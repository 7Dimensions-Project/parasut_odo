import requests
import time
import logging
from odoo import fields, models, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'


    parasut_client_id = fields.Char(string='Client ID', config_parameter='parasut.client_id')
    parasut_client_secret = fields.Char(string='Client Secret', config_parameter='parasut.client_secret')
    parasut_username = fields.Char(string='Username', config_parameter='parasut.username')
    parasut_password = fields.Char(string='Password', config_parameter='parasut.password')
    parasut_company_id = fields.Char(string='Company ID', config_parameter='parasut.company_id')

    def action_test_parasut_connection(self):
        """ Tests the connection to Parasut API using the provided credentials. """
        self.ensure_one()
        token_url = "https://api.parasut.com/oauth/token"
        
        payload = {
            'client_id': self.parasut_client_id,
            'client_secret': self.parasut_client_secret,
            'username': self.parasut_username,
            'password': self.parasut_password,
            'grant_type': 'password',
            'redirect_uri': 'urn:ietf:wg:oauth:2.0:oob',
        }

        try:
            # Send POST request to get the token
            response = requests.post(token_url, data=payload, timeout=10)
            response.raise_for_status() # Raise error for 4xx/5xx status codes
            
            data = response.json()
            if 'access_token' in data:
                # If we have an access token, the credentials are correct.
                # Optional: We could also check the Company ID if there's an endpoint for it,
                # but for now, auth success is good enough.
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Connection Successful'),
                        'message': _('Successfully authenticated with Parasut!'),
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                raise UserError(_("Authentication successful but no access token received."))

        except requests.exceptions.RequestException as e:
            error_msg = _("Connection Failed.")
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_data = e.response.json()
                    if 'error_description' in error_data:
                        error_msg = f"{error_msg} {error_data['error_description']}"
                    elif 'error' in error_data:
                        error_msg = f"{error_msg} {error_data['error']}"
                except ValueError:
                    error_msg = f"{error_msg} {str(e)}"
            else:
                 error_msg = f"{error_msg} {str(e)}"
            
            raise UserError(error_msg)

    
    def _get_parasut_headers(self):
        """ Tests connection and returns headers if successful. """
        self.ensure_one()
        token_url = "https://api.parasut.com/oauth/token"
        payload = {
            'client_id': self.parasut_client_id,
            'client_secret': self.parasut_client_secret,
            'username': self.parasut_username,
            'password': self.parasut_password,
            'grant_type': 'password',
            'redirect_uri': 'urn:ietf:wg:oauth:2.0:oob',
        }
        try:
            response = requests.post(token_url, data=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            return {
                'Authorization': f"Bearer {data['access_token']}",
                'Content-Type': 'application/json'
            }
        except Exception as e:
            raise UserError(_("Could not authenticate with Parasut. Please check credentials."))

    def _fetch_from_parasut(self, endpoint, params=None):
        """ Helper to fetch pages from Parasut API. Returns list of {data: [], included: []} batches. """
        headers = self._get_parasut_headers()
        base_url = "https://api.parasut.com/v4"
        company_id = self.parasut_company_id
        url = f"{base_url}/{company_id}/{endpoint}"
        
        results = []
        page = 1
        while True:
            current_params = params.copy() if params else {}
            current_params['page[size]'] = 25
            current_params['page[number]'] = page
            
            try:
                resp = requests.get(url, headers=headers, params=current_params, timeout=30)
                resp.raise_for_status()
                json_data = resp.json()
                
                data_list = json_data.get('data', [])
                if not data_list:
                    break
                    
                results.append({
                    'data': data_list,
                    'included': json_data.get('included', [])
                })
                
                meta = json_data.get('meta', {})
                if page >= meta.get('page_count', 0) or page > 20: # Limit to 20 pages for safety per run
                    break
                page += 1
            except Exception as e:
                raise UserError(f"Error fetching {endpoint}: {str(e)}")
            
        return results

    def _find_in_included(self, included, type_name, item_id):
        for inc in included:
            if inc.get('type') == type_name and inc.get('id') == item_id:
                return inc
        return None

    def _find_odoo_tax(self, vat_rate, type_tax_use):
        """Ultra-robust tax matching helper with auto-creation fallback.
        Returns: (tax_record or False, is_inclusive boolean)
        """
        if vat_rate is None:
            return False, False
        
        try:
            rate = float(vat_rate)
        except (ValueError, TypeError):
            return False, False

        # If rate is 0, we don't need to search
        if rate == 0:
            return False, False

        # Order of search:
        # 1. Exact amount match (Percent or Decimal) in requested usage (Sale/Purchase)
        # 2. Exact amount match in ANY usage
        # 3. Name match (contains rate) in ANY usage
        
        # Priority 1: Exact Amount + Exact Usage + INCLUSIVE ONLY
        taxes = self.env['account.tax'].search([
            ('amount', 'in', [rate, rate / 100.0]),
            ('type_tax_use', '=', type_tax_use),
            ('price_include', '=', True),
            ('active', '=', True)
        ], order='sequence')
        if taxes:
            return taxes[0], True

        # Priority 2: Exact Amount in ANY Usage + INCLUSIVE ONLY
        taxes = self.env['account.tax'].search([
            ('amount', 'in', [rate, rate / 100.0]),
            ('price_include', '=', True),
            ('active', '=', True)
        ], order='type_tax_use desc, sequence')
        if taxes:
            return taxes[0], True

        # Priority 3: Name Match ("%20", "20", etc.) + INCLUSIVE ONLY
        search_str = str(int(rate))
        taxes = self.env['account.tax'].search([
            ('name', 'ilike', search_str),
            ('price_include', '=', True),
            ('active', '=', True)
        ], order='sequence')
        if taxes:
            return taxes[0], True

        # FINAL SAFETY: Check for exact name collision before creating to avoid uniqueness error
        tax_name = f"Paraşüt KDV %{int(rate)} (Dahil - Oto)"
        existing_by_name = self.env['account.tax'].with_context(active_test=False).search([('name', '=', tax_name)], limit=1)
        
        # Prepare Account if possible (Mapping to 191 for Purchases)
        account_id = False
        if type_tax_use == 'purchase':
            account_191 = self.env['account.account'].search([('code', '=ilike', '191%')], limit=1)
            if account_191:
                account_id = account_191.id

        # Prepare Tax Group for labeling (Avoid %18 labels on %20 taxes)
        tax_group_name = f"KDV %{int(rate)}"
        tax_group = self.env['account.tax.group'].search([('name', '=ilike', tax_group_name)], limit=1)
        if not tax_group:
             tax_group = self.env['account.tax.group'].search([('name', 'ilike', 'KDV')], limit=1)

        if existing_by_name:
            if not existing_by_name.active:
                existing_by_name.active = True
            # Force correct settings even on existing taxes
            update_vals = {
                'price_include': True,
                'include_base_amount': False, # Critical: No "tax on tax"
            }
            if tax_group:
                update_vals['tax_group_id'] = tax_group.id
            existing_by_name.write(update_vals)
            return existing_by_name[0], True

        # FALLBACK: Create the inclusive tax if it doesn't exist.
        create_vals = {
            'name': tax_name,
            'amount': rate,
            'type_tax_use': type_tax_use,
            'amount_type': 'percent',
            'price_include': True,  # Forced to True for user request
            'include_base_amount': False, # Critical
            'description': f"%{int(rate)} (Dahil)",
        }
        if tax_group:
             create_vals['tax_group_id'] = tax_group.id
        
        if account_id:
            # In Odoo 17+, we map accounts via invoice_repartition_line_ids or similar
            # But for simplicity in many setups, setting it on repartition lines is better.
            # We'll try to set it if repartition lines are being created or exist.
            pass # Creating repartition lines from scratch is complex, we will focus on the math first.

        new_tax = self.env['account.tax'].create(create_vals)
        return new_tax, True

    def _parse_purchase_bill_detail(self, det_node, included, invoice_attrs):
        """Parse a purchase bill detail node into Odoo line values.
        Returns a dict suitable for (0, 0, line_vals).
        """
        d_attrs = det_node.get('attributes', {})
        line_vals = {
            'quantity': float(d_attrs.get('quantity', 1.0)),
            'price_unit': float(d_attrs.get('unit_price', 0.0)),
        }
        # Direct product name fields from detail
        product_name = d_attrs.get('product_name') or d_attrs.get('item_name') or d_attrs.get('service_name')
        # Relationship based product lookup
        if not product_name and det_node.get('relationships', {}).get('product', {}).get('data'):
            rel_data = det_node['relationships']['product']['data']
            prod_id = rel_data['id']
            prod_type = rel_data.get('type', 'products')
            # Try various type names in included
            prod_node = self._find_in_included(included, prod_type, prod_id)
            if not prod_node:
                prod_node = self._find_in_included(included, 'products', prod_id)
            if not prod_node:
                prod_node = self._find_in_included(included, 'product', prod_id)
            if prod_node:
                p_attrs = prod_node.get('attributes', {})
                product_name = p_attrs.get('name') or p_attrs.get('title') or p_attrs.get('product_name')
            # Link to Odoo product if exists
            product = self.env['product.template'].search([('parasut_id', '=', prod_id)], limit=1)
            if product:
                line_vals['product_id'] = product.product_variant_id.id
                if not product_name:
                    product_name = product.name
        # Name resolution hierarchy
        line_vals['name'] = (
            d_attrs.get('description')
            or d_attrs.get('name')
            or product_name
            or invoice_attrs.get('description')
            or 'Purchase Line'
        )
        # VAT handling
        vat_rate = d_attrs.get('vat_rate')
        tax, is_inclusive = self._find_odoo_tax(vat_rate, 'purchase')
        
        # Resilient Price Calculation Logic
        qty = line_vals['quantity'] or 1.0
        # Try different sources for net/unit price to avoid 0.00 results
        raw_net = float(d_attrs.get('net_total') or 0.0)
        raw_unit = float(d_attrs.get('unit_price') or 0.0)
        raw_total = float(d_attrs.get('total') or 0.0)
        raw_vat = float(d_attrs.get('vat_amount') or 0.0)

        if tax:
            line_vals['tax_ids'] = [(6, 0, [tax.id])]
            if is_inclusive:
                # Use GROSS price as unit price for inclusive taxes
                val_to_use = raw_total if raw_total > 0 else (raw_net + raw_vat if raw_net > 0 else raw_unit * (1 + (float(vat_rate or 0)/100.0)))
                line_vals['price_unit'] = val_to_use / qty
            else:
                # Use NET price for exclusive taxes
                if raw_unit > 0:
                    line_vals['price_unit'] = raw_unit
                elif raw_net > 0:
                    line_vals['price_unit'] = raw_net / qty
                else:
                    line_vals['price_unit'] = (raw_total - raw_vat) / qty
        else:
            # No tax: total, net, and unit_price should be same.
            val_to_use = raw_unit if raw_unit > 0 else (raw_net if raw_net > 0 else raw_total)
            line_vals['price_unit'] = val_to_use if (val_to_use == raw_unit) else (val_to_use / qty)

        return line_vals

    def action_sync_accounts(self):
        """ Sync Bank and Cash Accounts (Kasa/Banka) """
        batches = self._fetch_from_parasut('accounts')
        Journal = self.env['account.journal']
        
        created = 0
        updated = 0
        
        for batch in batches:
            for item in batch['data']:
                attrs = item['attributes']
                p_id = item['id']
                name = attrs.get('name')
                acc_type = 'cash' if attrs.get('account_type') == 'cash' else 'bank'
                
                # Logic: Find by Parasut ID -> Name
                journal = Journal.search([('parasut_id', '=', p_id)], limit=1)
                if not journal:
                    journal = Journal.search([('name', '=', name)], limit=1)
                
                vals = {
                    'parasut_id': p_id,
                    'name': name,
                    'type': acc_type,
                }
                
                if journal:
                    journal.write(vals)
                    updated += 1
                else:
                    # Generic code generation
                    code_base = name[:5].upper().replace(" ", "")
                    # Ensure code is unique
                    code = code_base
                    counter = 1
                    while Journal.search([('code', '=', code)]):
                        code = f"{code_base[:4]}{counter}"
                        counter += 1
                    
                    vals['code'] = code
                    Journal.create(vals)
                    created += 1

        return self._return_notification("Accounts Synced", f"{created} created, {updated} updated.")

    def action_sync_contacts(self):
        """ Sync Suppliers and Customers """
        batches = self._fetch_from_parasut('contacts', params={'sort': 'id'})
        Partner = self.env['res.partner']
        
        created = 0
        updated = 0
        
        for batch in batches:
            for item in batch['data']:
                attrs = item['attributes']
                p_id = item['id']
                
                # Build Full Address
                address_parts = [attrs.get('address'), attrs.get('district')]
                if attrs.get('tax_office'):
                    address_parts.append(f"Vergi D.: {attrs.get('tax_office')}")
                full_address = "\n".join([p for p in address_parts if p])
                
                # Build Notes
                notes_parts = []
                if attrs.get('short_name'): notes_parts.append(f"Kısa: {attrs.get('short_name')}")
                if attrs.get('iban'): notes_parts.append(f"IBAN: {attrs.get('iban')}")
                if attrs.get('mobile_phone'): notes_parts.append(f"Cep: {attrs.get('mobile_phone')}")
                notes = "\n".join(notes_parts)
                
                vals = {
                    'parasut_id': p_id,
                    'name': attrs.get('name'),
                    'email': attrs.get('email'),
                    'vat': attrs.get('tax_number'),
                    'street': full_address,
                    'city': attrs.get('city'),
                    'phone': attrs.get('phone') or attrs.get('mobile_phone'),
                    'comment': notes,
                    'is_company': attrs.get('contact_type') == 'company',
                    'supplier_rank': 1 if attrs.get('contact_type') == 'supplier' else 0,
                    'customer_rank': 1 if attrs.get('contact_type') == 'customer' else 0,
                }
                
                partner = Partner.search([('parasut_id', '=', p_id)], limit=1)
                if not partner and vals.get('vat'):
                    partner = Partner.search([('vat', '=', vals['vat'])], limit=1)
                # Fallback to name match if no ID/Tax ID
                if not partner:
                    partner = Partner.search([('name', '=', vals['name'])], limit=1)

                if partner:
                    partner.write(vals)
                    updated += 1
                else:
                    Partner.create(vals)
                    created += 1
                    
        return self._return_notification("Contacts Synced", f"{created} created, {updated} updated.")

    def action_sync_products(self):
        """ Sync Products (Ürünler) """
        batches = self._fetch_from_parasut('products', params={'sort': 'id'})
        Product = self.env['product.template']
        
        created = 0
        updated = 0
        
        for batch in batches:
            for item in batch['data']:
                attrs = item['attributes']
                p_id = item['id']
                
                vals = {
                    'parasut_id': p_id,
                    'name': attrs.get('name'),
                    'default_code': attrs.get('code'),  # Internal Reference
                    'list_price': float(attrs.get('list_price') or 0.0),
                    'standard_price': float(attrs.get('buying_price') or 0.0),
                    'type': 'consu',  # Consumable product (safe default)
                    'barcode': attrs.get('barcode'),
                }
                
                # VAT Rate
                vat_rate = attrs.get('vat_rate')
                tax, is_inclusive = self._find_odoo_tax(vat_rate, 'sale')
                if tax:
                    vals['taxes_id'] = [(6, 0, [tax.id])]
                
                product = Product.search([('parasut_id', '=', p_id)], limit=1)
                if not product and vals.get('default_code'):
                    product = Product.search([('default_code', '=', vals['default_code'])], limit=1)
                
                if product:
                    product.write(vals)
                    updated += 1
                else:
                    Product.create(vals)
                    created += 1
                    
        return self._return_notification("Products Synced", f"{created} created, {updated} updated.")

    def action_sync_sales_invoices(self):
        """ Sync Sales Invoices (Satış Faturaları) """
        params = {'include': 'details,details.product,contact', 'sort': '-issue_date'}
        batches = self._fetch_from_parasut('sales_invoices', params=params)
        Move = self.env['account.move']
        Partner = self.env['res.partner']
        Product = self.env['product.template']
        
        processed = 0
        
        for batch in batches:
            for item in batch['data']:
                attrs = item['attributes']
                p_id = item['id']
                
                # Check exist
                existing_move = Move.search([('parasut_id', '=', p_id), ('move_type', '=', 'out_invoice')], limit=1)
                
                # Resolve Partner (Customer)
                partner_id = False
                contact_data = item.get('relationships', {}).get('contact', {}).get('data')
                
                if contact_data:
                    contact_id = contact_data['id']
                    # 1. Match by Parasut ID
                    partner_obj = Partner.search([('parasut_id', '=', contact_id)], limit=1)
                    
                    if not partner_obj:
                        # 2. Match by Name if ID fails (find name in included)
                        contact_node = self._find_in_included(batch['included'], 'contacts', contact_id)
                        if contact_node:
                            c_name = contact_node['base_attributes' if 'base_attributes' in contact_node else 'attributes'].get('name')
                            if not c_name:
                                c_name = contact_node.get('attributes', {}).get('name')
                            
                            if c_name:
                                partner_obj = Partner.search([('name', '=', c_name)], limit=1)
                                if partner_obj:
                                    partner_obj.parasut_id = contact_id # Link them
                    
                    if partner_obj:
                        partner_id = partner_obj.id
                    else:
                        # 3. Create if still not found
                        contact_node = self._find_in_included(batch['included'], 'contacts', contact_id)
                        if contact_node:
                            attr_node = contact_node.get('attributes', {})
                            p_vals = {
                                'name': attr_node.get('name') or 'Paraşüt Müşteri',
                                'parasut_id': contact_id,
                            }
                            partner_id = Partner.create(p_vals).id
                            _logger.info(f"Created new partner for invoice {p_id}: {p_vals['name']}")

                if not partner_id:
                    _logger.warning(f"Skipping sales invoice {p_id}: Could not resolve partner.")
                    continue
                
                # Prepare Lines
                invoice_lines = []
                details_rels = item.get('relationships', {}).get('details', {}).get('data', [])
                
                for det in details_rels:
                    det_node = self._find_in_included(batch['included'], 'sales_invoice_details', det['id'])
                    if det_node:
                        d_attrs = det_node['attributes']
                        line_vals = {
                            'name': d_attrs.get('description') or attrs.get('description') or 'Sales Line',
                            'quantity': float(d_attrs.get('quantity', 1.0)),
                            'price_unit': float(d_attrs.get('unit_price', 0.0)),
                        }
                        
                        # Try to match product
                        if det_node.get('relationships', {}).get('product', {}).get('data'):
                            prod_id = det_node['relationships']['product']['data']['id']
                            product = Product.search([('parasut_id', '=', prod_id)], limit=1)
                            if product:
                                line_vals['product_id'] = product.product_variant_id.id

                        # VAT Rate
                        vat_rate = d_attrs.get('vat_rate')
                        tax, is_inclusive = self._find_odoo_tax(vat_rate, 'sale')

                        qty = line_vals['quantity'] or 1.0
                        raw_net = float(d_attrs.get('net_total') or 0.0)
                        raw_unit = float(d_attrs.get('unit_price') or 0.0)
                        raw_total = float(d_attrs.get('total') or 0.0)
                        raw_vat = float(d_attrs.get('vat_amount') or 0.0)

                        if tax:
                            line_vals['tax_ids'] = [(6, 0, [tax.id])]
                            if is_inclusive:
                                # Use GROSS price as unit price for inclusive taxes
                                val_to_use = raw_total if raw_total > 0 else (raw_net + raw_vat if raw_net > 0 else raw_unit * (1 + (float(vat_rate or 0)/100.0)))
                                line_vals['price_unit'] = val_to_use / qty
                            else:
                                # Use NET price for exclusive taxes
                                if raw_unit > 0:
                                    line_vals['price_unit'] = raw_unit
                                elif raw_net > 0:
                                    line_vals['price_unit'] = raw_net / qty
                                else:
                                    line_vals['price_unit'] = (raw_total - raw_vat) / qty
                        else:
                            val_to_use = raw_unit if raw_unit > 0 else (raw_net if raw_net > 0 else raw_total)
                            line_vals['price_unit'] = val_to_use if (val_to_use == raw_unit) else (val_to_use / qty)
                        
                        invoice_lines.append((0, 0, line_vals))
                
                # Fallback line
                if not invoice_lines:
                     invoice_lines.append((0, 0, {
                         'name': attrs.get('description', 'Sale'),
                         'quantity': 1,
                         'price_unit': float(attrs.get('net_total', 0)),
                     }))

                move_vals = {
                    'move_type': 'out_invoice',
                    'parasut_id': p_id,
                    'partner_id': partner_id,
                    'parasut_total_visual': float(attrs.get('total') or 0.0),
                    'invoice_date': attrs.get('issue_date') or fields.Date.today(),
                    'date': attrs.get('issue_date') or fields.Date.today(),
                    'invoice_date_due': attrs.get('due_date') or attrs.get('issue_date') or fields.Date.today(),
                    'ref': f"SLS-{p_id}",
                    'invoice_line_ids': invoice_lines,
                }
                
                if existing_move:
                    # UPDATE logic similar to purchase bills
                    if existing_move.state == 'posted':
                        existing_move.button_draft()
                    move_vals['invoice_line_ids'].insert(0, (5, 0, 0)) # Clear lines
                    existing_move.write(move_vals)
                    existing_move.action_post()
                else:
                    # CREATE
                    move = Move.create(move_vals)
                    move.action_post()
                
                processed += 1
        
        return self._return_notification("Sales Invoices Synced", f"{processed} invoices processed (created/updated).")

    def action_sync_sales_payments(self):
        """ Sync Sales Payments (Müşteri Tahsilatları) """
        Move = self.env['account.move']
        Journal = self.env['account.journal']
        PaymentRegister = self.env['account.payment.register']
        
        # Find Open Sales Invoices
        open_invoices = Move.search([
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('payment_state', '!=', 'paid'),
            ('parasut_id', '!=', False)
        ], limit=50)

        if not open_invoices:
             return self._return_notification("Odoo Güncel", "Ödenmemiş satış faturası bulunamadı.")

        headers = self._get_parasut_headers()
        base_url = "https://api.parasut.com/v4"
        company_id = self.parasut_company_id

        processed_count = 0
        
        for invoice in open_invoices:
            try:
                time.sleep(0.5)
                
                url = f"{base_url}/{company_id}/sales_invoices/{invoice.parasut_id}"
                params = {'include': 'payments'} 
                
                response = requests.get(url, headers=headers, params=params, timeout=10)
                if response.status_code == 429:
                    return self._return_notification("Rate Limit", f"Processed {processed_count}. Wait and retry.")
                if response.status_code != 200:
                    continue

                data = response.json()
                main_data = data.get('data', {})
                included = data.get('included', [])

                payments_rel = main_data.get('relationships', {}).get('payments', {}).get('data', [])
                if not payments_rel:
                    continue
                
                payment_list = payments_rel if isinstance(payments_rel, list) else [payments_rel]
                
                for pay_ref in payment_list:
                    p_id = pay_ref['id']
                    payment_obj = self._find_in_included(included, 'payments', p_id)
                    if not payment_obj:
                         continue
                    
                    p_attrs = payment_obj.get('attributes')
                    amount = float(p_attrs.get('amount') or 0.0)
                    p_date = p_attrs.get('date')
                    
                    journal_id = False
                    
                    # Try to find account
                    acc_rel = payment_obj.get('relationships', {}).get('account', {}).get('data') 
                    if acc_rel:
                         j_finder = Journal.search([('parasut_id', '=', acc_rel['id'])], limit=1)
                         if j_finder: journal_id = j_finder.id
                    
                    if not journal_id:
                        journal_id = Journal.search([('type', '=', 'bank')], limit=1).id
                    
                    if not journal_id:
                        continue
                        
                    try:
                        ctx = {
                            'active_model': 'account.move',
                            'active_ids': [invoice.id],
                        }
                        register = PaymentRegister.with_context(ctx).create({
                            'amount': amount,
                            'payment_date': p_date,
                            'journal_id': journal_id,
                            'communication': f"Tahsilat: {invoice.name}",
                        })
                        register.action_create_payments()
                    except Exception as e:
                        _logger.error(f"Error creating payment for sales invoice {invoice.id}: {e}")
            
            except Exception as e:
                _logger.error(f"Error processing sales invoice {invoice.id}: {e}")
                
            processed_count += 1

        return self._return_notification("Tahsilatlar Kontrol Edildi", f"{processed_count} fatura kontrol edildi.")

    def action_sync_employees(self):
        """ Sync Employees (Çalışanlar) """
        batches = self._fetch_from_parasut('employees', params={'sort': 'id'})
        Employee = self.env['hr.employee']
        
        created = 0
        updated = 0
        
        for batch in batches:
            for item in batch['data']:
                attrs = item['attributes']
                p_id = item['id']
                
                vals = {
                    'parasut_id': p_id,
                    'name': attrs.get('name'),
                    'work_email': attrs.get('email'),
                    'mobile_phone': attrs.get('phone'),
                    'identification_id': attrs.get('iban'),  # IBAN bilgisi
                }
                
                employee = Employee.search([('parasut_id', '=', p_id)], limit=1)
                if not employee:
                    employee = Employee.search([('name', '=', vals['name'])], limit=1)
                
                if employee:
                    employee.write(vals)
                    updated += 1
                else:
                    Employee.create(vals)
                    created += 1
                    
        return self._return_notification("Employees Synced", f"{created} created, {updated} updated.")

    def action_sync_salaries(self):
        """ Sync Salaries as Journal Entries (Maaş Kayıtları) """
        params = {'include': 'employee', 'sort': '-id'}
        batches = self._fetch_from_parasut('salaries', params=params)
        Move = self.env['account.move']
        Employee = self.env['hr.employee']
        Journal = self.env['account.journal']
        
        processed = 0
        
        # Find or create general journal
        general_journal = Journal.search([('type', '=', 'general')], limit=1)
        if not general_journal:
            return self._return_notification("Hata", "Genel yevmiye defteri bulunamadı.")
        
        for batch in batches:
            for item in batch['data']:
                attrs = item['attributes']
                p_id = item['id']
                
                # Check if exists
                if Move.search([('parasut_id', '=', p_id), ('ref', 'like', 'MAAS-%')], limit=1):
                    continue
                
                # Find Employee and associated Partner
                employee_name = "Çalışan"
                partner_id = False
                if item.get('relationships', {}).get('employee', {}).get('data'):
                    emp_id = item['relationships']['employee']['data']['id']
                    emp_obj = Employee.search([('parasut_id', '=', emp_id)], limit=1)
                    if emp_obj:
                        employee_name = emp_obj.name
                        # Link to employee's partner if available, otherwise find/create by name
                        partner = emp_obj.address_home_id or self.env['res.partner'].search([('name', '=', employee_name)], limit=1)
                        if not partner:
                            partner = self.env['res.partner'].create({'name': employee_name, 'supplier_rank': 1})
                        partner_id = partner.id
                    else:
                        # Try from included
                        emp_node = self._find_in_included(batch['included'], 'employees', emp_id)
                        if emp_node:
                            employee_name = emp_node['attributes']['name']
                            partner = self.env['res.partner'].search([('name', '=', employee_name)], limit=1)
                            if not partner:
                                partner = self.env['res.partner'].create({'name': employee_name, 'supplier_rank': 1})
                            partner_id = partner.id
                
                if not partner_id:
                    # Fallback for "Vergi/SGK" or unknown employees
                    partner = self.env['res.partner'].search([('name', '=', employee_name)], limit=1)
                    if not partner:
                        partner = self.env['res.partner'].create({'name': employee_name, 'supplier_rank': 1})
                    partner_id = partner.id

                # Robust amount detection (checking all potential Paraşüt fields)
                amount = float(attrs.get('net_total') or attrs.get('amount') or attrs.get('total_paid') or 0.0)
                date = attrs.get('payment_date') or attrs.get('date') or fields.Date.today()
                
                if amount <= 0:
                    _logger.warning(f"Skipping Salary {p_id} because amount is zero.")
                    continue

                # Create Journal Entry
                # Try to find a suitable expense account (starting with 770 or any expense)
                expense_account = self.env['account.account'].search([
                    ('code', '=like', '770%'),
                    ('account_type', '=', 'expense')
                ], limit=1) or self.env['account.account'].search([
                    ('account_type', '=', 'expense')
                ], limit=1)
                
                # Try to find a suitable payable account (starting with 335 or any payable)
                payable_account = self.env['account.account'].search([
                    ('code', '=like', '335%'),
                    ('account_type', '=', 'liability_payable')
                ], limit=1) or self.env['account.account'].search([
                    ('account_type', '=', 'liability_payable')
                ], limit=1)
                
                if not expense_account or not payable_account:
                    _logger.error(f"Could not find suitable accounts for Salary {p_id}.")
                    continue
                
                move_lines = [
                    (0, 0, {
                        'account_id': expense_account.id,
                        'partner_id': partner_id,
                        'name': f"Maaş: {employee_name}",
                        'debit': amount,
                        'credit': 0,
                    }),
                    (0, 0, {
                        'account_id': payable_account.id,
                        'partner_id': partner_id,
                        'name': f"Maaş: {employee_name}",
                        'debit': 0,
                        'credit': amount,
                    })
                ]
                
                move_vals = {
                    'move_type': 'entry',
                    'parasut_id': p_id,
                    'journal_id': general_journal.id,
                    'date': date,
                    'ref': f"MAAS-{p_id} ({employee_name})",
                    'line_ids': move_lines,
                }
                
                move = Move.create(move_vals)
                move.action_post()
                processed += 1
        
        return self._return_notification("Salaries Synced", f"{processed} salary entries created.")

    def action_sync_taxes(self):
        """ Sync Tax Payments as Journal Entries (Vergi Ödemeleri) """
        params = {'sort': '-id'}
        batches = self._fetch_from_parasut('taxes', params=params)
        Move = self.env['account.move']
        Journal = self.env['account.journal']
        
        processed = 0
        
        # Find or create general journal
        general_journal = Journal.search([('type', '=', 'general')], limit=1)
        if not general_journal:
            return self._return_notification("Hata", "Genel yevmiye defteri bulunamadı.")
        
        for batch in batches:
            for item in batch['data']:
                attrs = item['attributes']
                p_id = item['id']
                
                # Check if exists
                if Move.search([('parasut_id', '=', p_id), ('ref', 'like', 'VERGI-%')], limit=1):
                    continue
                
                tax_name = attrs.get('name') or "Vergi Ödemesi"
                # Robust amount detection
                amount = float(attrs.get('net_total') or attrs.get('amount') or attrs.get('total_paid') or 0.0)
                date = attrs.get('payment_date') or attrs.get('date') or fields.Date.today()
                
                if amount <= 0:
                    _logger.warning(f"Skipping Tax {p_id} because amount is zero.")
                    continue

                # Resolve Partner for Tax (Vergi Dairesi / SGK)
                partner_name = "Vergi Dairesi / SGK"
                tax_partner = self.env['res.partner'].search([('name', '=', partner_name)], limit=1)
                if not tax_partner:
                    tax_partner = self.env['res.partner'].create({'name': partner_name, 'supplier_rank': 1})
                
                # Create Journal Entry
                expense_account = self.env['account.account'].search([
                    ('code', '=like', '770%'),
                    ('account_type', '=', 'expense')
                ], limit=1) or self.env['account.account'].search([
                    ('account_type', '=', 'expense')
                ], limit=1)
                
                payable_account = self.env['account.account'].search([
                    ('code', '=like', '360%'),
                    ('account_type', '=', 'liability_current')
                ], limit=1) or self.env['account.account'].search([
                    ('account_type', 'in', ['liability_current', 'liability_payable'])
                ], limit=1)
                
                if not expense_account or not payable_account:
                    _logger.error(f"Could not find suitable accounts for Tax {p_id}.")
                    continue
                
                move_lines = [
                    (0, 0, {
                        'account_id': expense_account.id,
                        'partner_id': tax_partner.id,
                        'name': f"Vergi: {tax_name}",
                        'debit': amount,
                        'credit': 0,
                    }),
                    (0, 0, {
                        'account_id': payable_account.id,
                        'partner_id': tax_partner.id,
                        'name': f"Vergi: {tax_name}",
                        'debit': 0,
                        'credit': amount,
                    })
                ]
                
                move_vals = {
                    'move_type': 'entry',
                    'parasut_id': p_id,
                    'journal_id': general_journal.id,
                    'date': date,
                    'ref': f"VERGI-{p_id} ({tax_name})",
                    'line_ids': move_lines,
                }
                
                move = Move.create(move_vals)
                move.action_post()
                processed += 1
        
        return self._return_notification("Taxes Synced", f"{processed} tax entries created.")

    def action_sync_purchase_bills(self):
        """ Sync Purchase Bills (Gider Faturaları) """
        # Removed filter[date_type] as it was causing 400 Bad Request
        params = {'include': 'details,details.product,supplier', 'sort': '-issue_date'}
        batches = self._fetch_from_parasut('purchase_bills', params=params)
        Move = self.env['account.move']
        Partner = self.env['res.partner']
        Product = self.env['product.template']
        
        processed = 0
        
        for batch in batches:
            for item in batch['data']:
                attrs = item['attributes']
                p_id = item['id']
                
                # Check exist
                existing_move = Move.search([('parasut_id', '=', p_id), ('move_type', '=', 'in_invoice')], limit=1)
                # Removed 'continue' to allow updates
                
                # Resolve Partner
                partner_id = False
                if item.get('relationships', {}).get('supplier', {}).get('data'):
                    supp_id = item['relationships']['supplier']['data']['id']
                    partner_obj = Partner.search([('parasut_id', '=', supp_id)], limit=1)
                    if partner_obj:
                        partner_id = partner_obj.id
                
                if not partner_id:
                     supp_data = item['relationships']['supplier']['data']
                     if supp_data:
                         supp_node = self._find_in_included(batch['included'], 'contacts', supp_data['id'])
                         if supp_node:
                             p_vals = {'name': supp_node['attributes']['name'], 'parasut_id': supp_data['id'], 'supplier_rank': 1}
                             partner_id = Partner.create(p_vals).id

                if not partner_id:
                    continue 
                
                # Prepare Lines
                invoice_lines = []
                details_rels = item.get('relationships', {}).get('details', {}).get('data', [])
                for det in details_rels:
                    det_node = self._find_in_included(batch['included'], 'purchase_bill_details', det['id'])
                    if det_node:
                        line_vals = self._parse_purchase_bill_detail(det_node, batch['included'], attrs)
                        invoice_lines.append((0, 0, line_vals))
                
                # Fallback line
                if not invoice_lines:
                     line_vals = {
                         'name': attrs.get('description', 'Bill'),
                         'quantity': 1,
                         'price_unit': float(attrs.get('net_total', 0)),
                     }
                     # Paraşüt doesn't always provide VAT on header, usually it's in details.
                     # But if we have no details, we just assume no tax or use a default if needed.
                     invoice_lines.append((0, 0, line_vals))

                move_vals = {
                    'move_type': 'in_invoice',
                    'parasut_id': p_id,
                    'partner_id': partner_id,
                    'parasut_total_visual': float(attrs.get('total') or 0.0),
                    'invoice_date': attrs.get('issue_date') or fields.Date.today(),
                    'date': attrs.get('issue_date') or fields.Date.today(),
                    'invoice_date_due': attrs.get('due_date') or attrs.get('issue_date') or fields.Date.today(),
                    'ref': f"PRS-{p_id}",
                    'invoice_line_ids': invoice_lines,
                }
                
                if existing_move:
                    # UPDATE
                    if existing_move.state == 'posted':
                        existing_move.button_draft()
                    
                    # Clear existing lines to prevent duplication
                    move_vals['invoice_line_ids'].insert(0, (5, 0, 0))
                    
                    existing_move.write(move_vals)
                    existing_move.action_post()
                    # processed += 1 # Count updates as processed too
                else:
                    # CREATE
                    move = Move.create(move_vals)
                    move.action_post()
                
                processed += 1
        
        return self._return_notification("Bills Synced", f"{processed} bills processed (created/updated).")

    def action_sync_payments(self):
        """ Sync Payments (Smart Mode: Supporting Bills, Salaries, and Taxes) """
        Move = self.env['account.move']
        Journal = self.env['account.journal']
        PaymentRegister = self.env['account.payment.register']
        
        # 1. Find Open Payables in Odoo
        open_payables = Move.search([
            ('move_type', 'in', ['in_invoice', 'entry']),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ['not_paid', 'partial']),
            ('parasut_id', '!=', False)
        ], limit=50)

        if not open_payables:
             return self._return_notification("Odoo Güncel", "Ödenmemiş borç kaydı bulunamadı.")

        headers = self._get_parasut_headers()
        base_url = "https://api.parasut.com/v4"
        company_id = self.parasut_company_id

        processed_count = 0
        
        for move in open_payables:
            try:
                time.sleep(0.5) 
                
                # Determine Endpoint
                endpoint = "purchase_bills"
                if move.ref and move.ref.startswith('MAAS-'):
                    endpoint = "salaries"
                elif move.ref and move.ref.startswith('VERGI-'):
                    endpoint = "taxes"
                
                # Fetch Record with Payments
                url = f"{base_url}/{company_id}/{endpoint}/{move.parasut_id}"
                params = {'include': 'payments'} 
                
                response = requests.get(url, headers=headers, params=params, timeout=10)
                if response.status_code == 429:
                    return self._return_notification("Rate Limit Hit", f"Processed {processed_count} records. Please retry.")
                if response.status_code != 200:
                    continue

                data = response.json()
                main_data = data.get('data', {})
                included = data.get('included', [])

                payments_rel = main_data.get('relationships', {}).get('payments', {}).get('data', [])
                if not payments_rel:
                    continue
                
                payment_list = payments_rel if isinstance(payments_rel, list) else [payments_rel]
                
                for pay_ref in payment_list:
                    p_id = pay_ref['id']
                    payment_obj = self._find_in_included(included, 'payments', p_id)
                    if not payment_obj:
                         continue
                    
                    p_attrs = payment_obj.get('attributes')
                    amount = float(p_attrs.get('amount') or 0.0)
                    p_date = p_attrs.get('date')
                    
                    journal_id = False
                    
                    # 1. Try account relationship (most common for bank/cash)
                    acc_rel = payment_obj.get('relationships', {}).get('account', {}).get('data') 
                    
                    if not acc_rel:
                        # 2. Try transaction relationship
                        trans_rel = payment_obj.get('relationships', {}).get('transaction', {}).get('data')
                        if trans_rel:
                            t_url = f"{base_url}/{company_id}/transactions/{trans_rel['id']}"
                            t_params = {'include': 'credit_account,debit_account'}
                            try:
                                t_resp = requests.get(t_url, headers=headers, params=t_params, timeout=10)
                                if t_resp.status_code == 200:
                                    t_data = t_resp.json()
                                    t_included = t_data.get('included', [])
                                    for inc in t_included:
                                        if inc.get('type') == 'accounts':
                                            j_finder = Journal.search([('parasut_id', '=', inc['id'])], limit=1)
                                            if j_finder:
                                                journal_id = j_finder.id
                                                break
                            except:
                                pass
                    
                    if not journal_id and acc_rel:
                         j_finder = Journal.search([('parasut_id', '=', acc_rel['id'])], limit=1)
                         if j_finder: journal_id = j_finder.id
                    
                    if not journal_id:
                        journal_id = Journal.search([('type', '=', 'bank')], limit=1).id
                    
                    if not journal_id:
                        continue
                        
                    try:
                        ctx = {
                            'active_model': 'account.move',
                            'active_ids': [move.id],
                        }
                        register = PaymentRegister.with_context(ctx).create({
                            'amount': amount,
                            'payment_date': p_date,
                            'journal_id': journal_id,
                            'communication': f"{move.ref} - Ödeme: {p_id}",
                        })
                        register.action_create_payments()
                    except Exception as e:
                        _logger.error(f"Error creating payment for record {move.id}: {e}")
            except Exception as e:
                _logger.error(f"Error processing record {move.id}: {e}")
            
            processed_count += 1

        return self._return_notification("Kontrol Edildi", f"{processed_count} adet borç kaydı için ödemeler senkronize edildi.")

    def _return_notification(self, title, message):
         return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _(title),
                'message': _(message),
                'type': 'success',
            }
        }


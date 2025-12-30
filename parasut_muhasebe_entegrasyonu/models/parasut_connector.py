import requests
import json
import time
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class ParasutConnector(models.TransientModel):
    _name = 'parasut.connector'
    _description = 'Parasut Integration Connector'

    @api.model
    def _get_parasut_headers(self):
        """ Fetch credentials from settings and return headers with token. """
        params = self.env['ir.config_parameter'].sudo()
        client_id = params.get_param('parasut.client_id')
        client_secret = params.get_param('parasut.client_secret')
        username = params.get_param('parasut.username')
        password = params.get_param('parasut.password')

        if not all([client_id, client_secret, username, password]):
            raise UserError(_("Parasut API credentials are not fully configured in Settings."))

        token_url = "https://api.parasut.com/oauth/token"
        payload = {
            'client_id': client_id,
            'client_secret': client_secret,
            'username': username,
            'password': password,
            'grant_type': 'password',
            'redirect_uri': 'urn:ietf:wg:oauth:2.0:oob',
        }
        try:
            response = requests.post(token_url, data=payload, timeout=15)
            response.raise_for_status()
            data = response.json()
            return {
                'Authorization': f"Bearer {data['access_token']}",
                'Content-Type': 'application/json'
            }
        except Exception as e:
            _logger.error("Parasut Authentication Failed: %s", str(e))
            raise UserError(_("Could not authenticate with Parasut. Please check credentials in General Settings."))

    def _fetch_from_parasut(self, endpoint, params=None):
        """ Helper to fetch pages from Parasut API. """
        headers = self._get_parasut_headers()
        base_url = "https://api.parasut.com/v4"
        company_id = self.env['ir.config_parameter'].sudo().get_param('parasut.company_id')
        if not company_id:
            raise UserError(_("Parasut Company ID is missing in Settings."))
            
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
                if page >= meta.get('page_count', 0) or page > 20: # Limit for safety
                    break
                page += 1
            except Exception as e:
                _logger.error("Error fetching %s from Parasut: %s", endpoint, str(e))
                break # Stop fetching on error to avoid partial data issues
            
        return results

    def _find_in_included(self, included, type_name, item_id):
        for inc in included:
            if inc.get('type') == type_name and inc.get('id') == item_id:
                return inc
        return None

    # --- Sync Actions ---

    def action_sync_accounts(self):
        batches = self._fetch_from_parasut('accounts')
        Journal = self.env['account.journal']
        created = updated = 0
        for batch in batches:
            for item in batch['data']:
                attrs = item['attributes']
                p_id = item['id']
                name = attrs.get('name')
                acc_type = 'cash' if attrs.get('account_type') == 'cash' else 'bank'
                
                journal = Journal.search([('parasut_id', '=', p_id)], limit=1)
                if not journal:
                    journal = Journal.search([('name', '=', name)], limit=1)
                
                vals = {'parasut_id': p_id, 'name': name, 'type': acc_type}
                if journal:
                    journal.write(vals)
                    updated += 1
                else:
                    code_base = name[:5].upper().replace(" ", "")
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
        batches = self._fetch_from_parasut('contacts', params={'sort': 'id'})
        Partner = self.env['res.partner']
        created = updated = 0
        for batch in batches:
            for item in batch['data']:
                attrs = item['attributes']
                p_id = item['id']
                
                address_parts = [attrs.get('address'), attrs.get('district')]
                if attrs.get('tax_office'):
                    address_parts.append(f"Vergi D.: {attrs.get('tax_office')}")
                full_address = "\n".join([p for p in address_parts if p])
                
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
        batches = self._fetch_from_parasut('products', params={'sort': 'id'})
        Product = self.env['product.template']
        created = updated = 0
        for batch in batches:
            for item in batch['data']:
                attrs = item['attributes']
                p_id = item['id']
                vals = {
                    'parasut_id': p_id,
                    'name': attrs.get('name'),
                    'default_code': attrs.get('code'),
                    'list_price': float(attrs.get('list_price') or 0.0),
                    'standard_price': float(attrs.get('buying_price') or 0.0),
                    'type': 'consu',
                    'barcode': attrs.get('barcode'),
                }
                vat_rate = attrs.get('vat_rate')
                if vat_rate:
                    tax = self.env['account.tax'].search([('amount', '=', float(vat_rate)), ('type_tax_use', '=', 'sale')], limit=1)
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
        params = {'include': 'details,contact', 'sort': '-issue_date'}
        batches = self._fetch_from_parasut('sales_invoices', params=params)
        Move = self.env['account.move']
        Partner = self.env['res.partner']
        Product = self.env['product.template']
        processed = 0
        for batch in batches:
            for item in batch['data']:
                attrs = item['attributes']
                p_id = item['id']
                if Move.search([('parasut_id', '=', p_id), ('move_type', '=', 'out_invoice')], limit=1):
                    continue
                
                partner_id = False
                if item.get('relationships', {}).get('contact', {}).get('data'):
                    contact_id = item['relationships']['contact']['data']['id']
                    partner_obj = Partner.search([('parasut_id', '=', contact_id)], limit=1)
                    if partner_obj:
                        partner_id = partner_obj.id
                
                if not partner_id:
                    continue
                
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
                        if det_node.get('relationships', {}).get('product', {}).get('data'):
                            prod_id = det_node['relationships']['product']['data']['id']
                            product = Product.search([('parasut_id', '=', prod_id)], limit=1)
                            if product:
                                line_vals['product_id'] = product.product_variant_id.id
                        
                        vat_rate = d_attrs.get('vat_rate')
                        if vat_rate:
                            tax = self.env['account.tax'].search([('amount', '=', float(vat_rate)), ('type_tax_use', '=', 'sale'), ('price_include', '=', False)], limit=1)
                            if tax:
                                line_vals['tax_ids'] = [(6, 0, [tax.id])]
                        invoice_lines.append((0, 0, line_vals))
                
                if not invoice_lines:
                     invoice_lines.append((0, 0, {'name': attrs.get('description', 'Sale'), 'quantity': 1, 'price_unit': float(attrs.get('net_total', 0))}))

                move_vals = {
                    'move_type': 'out_invoice',
                    'parasut_id': p_id,
                    'partner_id': partner_id,
                    'invoice_date': attrs.get('issue_date') or fields.Date.today(),
                    'date': attrs.get('issue_date') or fields.Date.today(),
                    'invoice_date_due': attrs.get('due_date') or attrs.get('issue_date') or fields.Date.today(),
                    'ref': f"SLS-{p_id}",
                    'invoice_line_ids': invoice_lines,
                }
                move = Move.create(move_vals)
                move.action_post()
                processed += 1
        return self._return_notification("Sales Invoices Synced", f"{processed} invoices created.")

    def action_sync_purchase_bills(self):
        params = {'include': 'details,supplier', 'sort': '-issue_date'}
        batches = self._fetch_from_parasut('purchase_bills', params=params)
        Move = self.env['account.move']
        Partner = self.env['res.partner']
        processed = 0
        for batch in batches:
            for item in batch['data']:
                attrs = item['attributes']
                p_id = item['id']
                if Move.search([('parasut_id', '=', p_id), ('move_type', '=', 'in_invoice')], limit=1):
                    continue
                
                partner_id = False
                if item.get('relationships', {}).get('supplier', {}).get('data'):
                    supp_id = item['relationships']['supplier']['data']['id']
                    partner_obj = Partner.search([('parasut_id', '=', supp_id)], limit=1)
                    if partner_obj:
                        partner_id = partner_obj.id
                
                if not partner_id:
                    continue 
                
                invoice_lines = []
                details_rels = item.get('relationships', {}).get('details', {}).get('data', [])
                for det in details_rels:
                    det_node = self._find_in_included(batch['included'], 'purchase_bill_details', det['id'])
                    if det_node:
                        d_attrs = det_node['attributes']
                        line_vals = {
                            'name': d_attrs.get('name') or attrs.get('description') or 'Purchase Line',
                            'quantity': float(d_attrs.get('quantity', 1.0)),
                            'price_unit': float(d_attrs.get('unit_price', 0.0)),
                        }
                        vat_rate = d_attrs.get('vat_rate')
                        if vat_rate:
                            tax = self.env['account.tax'].search([('amount', '=', float(vat_rate)), ('type_tax_use', '=', 'purchase'), ('price_include', '=', False)], limit=1)
                            if tax:
                                line_vals['tax_ids'] = [(6, 0, [tax.id])]
                        invoice_lines.append((0, 0, line_vals))
                
                if not invoice_lines:
                     invoice_lines.append((0, 0, {'name': attrs.get('description', 'Bill'), 'quantity': 1, 'price_unit': float(attrs.get('net_total', 0))}))

                move_vals = {
                    'move_type': 'in_invoice',
                    'parasut_id': p_id,
                    'partner_id': partner_id,
                    'invoice_date': attrs.get('issue_date') or fields.Date.today(),
                    'date': attrs.get('issue_date') or fields.Date.today(),
                    'invoice_date_due': attrs.get('due_date') or attrs.get('issue_date') or fields.Date.today(),
                    'ref': f"PRS-{p_id}",
                    'invoice_line_ids': invoice_lines,
                }
                move = Move.create(move_vals)
                move.action_post()
                processed += 1
        return self._return_notification("Bills Synced", f"{processed} bills created.")

    def action_sync_payments(self):
        """ Sync Payables Payments """
        Move = self.env['account.move']
        Journal = self.env['account.journal']
        PaymentRegister = self.env['account.payment.register']
        
        open_payables = Move.search([
            ('move_type', 'in', ['in_invoice', 'entry']),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ['not_paid', 'partial']),
            ('parasut_id', '!=', False)
        ], limit=50)

        if not open_payables:
            return self._return_notification("Status", "No unpaid payables found.")

        headers = self._get_parasut_headers()
        base_url = "https://api.parasut.com/v4"
        company_id = self.env['ir.config_parameter'].sudo().get_param('parasut.company_id')

        processed_count = 0
        for move in open_payables:
            try:
                endpoint = "purchase_bills"
                if move.ref and move.ref.startswith('MAAS-'): endpoint = "salaries"
                elif move.ref and move.ref.startswith('VERGI-'): endpoint = "taxes"
                
                url = f"{base_url}/{company_id}/{endpoint}/{move.parasut_id}"
                params = {'include': 'payments'} 
                response = requests.get(url, headers=headers, params=params, timeout=10)
                if response.status_code != 200: continue

                data = response.json()
                main_data = data.get('data', {})
                included = data.get('included', [])
                payments_rel = main_data.get('relationships', {}).get('payments', {}).get('data', [])
                if not payments_rel: continue
                
                payment_list = payments_rel if isinstance(payments_rel, list) else [payments_rel]
                for pay_ref in payment_list:
                    p_id = pay_ref['id']
                    payment_obj = self._find_in_included(included, 'payments', p_id)
                    if not payment_obj: continue
                    
                    p_attrs = payment_obj.get('attributes')
                    amount = float(p_attrs.get('amount') or 0.0)
                    p_date = p_attrs.get('date')
                    
                    journal_id = False
                    acc_rel = payment_obj.get('relationships', {}).get('account', {}).get('data') 
                    if acc_rel:
                        j_finder = Journal.search([('parasut_id', '=', acc_rel['id'])], limit=1)
                        if j_finder: journal_id = j_finder.id
                    
                    if not journal_id:
                        journal_id = Journal.search([('type', '=', 'bank')], limit=1).id
                    
                    if not journal_id: continue
                        
                    ctx = {'active_model': 'account.move', 'active_ids': [move.id]}
                    register = PaymentRegister.with_context(ctx).create({
                        'amount': amount,
                        'payment_date': p_date,
                        'journal_id': journal_id,
                        'communication': f"{move.ref} - Pay: {p_id}",
                    })
                    register.action_create_payments()
            except Exception as e:
                _logger.error("Error syncing payment for %s: %s", move.ref, str(e))
            processed_count += 1
        return self._return_notification("Payments Synced", f"{processed_count} records checked.")

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

from odoo import fields, models

class AccountMove(models.Model):
    _inherit = 'account.move'

    parasut_id = fields.Char(string='Parasut Invoice ID', help="Unique ID from Parasut", copy=False, index=True)
    parasut_payment_status = fields.Selection([
        ('unpaid', 'Unpaid'),
        ('paid', 'Paid'),
        ('partially_paid', 'Partially Paid')
    ], string='Parasut Payment Status', help="Payment status received from Parasut")
    
    parasut_total_visual = fields.Monetary(string='Toplam (Vergi dahil) - P', help="Paraşüt'ten gelen vergi dahil toplam tutar")
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id')

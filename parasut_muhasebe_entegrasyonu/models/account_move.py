from odoo import fields, models

class AccountMove(models.Model):
    _inherit = 'account.move'

    parasut_id = fields.Char(string='Parasut Invoice ID', help="Unique ID from Parasut", copy=False, index=True)
    parasut_payment_status = fields.Selection([
        ('unpaid', 'Unpaid'),
        ('paid', 'Paid'),
        ('partially_paid', 'Partially Paid')
    ], string='Parasut Payment Status', help="Payment status received from Parasut")

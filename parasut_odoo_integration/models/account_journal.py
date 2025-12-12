from odoo import fields, models

class AccountJournal(models.Model):
    _inherit = 'account.journal'

    parasut_id = fields.Char(string='Parasut Account ID', help="Unique ID from Parasut for Banks/Cash", copy=False, index=True)

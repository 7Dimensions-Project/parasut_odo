from odoo import fields, models

class ResPartner(models.Model):
    _inherit = 'res.partner'

    parasut_id = fields.Char(string='Parasut Follow ID', help="Unique ID from Parasut", copy=False, index=True)

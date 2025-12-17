from odoo import fields, models

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    parasut_id = fields.Char(string='Parasut Product ID', help="Unique ID from Parasut", copy=False, index=True)
    parasut_code = fields.Char(string='Parasut Code', help="Product code from Parasut")

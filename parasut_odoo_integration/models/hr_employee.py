from odoo import fields, models

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    parasut_id = fields.Char(string='Parasut Employee ID', help="Unique ID from Parasut", copy=False, index=True)

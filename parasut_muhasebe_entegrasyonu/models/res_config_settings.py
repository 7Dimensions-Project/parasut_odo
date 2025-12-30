import requests
import logging
from odoo import fields, models, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    parasut_client_id = fields.Char(string='Client ID', config_parameter='parasut.client_id')
    parasut_client_secret = fields.Char(string='Client Secret', config_parameter='parasut.client_secret', groups='base.group_system')
    parasut_username = fields.Char(string='Username', config_parameter='parasut.username')
    parasut_password = fields.Char(string='Password', config_parameter='parasut.password', groups='base.group_system')
    parasut_company_id = fields.Char(string='Company ID', config_parameter='parasut.company_id')

    def action_test_parasut_connection(self):
        """ Tests the connection to Parasut API. """
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
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connection Successful'),
                    'message': _('Successfully authenticated with Parasut!'),
                    'type': 'success',
                }
            }
        except Exception as e:
            raise UserError(_("Connection Failed: %s") % str(e))

    def action_parasut_sync_now(self):
        """ Opens the Parasut Connector wizard for manual sync. """
        return {
            'name': _('Parasut Synchronization'),
            'type': 'ir.actions.act_window',
            'res_model': 'parasut.connector',
            'view_mode': 'form',
            'target': 'new',
        }

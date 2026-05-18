from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    mlm_admin_partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='MLM Admin Account',
        help=(
            'This partner receives commission portions for any MLM level '
            'that has no upline partner. '
            'For example, if an order is referred by a Level-1 affiliate who '
            'has no upline, the Level-2, 3, 4 … portions all go here.'
        ),
        config_parameter='mlm_affiliate.admin_partner_id',
    )

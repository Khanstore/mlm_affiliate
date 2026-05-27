from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    mlm_admin_partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='MLM Admin Account',
        help='Receives commission portions for any MLM level that has no upline partner.',
        config_parameter='mlm_affiliate.admin_partner_id',
    )

    # FEATURE: minimum payout threshold
    mlm_min_payout_threshold = fields.Float(
        string='Minimum Payout Amount',
        digits=(16, 2),
        default=0.0,
        help='Commissions below this amount cannot be marked as Paid. '
             'Set to 0 to disable the threshold.',
        config_parameter='mlm_affiliate.min_payout_threshold',
    )

    # FEATURE: enable/disable monthly summary emails
    mlm_send_monthly_summary = fields.Boolean(
        string='Send Monthly Commission Summary Emails',
        default=True,
        config_parameter='mlm_affiliate.send_monthly_summary',
    )

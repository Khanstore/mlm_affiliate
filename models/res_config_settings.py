from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    mlm_admin_partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='MLM Admin Account',
        help='Receives commission portions for any MLM level that has no upline partner.',
        config_parameter='mlm_affiliate.admin_partner_id',
    )
    mlm_min_payout_threshold = fields.Float(
        string='Minimum Payout Amount',
        digits=(16, 2), default=0.0,
        help='Commissions below this amount cannot be marked as Paid. Set to 0 to disable.',
        config_parameter='mlm_affiliate.min_payout_threshold',
    )
    mlm_send_monthly_summary = fields.Boolean(
        string='Send Monthly Commission Summary Emails',
        default=True,
        config_parameter='mlm_affiliate.send_monthly_summary',
    )
    mlm_commission_hold_days = fields.Integer(
        string='Commission Hold Period (Days)',
        default=0,
        help='Newly created commissions are held for this many days before they can be '
             'approved (covers return/refund window). Set to 0 to disable.',
        config_parameter='mlm_affiliate.commission_hold_days',
    )
    # ── Accounting ─────────────────────────────────────────────────────────────
    mlm_expense_account_id = fields.Many2one(
        comodel_name='account.account',
        string='MLM Commission Expense Account',
        help='Debit account for MLM commission journal entries (e.g. Marketing Expenses).',
        config_parameter='mlm_affiliate.expense_account_id',
    )
    mlm_payable_account_id = fields.Many2one(
        comodel_name='account.account',
        string='MLM Commission Payable Account',
        help='Credit account for MLM commission journal entries (Affiliate Commissions Payable).',
        config_parameter='mlm_affiliate.payable_account_id',
    )
    mlm_journal_id = fields.Many2one(
        comodel_name='account.journal',
        string='MLM Commission Journal',
        domain="[('type', '=', 'general')]",
        help='Miscellaneous journal used for MLM commission entries. Defaults to the first '
             'general journal if not set.',
        config_parameter='mlm_affiliate.journal_id',
    )
    # ── Affiliate application ──────────────────────────────────────────────────
    mlm_require_application = fields.Boolean(
        string='Require Affiliate Application Approval',
        default=False,
        help='When enabled, new affiliates start with "Pending Review" status and must be '
             'approved by an admin before earning commissions.',
        config_parameter='mlm_affiliate.require_application',
    )

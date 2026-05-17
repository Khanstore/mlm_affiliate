import random
import string
from odoo import models, fields, api


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # ── Affiliate Identity ──────────────────────────────────────────────────
    referral_code = fields.Char(
        string='Referral Code',
        copy=False,
        index=True,
        help='Unique code used in referral links: /ref/<code>',
    )
    is_affiliate = fields.Boolean(
        string='Is Affiliate / Referrer',
        default=False,
        help='Enable to allow this partner to generate referral links and earn commissions.',
    )
    upline_partner_id = fields.Many2one(
        'res.partner',
        string='Referred By (Upline)',
        index=True,
        help='The partner who referred this person. Defines the MLM upline chain.',
    )
    downline_ids = fields.One2many(
        'res.partner',
        'upline_partner_id',
        string='Direct Downline',
    )
    downline_count = fields.Integer(
        string='Direct Referrals',
        compute='_compute_downline_count',
    )

    # ── Wallet / Earnings ───────────────────────────────────────────────────
    affiliate_wallet_balance = fields.Float(
        string='Wallet Balance',
        compute='_compute_wallet_balance',
        store=True,
        digits=(16, 2),
        help='Approved wallet commissions minus paid-out wallet commissions.',
    )
    commission_ids = fields.One2many(
        'mlm.commission',
        'partner_id',
        string='Commissions',
    )
    total_commission_earned = fields.Float(
        string='Total Earned (All Time)',
        compute='_compute_total_commission_earned',
        digits=(16, 2),
    )

    # ── Referral URL helper (non-stored) ────────────────────────────────────
    referral_url = fields.Char(
        string='Referral Link',
        compute='_compute_referral_url',
    )

    # ───────────────────────────────────────────────────────────────────────
    # Computes
    # ───────────────────────────────────────────────────────────────────────

    @api.depends('commission_ids.state', 'commission_ids.amount', 'commission_ids.payout_method')
    def _compute_wallet_balance(self):
        for partner in self:
            approved = partner.commission_ids.filtered(
                lambda c: c.state == 'approved' and c.payout_method == 'wallet'
            )
            paid = partner.commission_ids.filtered(
                lambda c: c.state == 'paid' and c.payout_method == 'wallet'
            )
            partner.affiliate_wallet_balance = (
                sum(approved.mapped('amount')) - sum(paid.mapped('amount'))
            )

    @api.depends('commission_ids.state', 'commission_ids.amount')
    def _compute_total_commission_earned(self):
        for partner in self:
            earned = partner.commission_ids.filtered(
                lambda c: c.state in ('approved', 'paid')
            )
            partner.total_commission_earned = sum(earned.mapped('amount'))

    @api.depends('downline_ids')
    def _compute_downline_count(self):
        for partner in self:
            partner.downline_count = len(partner.downline_ids)

    @api.depends('referral_code')
    def _compute_referral_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        for partner in self:
            if partner.referral_code:
                partner.referral_url = f"{base_url}/ref/{partner.referral_code}"
            else:
                partner.referral_url = ''

    # ───────────────────────────────────────────────────────────────────────
    # Helpers
    # ───────────────────────────────────────────────────────────────────────

    def _generate_referral_code(self):
        """Generate a unique 8-character alphanumeric referral code."""
        chars = string.ascii_uppercase + string.digits
        while True:
            code = ''.join(random.choices(chars, k=8))
            if not self.sudo().search([('referral_code', '=', code)], limit=1):
                return code

    def action_generate_referral_code(self):
        """Button: generate referral code if not already set."""
        for partner in self:
            if not partner.referral_code:
                partner.referral_code = partner._generate_referral_code()
                partner.is_affiliate = True

    def action_view_mlm_commissions(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Commissions',
            'res_model': 'mlm.commission',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }

    # ───────────────────────────────────────────────────────────────────────
    # ORM overrides
    # ───────────────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        for partner in partners:
            if partner.is_affiliate and not partner.referral_code:
                partner.referral_code = partner._generate_referral_code()
        return partners

    def write(self, vals):
        res = super().write(vals)
        # Auto-generate code when affiliate flag is turned on
        if vals.get('is_affiliate'):
            for partner in self:
                if not partner.referral_code:
                    partner.referral_code = partner._generate_referral_code()
        return res

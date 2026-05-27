import random
import string
from odoo import models, fields, api


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # ── Affiliate identity ────────────────────────────────────────────────────
    referral_code = fields.Char(string='Referral Code', copy=False, index=True)
    is_affiliate = fields.Boolean(string='Is Affiliate / Referrer', default=False)
    upline_partner_id = fields.Many2one('res.partner', string='Referred By (Upline)', index=True)
    downline_ids = fields.One2many('res.partner', 'upline_partner_id', string='Direct Downline')
    downline_count = fields.Integer(string='Direct Referrals', compute='_compute_downline_count')

    # FEATURE: Affiliate tier
    tier_id = fields.Many2one(
        'mlm.affiliate.tier', string='Affiliate Tier',
        help='Auto-assigned based on earnings and referral count.',
    )

    # FEATURE: Bank account for payouts
    affiliate_bank_account = fields.Char(
        string='Bank / Payout Account',
        help='IBAN, account number, or mobile wallet number for bank transfer payouts.',
    )

    # FEATURE: Referral link click tracking
    referral_click_count = fields.Integer(
        string='Link Clicks', default=0,
        help='Number of times the referral link has been visited.',
    )
    referral_last_click = fields.Datetime(string='Last Click')

    # ── Wallet ────────────────────────────────────────────────────────────────
    affiliate_wallet_balance = fields.Float(
        string='Wallet Balance',
        compute='_compute_wallet_balance',
        store=True, digits=(16, 2),
    )
    commission_ids = fields.One2many('mlm.commission', 'partner_id', string='Commissions')
    total_commission_earned = fields.Float(
        string='Total Earned (All Time)',
        compute='_compute_total_commission_earned',
        digits=(16, 2),
    )
    wallet_order_ids = fields.One2many(
        'sale.order', 'wallet_partner_id', string='Wallet Orders',
        domain=[('state', 'in', ['sale', 'done'])],
    )
    referral_url = fields.Char(string='Referral Link', compute='_compute_referral_url')

    # ── Computes ──────────────────────────────────────────────────────────────

    @api.depends(
        'commission_ids.state', 'commission_ids.amount', 'commission_ids.payout_method',
        'wallet_order_ids.wallet_amount_used', 'wallet_order_ids.state',
    )
    def _compute_wallet_balance(self):
        """
        FIX (N+1): fetch all wallet orders for the entire batch in one query,
        group by wallet_partner_id, then look up amounts by partner id.
        """
        Order = self.env['sale.order'].sudo()
        partner_ids = self.ids
        if not partner_ids:
            return

        # One query for the whole recordset
        wallet_orders = Order.search([
            ('wallet_partner_id', 'in', partner_ids),
            ('state', 'in', ['sale', 'done']),
        ])
        # Build a dict: partner_id → total spent
        spent_by_partner = {}
        for wo in wallet_orders:
            pid = wo.wallet_partner_id.id
            spent_by_partner[pid] = spent_by_partner.get(pid, 0.0) + wo.wallet_amount_used

        for partner in self:
            comms = partner.commission_ids
            approved = sum(
                c.amount for c in comms
                if c.state == 'approved' and c.payout_method == 'wallet'
            )
            paid_out = sum(
                c.amount for c in comms
                if c.state == 'paid' and c.payout_method == 'wallet'
            )
            wallet_spent = spent_by_partner.get(partner.id, 0.0)
            partner.affiliate_wallet_balance = approved - paid_out - wallet_spent

    @api.depends('commission_ids.state', 'commission_ids.amount')
    def _compute_total_commission_earned(self):
        for partner in self:
            partner.total_commission_earned = sum(
                c.amount for c in partner.commission_ids
                if c.state in ('approved', 'paid')
            )

    @api.depends('downline_ids')
    def _compute_downline_count(self):
        for partner in self:
            partner.downline_count = len(partner.downline_ids)

    @api.depends('referral_code')
    def _compute_referral_url(self):
        base_url = (
            self.env['ir.config_parameter'].sudo()
            .get_param('web.base.url', '').rstrip('/')
        )
        for partner in self:
            if partner.referral_code:
                partner.referral_url = f"{base_url}/ref/{partner.referral_code}"
            else:
                partner.referral_url = ''

    # ── Tier auto-assignment ──────────────────────────────────────────────────

    def action_update_tier(self):
        """Assign the highest tier the partner qualifies for."""
        tiers = self.env['mlm.affiliate.tier'].sudo().search(
            [('active', '=', True)], order='min_earned desc'
        )
        for partner in self:
            if not partner.is_affiliate:
                continue
            earned = partner.total_commission_earned
            referrals = partner.downline_count
            assigned = False
            for tier in tiers:
                if earned >= tier.min_earned and referrals >= tier.min_referrals:
                    partner.tier_id = tier
                    assigned = True
                    break
            if not assigned:
                partner.tier_id = False

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _generate_referral_code(self):
        chars = string.ascii_uppercase + string.digits
        while True:
            code = ''.join(random.choices(chars, k=8))
            if not self.sudo().search([('referral_code', '=', code)], limit=1):
                return code

    def action_generate_referral_code(self):
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

    # ── ORM overrides ─────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        for partner in partners:
            if partner.is_affiliate and not partner.referral_code:
                partner.referral_code = partner._generate_referral_code()
        return partners

    def write(self, vals):
        res = super().write(vals)
        if vals.get('is_affiliate'):
            for partner in self:
                if not partner.referral_code:
                    partner.referral_code = partner._generate_referral_code()
        return res

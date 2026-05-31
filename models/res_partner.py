import random
import string
from odoo import models, fields, api


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # ── Ensure custom columns exist before ORM queries them ───────────────────

    def _auto_init(self):
        """
        Create every custom column this module adds to res_partner before the
        ORM touches the table.  Runs on every server start / module load.
        Idempotent — skips columns that already exist.
        """
        res = super()._auto_init()
        self._mlm_ensure_partner_columns()
        return res

    @api.model
    def _mlm_ensure_partner_columns(self):
        columns = [
            # (name,                      DDL type,                   default)
            ('referral_code',             'VARCHAR(20)',               None),
            ('is_affiliate',              'BOOLEAN',                   'FALSE'),
            ('upline_partner_id',         'INTEGER',                   None),
            ('tier_id',                   'INTEGER',                   None),
            ('affiliate_bank_account',    'TEXT',                      None),
            ('referral_click_count',      'INTEGER',                   '0'),
            ('referral_last_click',       'TIMESTAMP WITH TIME ZONE',  None),
            ('affiliate_status',          'VARCHAR(20)',                "'approved'"),
        ]
        cr = self.env.cr
        for col, col_type, default in columns:
            cr.execute("""
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'res_partner' AND column_name = %s
            """, (col,))
            if not cr.fetchone():
                ddl = (
                    f'ALTER TABLE res_partner ADD COLUMN "{col}" {col_type}'
                    + (f' NOT NULL DEFAULT {default}' if default else '')
                )
                cr.execute(ddl)

    # ── Affiliate identity ────────────────────────────────────────────────────
    referral_code = fields.Char(string='Referral Code', copy=False, index=True)
    is_affiliate = fields.Boolean(string='Is Affiliate / Referrer', default=False)
    upline_partner_id = fields.Many2one('res.partner', string='Referred By (Upline)', index=True)
    downline_ids = fields.One2many('res.partner', 'upline_partner_id', string='Direct Downline')
    downline_count = fields.Integer(string='Direct Referrals', compute='_compute_downline_count')

    tier_id = fields.Many2one('mlm.affiliate.tier', string='Affiliate Tier',
        help='Auto-assigned based on earnings and referral count.')
    affiliate_bank_account = fields.Char(string='Bank / Payout Account',
        help='IBAN, account number, or mobile wallet number for bank transfer payouts.')

    # Referral link click tracking
    referral_click_count = fields.Integer(string='Link Clicks', default=0)
    referral_last_click = fields.Datetime(string='Last Click')

    # ── Wallet ────────────────────────────────────────────────────────────────
    affiliate_wallet_balance = fields.Float(
        string='Wallet Balance',
        compute='_compute_wallet_balance',
        store=True, digits=(16, 2))
    commission_ids = fields.One2many('mlm.commission', 'partner_id', string='Commissions')
    total_commission_earned = fields.Float(
        string='Total Earned (All Time)',
        compute='_compute_total_commission_earned',
        store=True,
        digits=(16, 2))
    wallet_order_ids = fields.One2many(
        'sale.order', 'wallet_partner_id', string='Wallet Orders',
        domain=[('state', 'in', ['draft', 'sent', 'sale', 'done']),
                ('wallet_amount_used', '>', 0)])
    referral_url = fields.Char(string='Referral Link', compute='_compute_referral_url')

    # Affiliate application status
    affiliate_status = fields.Selection(
        [('pending', 'Pending Review'), ('approved', 'Approved'), ('rejected', 'Rejected')],
        string='Application Status', default='approved', index=True,
        help='Controls whether the affiliate can share links and earn commissions.')

    # ── Computes ──────────────────────────────────────────────────────────────

    @api.depends(
        'commission_ids.state', 'commission_ids.amount', 'commission_ids.payout_method',
        'wallet_order_ids.wallet_amount_used', 'wallet_order_ids.state',
    )
    def _compute_wallet_balance(self):
        Order = self.env['sale.order'].sudo()
        partner_ids = self.ids
        if not partner_ids:
            return
        # Include draft/sent orders so balance reflects pending wallet usage
        wallet_orders = Order.search([
            ('wallet_partner_id', 'in', partner_ids),
            ('state', 'in', ['draft', 'sent', 'sale', 'done']),
            ('wallet_amount_used', '>', 0),
        ])
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
            # Check milestone bonuses
            partner._check_milestones()

    def _check_milestones(self):
        """Award one-time milestone bonuses the partner has not yet received."""
        self.ensure_one()
        if not self.is_affiliate:
            return

        Milestone = self.env['mlm.milestone'].sudo()
        AwardModel = self.env['mlm.partner.milestone'].sudo()
        Commission = self.env['mlm.commission'].sudo()

        milestones = Milestone.search([
            ('active', '=', True),
            ('bonus_amount', '>', 0),
        ])
        already_awarded = AwardModel.search([
            ('partner_id', '=', self.id)
        ]).mapped('milestone_id').ids

        earned = self.total_commission_earned
        referrals = self.downline_count

        for ms in milestones:
            if ms.id in already_awarded:
                continue
            if earned >= ms.min_earned and referrals >= ms.min_referrals:
                # Create a bonus commission (no order_id required)
                bonus = Commission.create({
                    'partner_id': self.id,
                    'level': 0,
                    'amount': ms.bonus_amount,
                    'is_milestone_bonus': True,
                    'note': f'Milestone bonus: {ms.name}',
                    'state': 'approved',
                    'payout_method': 'wallet',
                })
                # Immediately create the accounting entry for this bonus
                try:
                    bonus._create_accounting_entry()
                except Exception:
                    pass
                AwardModel.create({
                    'partner_id': self.id,
                    'milestone_id': ms.id,
                    'awarded_date': fields.Date.today(),
                    'commission_id': bonus.id,
                })

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

    def action_approve_affiliate(self):
        for partner in self:
            partner.affiliate_status = 'approved'

    def action_reject_affiliate(self):
        for partner in self:
            partner.affiliate_status = 'rejected'

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

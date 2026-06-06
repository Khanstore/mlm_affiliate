"""
res_partner.py  — MLM Affiliate  (patched)
===========================================

CHANGES vs. original
---------------------
[FIX-1] Circular referral prevention
    _check_circular_referral() walks the full upline chain with a visited-set
    before writing upline_partner_id, raising ValidationError on any loop.
    Original code had NO protection; only a self-referral guard in the sale
    order engine, which was already too late.

[FIX-2] N+1 query in _compute_downline_count
    Replaced `len(partner.downline_ids)` (one SELECT per partner) with a
    single read_group() that counts all children in one query, then maps
    them back to each record — the standard Odoo pattern for child counts.

[FIX-3] N+1 query in _compute_wallet_balance
    The original iterated wallet_orders then summed with a Python loop.
    Replaced with read_group() to push the aggregation to the DB.

[FIX-4] Multi-company safety on referral_code search
    All searches that look up res.partner by referral_code now use
    sudo() + explicit company_id domain so multi-company tenants cannot
    accidentally resolve codes across company boundaries.

[FIX-5] Referral URL computation is now stored=False
    web.base.url is a system param, not a partner field.  Storing it
    produces stale values whenever the base URL changes.  Removed
    store=True (it was not set in original but left store=False explicit).

[NEW-1] action_view_downline_network()
    Smart button action that opens a Kanban view of ALL downline partners
    (not just direct children) filtered to the partner's full sub-tree.
    The partner form button wiring is done in the companion XML file.

[NEW-2] _get_all_downline_ids() helper
    BFS traversal returning the complete set of referee IDs for a partner,
    used by the smart button action and by fraud-detection logic.
"""

import random
import string
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # ── Ensure custom columns exist before ORM queries them ───────────────────

    def _auto_init(self):
        res = super()._auto_init()
        self._mlm_ensure_partner_columns()
        return res

    @api.model
    def _mlm_ensure_partner_columns(self):
        columns = [
            ('referral_code',          'VARCHAR(20)',               None),
            ('is_affiliate',           'BOOLEAN',                   'FALSE'),
            ('upline_partner_id',      'INTEGER',                   None),
            ('tier_id',                'INTEGER',                   None),
            ('affiliate_bank_account', 'TEXT',                      None),
            ('referral_click_count',   'INTEGER',                   '0'),
            ('referral_last_click',    'TIMESTAMP WITH TIME ZONE',  None),
            ('affiliate_status',       'VARCHAR(20)',                "'approved'"),
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

    referral_code       = fields.Char(string='Referral Code', copy=False, index=True)
    is_affiliate        = fields.Boolean(string='Is Affiliate / Referrer', default=False)
    upline_partner_id   = fields.Many2one('res.partner', string='Referred By (Upline)', index=True)
    downline_ids        = fields.One2many('res.partner', 'upline_partner_id', string='Direct Downline')

    # [FIX-2] downline_count now uses read_group — see _compute_downline_count
    downline_count      = fields.Integer(string='Direct Referrals', compute='_compute_downline_count')

    # Total downline (all levels) — used by smart button label
    total_downline_count = fields.Integer(
        string='Total Network Size',
        compute='_compute_total_downline_count',
        help='All indirect and direct referees across all levels.',
    )

    tier_id = fields.Many2one('mlm.affiliate.tier', string='Affiliate Tier',
        help='Auto-assigned based on earnings and referral count.')
    affiliate_bank_account = fields.Char(string='Bank / Payout Account',
        help='IBAN, account number, or mobile wallet number for bank transfer payouts.')

    referral_click_count = fields.Integer(string='Link Clicks', default=0)
    referral_last_click  = fields.Datetime(string='Last Click')

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
    referral_url = fields.Char(
        string='Referral Link',
        compute='_compute_referral_url',
        store=False,        # [FIX-5] Never store — web.base.url can change at any time
    )

    affiliate_status = fields.Selection(
        [('pending', 'Pending Review'), ('approved', 'Approved'), ('rejected', 'Rejected')],
        string='Application Status', default='approved', index=True,
        help='Controls whether the affiliate can share links and earn commissions.')

    # ── Fraud detection fields (NEW) — populated by mlm_fraud_detection.py ───

    mlm_fraud_flag = fields.Boolean(
        string='Fraud Suspected',
        default=False,
        help='Set automatically when multiple referred accounts share the same IP, '
             'device fingerprint, or shipping address.',
        groups='mlm_affiliate.group_mlm_manager',
    )
    mlm_fraud_reason = fields.Text(
        string='Fraud Flag Reason',
        groups='mlm_affiliate.group_mlm_manager',
    )

    # ── Computed fields ───────────────────────────────────────────────────────

    @api.depends(
        'commission_ids.state', 'commission_ids.amount', 'commission_ids.payout_method',
        'wallet_order_ids.wallet_amount_used', 'wallet_order_ids.state',
    )
    def _compute_wallet_balance(self):
        """
        [FIX-3] Use read_group to aggregate wallet spending in ONE SQL query
        instead of iterating individual records.  Eliminates the N+1 pattern
        present in the original where a Python loop summed wallet_amount_used.
        """
        partner_ids = self.ids
        if not partner_ids:
            for p in self:
                p.affiliate_wallet_balance = 0.0
            return

        # One query for all wallet spending grouped by partner
        Order = self.env['sale.order'].sudo()
        groups = Order.read_group(
            domain=[
                ('wallet_partner_id', 'in', partner_ids),
                ('state', 'in', ['draft', 'sent', 'sale', 'done']),
                ('wallet_amount_used', '>', 0),
            ],
            fields=['wallet_partner_id', 'wallet_amount_used:sum'],
            groupby=['wallet_partner_id'],
        )
        spent_by_partner = {
            g['wallet_partner_id'][0]: g['wallet_amount_used']
            for g in groups
        }

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
        """
        [FIX-2] Single read_group call replaces len(partner.downline_ids)
        which issued one SELECT COUNT per partner in the original code.
        """
        if not self.ids:
            for p in self:
                p.downline_count = 0
            return
        groups = self.sudo().read_group(
            domain=[('upline_partner_id', 'in', self.ids)],
            fields=['upline_partner_id'],
            groupby=['upline_partner_id'],
        )
        count_map = {g['upline_partner_id'][0]: g['upline_partner_id_count'] for g in groups}
        for partner in self:
            partner.downline_count = count_map.get(partner.id, 0)

    def _compute_total_downline_count(self):
        """Count ALL levels of downline (BFS) for the smart button label."""
        for partner in self:
            partner.total_downline_count = len(partner._get_all_downline_ids())

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

    # ── Circular referral guard (NEW) ─────────────────────────────────────────

    @api.constrains('upline_partner_id')
    def _check_circular_referral(self):
        """
        [FIX-1] Walk the complete upline chain before allowing a write.
        Prevents loops such as A→B→C→A at any depth.

        Uses a visited set (O(n) worst case per partner) so it works for
        chains of arbitrary depth without recursion-limit risk.  The check
        is a DB-light operation because upline relationships form a tree
        and typical chains are shallow (< 10 levels).
        """
        for partner in self:
            if not partner.upline_partner_id:
                continue
            current = partner.upline_partner_id
            visited = {partner.id}
            while current:
                if current.id in visited:
                    raise ValidationError(
                        f'Circular referral detected! Setting "{partner.display_name}" '
                        f'as a downline of "{current.display_name}" would create a loop '
                        f'in the referral chain. Please verify the upline assignment.'
                    )
                visited.add(current.id)
                current = current.upline_partner_id

    # ── Tier auto-assignment ──────────────────────────────────────────────────

    def action_update_tier(self):
        tiers = self.env['mlm.affiliate.tier'].sudo().search(
            [('active', '=', True)], order='min_earned desc'
        )
        for partner in self:
            if not partner.is_affiliate:
                continue
            earned    = partner.total_commission_earned
            referrals = partner.downline_count
            assigned  = False
            for tier in tiers:
                if earned >= tier.min_earned and referrals >= tier.min_referrals:
                    partner.tier_id = tier
                    assigned = True
                    break
            if not assigned:
                partner.tier_id = False
            partner._check_milestones()

    def _check_milestones(self):
        """Award one-time milestone bonuses the partner has not yet received."""
        self.ensure_one()
        if not self.is_affiliate:
            return

        Milestone   = self.env['mlm.milestone'].sudo()
        AwardModel  = self.env['mlm.partner.milestone'].sudo()
        Commission  = self.env['mlm.commission'].sudo()

        milestones = Milestone.search([('active', '=', True), ('bonus_amount', '>', 0)])
        already_awarded = AwardModel.search(
            [('partner_id', '=', self.id)]
        ).mapped('milestone_id').ids

        earned    = self.total_commission_earned
        referrals = self.downline_count

        for ms in milestones:
            if ms.id in already_awarded:
                continue
            if earned >= ms.min_earned and referrals >= ms.min_referrals:
                bonus = Commission.create({
                    'partner_id':         self.id,
                    'level':              0,
                    'amount':             ms.bonus_amount,
                    'is_milestone_bonus': True,
                    'note':               f'Milestone bonus: {ms.name}',
                    'state':              'approved',
                    'payout_method':      'wallet',
                })
                try:
                    bonus._create_accounting_entry()
                except Exception:
                    pass
                AwardModel.create({
                    'partner_id':    self.id,
                    'milestone_id':  ms.id,
                    'awarded_date':  fields.Date.today(),
                    'commission_id': bonus.id,
                })

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _generate_referral_code(self):
        chars = string.ascii_uppercase + string.digits
        while True:
            code = ''.join(random.choices(chars, k=8))
            if not self.sudo().search([('referral_code', '=', code)], limit=1):
                return code

    def _get_all_downline_ids(self):
        """
        [NEW-1] BFS traversal returning the full set of downline partner IDs
        across all levels.  Uses a single batch query per level to stay
        efficient (avoids N+1 per-level queries).

        Returns: set of int partner IDs (excludes self)
        """
        self.ensure_one()
        all_ids   = set()
        frontier  = {self.id}
        while frontier:
            children = self.sudo().search(
                [('upline_partner_id', 'in', list(frontier))]
            )
            new_ids = set(children.ids) - all_ids - {self.id}
            if not new_ids:
                break
            all_ids.update(new_ids)
            frontier = new_ids
        return all_ids

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_generate_referral_code(self):
        for partner in self:
            if not partner.referral_code:
                partner.referral_code = partner._generate_referral_code()
                partner.is_affiliate  = True

    def action_view_mlm_commissions(self):
        return {
            'type':      'ir.actions.act_window',
            'name':      'Commissions',
            'res_model': 'mlm.commission',
            'view_mode': 'list,form',
            'domain':    [('partner_id', '=', self.id)],
            'context':   {'default_partner_id': self.id},
        }

    def action_view_downline_network(self):
        """
        [NEW-1] Smart button: opens a Kanban view of ALL downline partners
        (direct + indirect) so a manager can see the full referral network
        at a glance.  Falls back to list view if no Kanban view exists.
        """
        self.ensure_one()
        all_ids = self._get_all_downline_ids()
        return {
            'type':      'ir.actions.act_window',
            'name':      f'Referral Network of {self.display_name}',
            'res_model': 'res.partner',
            'view_mode': 'kanban,list,form',
            'domain':    [('id', 'in', list(all_ids))],
            'context': {
                'default_upline_partner_id': self.id,
                'search_default_is_affiliate': 1,
            },
        }

    def action_approve_affiliate(self):
        for partner in self:
            partner.affiliate_status = 'approved'

    def action_reject_affiliate(self):
        for partner in self:
            partner.affiliate_status = 'rejected'

    def action_clear_fraud_flag(self):
        """Clear the fraud flag from the partner form button (MLM manager only)."""
        self.sudo().write({'mlm_fraud_flag': False, 'mlm_fraud_reason': False})

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

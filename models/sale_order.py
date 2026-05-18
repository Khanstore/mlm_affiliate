from odoo import models, fields, api


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    referrer_partner_id = fields.Many2one(
        'res.partner', string='Referred By',
        index=True, tracking=True,
        help='Affiliate whose referral link was used for this order.',
    )
    referral_code_used = fields.Char(string='Referral Code Used', copy=False)
    commission_ids = fields.One2many('mlm.commission', 'order_id', string='Commissions')
    commission_count = fields.Integer(compute='_compute_commission_stats')
    total_commission_amount = fields.Float(
        compute='_compute_commission_stats',
        string='Total Commissions', digits=(16, 2),
    )

    @api.depends('commission_ids', 'commission_ids.amount')
    def _compute_commission_stats(self):
        for order in self:
            order.commission_count = len(order.commission_ids)
            order.total_commission_amount = sum(order.commission_ids.mapped('amount'))

    # ── Referrer capture via cookie ───────────────────────────────────────────

    def _cart_update(self, product_id=None, line_id=None,
                     add_qty=0, set_qty=0, **kwargs):
        result = super()._cart_update(
            product_id=product_id, line_id=line_id,
            add_qty=add_qty, set_qty=set_qty, **kwargs,
        )
        if not self.referrer_partner_id:
            self._attach_referrer_from_cookie()
        return result

    def _attach_referrer_from_cookie(self):
        try:
            from odoo.http import request as http_request
            ref_code = http_request.httprequest.cookies.get('mlm_ref', '').strip()
        except Exception:
            return
        if not ref_code:
            return
        partner = self.env['res.partner'].sudo().search(
            [('referral_code', '=', ref_code)], limit=1
        )
        if not partner or partner == self.partner_id:
            return
        self.sudo().write({
            'referrer_partner_id': partner.id,
            'referral_code_used': ref_code,
        })

    # ── Commission engine ─────────────────────────────────────────────────────

    def action_confirm(self):
        res = super().action_confirm()
        for order in self:
            if order.referrer_partner_id and not order.commission_ids:
                order._generate_mlm_commissions()
        return res

    def _generate_mlm_commissions(self):
        """
        Commission distribution logic:

        NORMAL case  (buyer has no existing upline,
                      OR buyer's upline IS the referrer):
        ─────────────────────────────────────────────
        Upline chain:  referrer → referrer's upline → …
        L1 → referrer (100% of L1 amount)
        L2 → referrer's upline
        L3 → …

        SPLIT case  (buyer already has an existing upline
                     AND that upline is DIFFERENT from the referrer):
        ─────────────────────────────────────────────────────────────
        Example: Aslam's upline is Karim.  Nurul shares a link.
                 Aslam clicks Nurul's link and buys.

        L1 → split 50 / 50:
                 ├── Nurul (the referrer)          gets  L1_amount × 50%
                 └── Karim (buyer's existing upline) gets  L1_amount × 50%

        L2 → Karim's upline  (chain continues UP from buyer's existing upline)
        L3 → Karim's upline's upline
        …

        Empty levels (no partner in chain) → Admin Account.
        """
        self.ensure_one()
        if not self.referrer_partner_id:
            return

        LevelRate   = self.env['mlm.level.rate'].sudo()
        Commission  = self.env['mlm.commission'].sudo()
        RuleModel   = self.env['product.commission.rule'].sudo()

        level_rates = LevelRate.search([('active', '=', True)], order='level')
        if not level_rates:
            return

        # ── Admin fallback partner ────────────────────────────────────────────
        admin_pid = int(
            self.env['ir.config_parameter'].sudo()
            .get_param('mlm_affiliate.admin_partner_id', 0)
        )
        admin_partner = (
            self.env['res.partner'].sudo().browse(admin_pid)
            if admin_pid else self.env['res.partner']
        )

        referrer     = self.referrer_partner_id
        buyer        = self.partner_id
        buyer_upline = buyer.upline_partner_id if buyer else False

        # ── Determine split mode ──────────────────────────────────────────────
        # Split when buyer has an upline AND it's not the same as the referrer
        do_l1_split = bool(
            buyer_upline
            and buyer_upline.id != referrer.id
        )

        # ── Build upline chain for L2+ ────────────────────────────────────────
        # In split mode: chain starts from buyer's upline (Karim)
        #                because Karim already shares L1; his upline gets L2.
        # In normal mode: chain starts from referrer.
        if do_l1_split:
            chain_start = buyer_upline        # Karim
        else:
            chain_start = referrer            # Nurul

        max_level = max(lr.level for lr in level_rates)
        upline_chain = []                     # index 0 = L1 recipient in normal mode
        current = chain_start
        visited = set()
        while current and len(upline_chain) < max_level:
            if current.id in visited:
                break
            visited.add(current.id)
            upline_chain.append(current)
            current = current.upline_partner_id

        # ── Per order line ────────────────────────────────────────────────────
        for line in self.order_line:
            if not line.product_id or line.price_subtotal <= 0:
                continue

            rule = RuleModel.search([
                ('product_tmpl_id', '=', line.product_id.product_tmpl_id.id),
                ('active', '=', True),
            ], limit=1)
            if not rule:
                continue

            total_pot = rule.compute_total_commission(line.price_subtotal)
            if total_pot <= 0:
                continue

            # ── Distribute across levels ──────────────────────────────────────
            for lr in level_rates:
                level_amount = round(total_pot * lr.rate / 100, 2)
                if level_amount <= 0:
                    continue

                if lr.level == 1 and do_l1_split:
                    # ── SPLIT L1 equally between referrer and buyer's upline ──
                    half = round(level_amount / 2, 2)

                    # Half to referrer (Nurul)
                    Commission.create({
                        'partner_id':        referrer.id,
                        'order_id':          self.id,
                        'order_line_id':     line.id,
                        'product_id':        line.product_id.id,
                        'buyer_partner_id':  buyer.id,
                        'level':             1,
                        'level_rate':        lr.rate,
                        'total_commission':  total_pot,
                        'amount':            half,
                        'is_l1_split':       True,
                        'split_partner_id':  buyer_upline.id,
                        'state':             'pending',
                        'payout_method':     'wallet',
                    })

                    # Half to buyer's existing upline (Karim)
                    Commission.create({
                        'partner_id':        buyer_upline.id,
                        'order_id':          self.id,
                        'order_line_id':     line.id,
                        'product_id':        line.product_id.id,
                        'buyer_partner_id':  buyer.id,
                        'level':             1,
                        'level_rate':        lr.rate,
                        'total_commission':  total_pot,
                        'amount':            half,
                        'is_l1_split':       True,
                        'split_partner_id':  referrer.id,
                        'state':             'pending',
                        'payout_method':     'wallet',
                    })

                else:
                    # ── Normal level (L1 no-split, or L2, L3, L4 …) ──────────
                    # In split mode:  L2 → chain index 1 (Karim's upline),
                    #                 L3 → chain index 2, etc.
                    #                 (chain[0] = Karim already got L1-split)
                    # In normal mode: L1 → chain index 0 (referrer),
                    #                 L2 → chain index 1, etc.
                    if do_l1_split:
                        chain_idx = lr.level - 1   # L2→1, L3→2, L4→3
                    else:
                        chain_idx = lr.level - 1   # L1→0, L2→1, L3→2

                    if chain_idx < len(upline_chain):
                        recipient   = upline_chain[chain_idx]
                        is_admin    = False
                    else:
                        if not admin_partner.exists():
                            continue
                        recipient   = admin_partner
                        is_admin    = True

                    Commission.create({
                        'partner_id':          recipient.id,
                        'order_id':            self.id,
                        'order_line_id':       line.id,
                        'product_id':          line.product_id.id,
                        'buyer_partner_id':    buyer.id,
                        'level':               lr.level,
                        'level_rate':          lr.rate,
                        'total_commission':    total_pot,
                        'amount':              level_amount,
                        'is_admin_allocation': is_admin,
                        'state':               'pending',
                        'payout_method':       'wallet',
                    })

    # ── Smart button ──────────────────────────────────────────────────────────

    def action_view_mlm_commissions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Commissions — {self.name}',
            'res_model': 'mlm.commission',
            'view_mode': 'list,form',
            'domain': [('order_id', '=', self.id)],
            'context': {'default_order_id': self.id},
        }


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    commission_ids = fields.One2many(
        'mlm.commission', 'order_line_id', string='Commissions',
    )

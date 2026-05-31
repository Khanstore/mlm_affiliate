from odoo import models, fields, api


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    referrer_partner_id = fields.Many2one('res.partner', string='Referred By',
        index=True, tracking=True)
    referral_code_used = fields.Char(string='Referral Code Used', copy=False)
    commission_ids = fields.One2many('mlm.commission', 'order_id', string='Commissions')
    commission_count = fields.Integer(compute='_compute_commission_stats')
    total_commission_amount = fields.Float(compute='_compute_commission_stats',
        string='Total Commissions', digits=(16, 2))

    wallet_amount_used = fields.Float(string='Wallet Amount Used', default=0.0, digits=(16, 2))
    wallet_partner_id = fields.Many2one('res.partner', string='Wallet Owner', index=True)

    @api.depends('commission_ids', 'commission_ids.amount')
    def _compute_commission_stats(self):
        for order in self:
            order.commission_count = len(order.commission_ids)
            order.total_commission_amount = sum(order.commission_ids.mapped('amount'))

    # ── Referrer capture ──────────────────────────────────────────────────────

    def _cart_update(self, product_id=None, line_id=None,
                     add_qty=0, set_qty=0, **kwargs):
        result = super()._cart_update(
            product_id=product_id, line_id=line_id,
            add_qty=add_qty, set_qty=set_qty, **kwargs,
        )
        if not self.referrer_partner_id:
            self._attach_referrer_from_cookie()
        # Re-protect the wallet discount line after any cart update,
        # because Odoo ORM recomputes price_unit from list_price on all lines.
        if self.wallet_amount_used > 0:
            self._mlm_reapply_wallet_line_sql()
        return result

    def _mlm_reapply_wallet_line_sql(self):
        """Fix wallet discount line price_unit via SQL after ORM resets it."""
        try:
            prod_tmpl = self.env.ref(
                "mlm_affiliate.product_wallet_discount", raise_if_not_found=False)
            if not prod_tmpl:
                return
            product = prod_tmpl.sudo().product_variant_id
            if not product:
                return
            wallet_lines = self.order_line.filtered(
                lambda l: l.product_id.id == product.id)
            if not wallet_lines:
                return
            neg = -abs(self.wallet_amount_used)
            cr = self.env.cr
            for line in wallet_lines:
                if abs(line.price_unit - neg) > 0.001:  # needs correction
                    cr.execute(
                        """UPDATE sale_order_line
                           SET price_unit = %s, discount = 0.0,
                               price_subtotal = %s, price_total = %s
                           WHERE id = %s""",
                        (neg, neg, neg, line.id)
                    )
                    cr.execute(
                        "DELETE FROM account_tax_sale_order_line_rel WHERE sale_order_line_id = %s",
                        (line.id,)
                    )
            self.sudo().invalidate_recordset(
                ["order_line", "amount_untaxed", "amount_tax", "amount_total"])
        except Exception:
            _logger.exception('MLM: _mlm_reapply_wallet_line_sql failed')

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
        # Only approved affiliates generate commissions
        if partner.affiliate_status != 'approved':
            return
        self.sudo().write({
            'referrer_partner_id': partner.id,
            'referral_code_used': ref_code,
        })

    # ── Commission engine ─────────────────────────────────────────────────────

    def action_confirm(self):
        # Protect wallet lines BEFORE confirm — Odoo recomputes all lines during confirm
        for order in self:
            if order.wallet_amount_used > 0:
                order._mlm_reapply_wallet_line_sql()

        res = super().action_confirm()

        # Re-protect wallet lines AFTER confirm — super() may have reset price_unit again
        for order in self:
            if order.wallet_amount_used > 0:
                order._mlm_reapply_wallet_line_sql()

            if order.commission_ids:
                continue  # already generated
            # Primary: referrer set from referral link cookie
            if not order.referrer_partner_id:
                # Fallback: buyer has an upline (direct referral relationship)
                buyer_upline = order.partner_id.upline_partner_id
                if buyer_upline and buyer_upline.id != order.partner_id.id:
                    if buyer_upline.affiliate_status == "approved":
                        order.sudo().write({
                            "referrer_partner_id": buyer_upline.id,
                            "referral_code_used": buyer_upline.referral_code or "",
                        })
            if order.referrer_partner_id:
                order._generate_mlm_commissions()
        return res

    def action_cancel(self):
        res = super().action_cancel()
        for order in self:
            cancellable = order.commission_ids.filtered(
                lambda c: c.state in ('pending', 'approved')
            )
            if cancellable:
                cancellable.action_cancel()
            # Release wallet credit so balance is restored
            if order.wallet_amount_used > 0:
                # Remove the wallet discount order line
                wallet_tmpl = order.env.ref(
                    'mlm_affiliate.product_wallet_discount', raise_if_not_found=False)
                if wallet_tmpl:
                    wallet_pid = wallet_tmpl.sudo().product_variant_id.id
                    wallet_lines = order.order_line.filtered(
                        lambda l: l.product_id.id == wallet_pid)
                    wallet_lines.sudo().unlink()
                order.sudo().write({
                    'wallet_amount_used': 0.0,
                    'wallet_partner_id': False,
                })
        return res

    def _generate_mlm_commissions(self):
        self.ensure_one()
        if not self.referrer_partner_id:
            return

        LevelRate  = self.env['mlm.level.rate'].sudo()
        Commission = self.env['mlm.commission'].sudo()
        RuleModel  = self.env['product.commission.rule'].sudo()
        CampaignModel = self.env['mlm.campaign'].sudo()

        level_rates = LevelRate.search([('active', '=', True)], order='level')
        if not level_rates:
            return

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
        do_l1_split  = bool(buyer_upline and buyer_upline.id != referrer.id)

        chain_start  = buyer_upline if do_l1_split else referrer
        max_level    = max(lr.level for lr in level_rates)
        upline_chain = []
        current = chain_start
        visited = set()
        while current and len(upline_chain) < max_level:
            if current.id in visited:
                break
            visited.add(current.id)
            upline_chain.append(current)
            current = current.upline_partner_id

        # Self-referral check: referrer must not be the buyer
        if referrer.id == buyer.id:
            return

        # Get wallet product id to skip it in commission calculation
        wallet_tmpl = self.env.ref(
            'mlm_affiliate.product_wallet_discount', raise_if_not_found=False)
        wallet_pid = wallet_tmpl.sudo().product_variant_id.id if wallet_tmpl else None

        for line in self.order_line:
            if not line.product_id or line.price_subtotal <= 0:
                continue
            # Never generate commission on the wallet discount line itself
            if wallet_pid and line.product_id.id == wallet_pid:
                continue
            rule = RuleModel.find_rule_for_product(line.product_id, self.pricelist_id)
            if not rule:
                continue
            total_pot = rule.compute_total_commission(line.price_subtotal, line.product_uom_qty)
            if total_pot <= 0:
                continue

            for lr in level_rates:
                level_amount = round(total_pot * lr.rate / 100, 2)
                if level_amount <= 0:
                    continue

                if lr.level == 1 and do_l1_split:
                    half = round(level_amount / 2, 2)
                    split_rate = round(lr.rate / 2, 4)  # each party gets half the rate
                    for recipient, split_with in [
                        (referrer, buyer_upline),
                        (buyer_upline, referrer),
                    ]:
                        # Apply campaign + tier multiplier per recipient
                        campaign = CampaignModel.get_active_campaign(recipient.id)
                        multiplier = campaign.commission_multiplier if campaign else 1.0
                        tier_mult = recipient.tier_id.commission_multiplier if recipient.tier_id else 1.0
                        multiplier = round(multiplier * tier_mult, 6)
                        final_amount = round(half * multiplier, 2)
                        Commission.create({
                            'partner_id': recipient.id,
                            'split_partner_id': split_with.id,
                            'order_id': self.id,
                            'order_line_id': line.id,
                            'product_id': line.product_id.id,
                            'buyer_partner_id': buyer.id,
                            'level': 1,
                            'level_rate': split_rate,  # show actual split rate (e.g. 35 not 70)
                            'total_commission': total_pot,
                            'amount': final_amount,
                            'campaign_multiplier': multiplier,
                            'is_l1_split': True,
                            'state': 'pending',
                            'payout_method': 'wallet',
                        })
                else:
                    chain_idx = lr.level - 1
                    if chain_idx < len(upline_chain):
                        recipient = upline_chain[chain_idx]
                        is_admin  = False
                    else:
                        if not admin_partner.exists():
                            continue
                        recipient = admin_partner
                        is_admin  = True
                    # Apply campaign multiplier
                    campaign = CampaignModel.get_active_campaign(recipient.id)
                    multiplier = campaign.commission_multiplier if campaign else 1.0
                    # Also apply tier multiplier (stacks with campaign)
                    tier_mult = recipient.tier_id.commission_multiplier if recipient.tier_id else 1.0
                    multiplier = round(multiplier * tier_mult, 6)
                    final_amount = round(level_amount * multiplier, 2)
                    Commission.create({
                        'partner_id': recipient.id,
                        'order_id': self.id,
                        'order_line_id': line.id,
                        'product_id': line.product_id.id,
                        'buyer_partner_id': buyer.id,
                        'level': lr.level,
                        'level_rate': lr.rate,
                        'total_commission': total_pot,
                        'amount': final_amount,
                        'campaign_multiplier': multiplier,
                        'is_admin_allocation': is_admin,
                        'state': 'pending',
                        'payout_method': 'wallet',
                    })

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
    commission_ids = fields.One2many('mlm.commission', 'order_line_id', string='Commissions')

    def _wallet_variant_id(self):
        """Return the wallet discount product variant id, safe for all contexts."""
        try:
            tmpl = self.sudo().env.ref(
                'mlm_affiliate.product_wallet_discount', raise_if_not_found=False)
            return tmpl.sudo().product_variant_id.id if tmpl else None
        except Exception:
            return None

    def _get_display_price(self):
        """Prevent Odoo from resetting the wallet discount line price to list_price."""
        wid = self._wallet_variant_id()
        if wid and self.product_id.id == wid:
            return self.price_unit
        return super()._get_display_price()

    def _compute_price_unit(self):
        """Skip wallet discount lines — their price_unit is managed by SQL."""
        wid = self._wallet_variant_id()
        if not wid:
            return super()._compute_price_unit()
        wallet_lines = self.filtered(lambda l: l.product_id.id == wid)
        other_lines  = self - wallet_lines
        if other_lines:
            super(SaleOrderLine, other_lines)._compute_price_unit()
        # wallet_lines: do nothing — preserve the SQL-written negative price_unit

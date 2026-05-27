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

    wallet_amount_used = fields.Float(string='Wallet Amount Used', default=0.0,
        digits=(16, 2))
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

    # FIX: cancel pending/approved commissions when the order is cancelled
    def action_cancel(self):
        res = super().action_cancel()
        for order in self:
            cancellable = order.commission_ids.filtered(
                lambda c: c.state in ('pending', 'approved')
            )
            if cancellable:
                cancellable.action_cancel()
        return res

    def _generate_mlm_commissions(self):
        self.ensure_one()
        if not self.referrer_partner_id:
            return

        LevelRate  = self.env['mlm.level.rate'].sudo()
        Commission = self.env['mlm.commission'].sudo()
        RuleModel  = self.env['product.commission.rule'].sudo()

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

        for line in self.order_line:
            if not line.product_id or line.price_subtotal <= 0:
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
                    base = {
                        'order_id': self.id, 'order_line_id': line.id,
                        'product_id': line.product_id.id,
                        'buyer_partner_id': buyer.id, 'level': 1,
                        'level_rate': lr.rate, 'total_commission': total_pot,
                        'amount': half, 'is_l1_split': True,
                        'state': 'pending', 'payout_method': 'wallet',
                    }
                    Commission.create({**base, 'partner_id': referrer.id,
                                       'split_partner_id': buyer_upline.id})
                    Commission.create({**base, 'partner_id': buyer_upline.id,
                                       'split_partner_id': referrer.id})
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
                    Commission.create({
                        'partner_id': recipient.id, 'order_id': self.id,
                        'order_line_id': line.id, 'product_id': line.product_id.id,
                        'buyer_partner_id': buyer.id, 'level': lr.level,
                        'level_rate': lr.rate, 'total_commission': total_pot,
                        'amount': level_amount, 'is_admin_allocation': is_admin,
                        'state': 'pending', 'payout_method': 'wallet',
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

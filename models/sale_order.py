from odoo import models, fields, api


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    referrer_partner_id = fields.Many2one(
        'res.partner',
        string='Referred By',
        index=True,
        tracking=True,
        help='Affiliate whose referral link was used for this order.',
    )
    referral_code_used = fields.Char(
        string='Referral Code Used',
        copy=False,
    )
    commission_ids = fields.One2many(
        'mlm.commission',
        'order_id',
        string='Commissions',
    )
    commission_count = fields.Integer(
        compute='_compute_commission_stats',
        string='Commission Count',
    )
    total_commission_amount = fields.Float(
        compute='_compute_commission_stats',
        string='Total Commissions',
        digits=(16, 2),
    )

    @api.depends('commission_ids', 'commission_ids.amount')
    def _compute_commission_stats(self):
        for order in self:
            order.commission_count = len(order.commission_ids)
            order.total_commission_amount = sum(order.commission_ids.mapped('amount'))

    # ── Hook: capture referrer from request cookie on _cart_update ───────────
    # This is the safest Odoo 18 hook - called every time a product is added
    # to or removed from the cart, without needing to override any route.

    def _cart_update(self, product_id=None, line_id=None,
                     add_qty=0, set_qty=0, **kwargs):
        """Attach referrer from mlm_ref cookie when cart is first modified."""
        result = super()._cart_update(
            product_id=product_id,
            line_id=line_id,
            add_qty=add_qty,
            set_qty=set_qty,
            **kwargs,
        )
        # Only try once (referrer already set → skip)
        if not self.referrer_partner_id:
            self._attach_referrer_from_cookie()
        return result

    def _attach_referrer_from_cookie(self):
        """Read mlm_ref cookie from the current HTTP request and set referrer."""
        try:
            from odoo.http import request as http_request
            ref_code = (
                http_request.httprequest.cookies.get('mlm_ref', '').strip()
            )
        except Exception:
            return  # Not in an HTTP context (e.g. unit tests)

        if not ref_code:
            return

        partner = self.env['res.partner'].sudo().search(
            [('referral_code', '=', ref_code)], limit=1
        )
        if not partner:
            return
        # Prevent self-referral
        if partner == self.partner_id:
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
        Walk up the MLM upline chain from the direct referrer.
        For each ancestor at depth N, check every order line for a
        product.commission.rule at level N and create an mlm.commission record.

        Safety: stops at MAX_LEVELS or on circular upline reference.
        """
        self.ensure_one()
        if not self.referrer_partner_id:
            return

        CommissionRule = self.env['product.commission.rule'].sudo()
        Commission = self.env['mlm.commission'].sudo()

        current_partner = self.referrer_partner_id
        level = 1
        visited = set()
        MAX_LEVELS = 20

        while current_partner and level <= MAX_LEVELS:
            if current_partner.id in visited:
                break  # Circular reference guard
            visited.add(current_partner.id)

            for line in self.order_line:
                # Skip non-product lines (delivery, discounts, etc.)
                if not line.product_id or line.price_subtotal <= 0:
                    continue

                rule = CommissionRule.search([
                    ('product_tmpl_id', '=', line.product_id.product_tmpl_id.id),
                    ('level', '=', level),
                    ('active', '=', True),
                ], limit=1)

                if not rule:
                    continue

                amount = rule.compute_commission(line.price_subtotal)
                if amount <= 0:
                    continue

                Commission.create({
                    'partner_id': current_partner.id,
                    'order_id': self.id,
                    'order_line_id': line.id,
                    'product_id': line.product_id.id,
                    'buyer_partner_id': self.partner_id.id,
                    'level': level,
                    'commission_type': rule.commission_type,
                    'commission_value': rule.commission_value,
                    'amount': amount,
                    'state': 'pending',
                    'payout_method': 'wallet',
                })

            # Move one level up the chain
            current_partner = current_partner.upline_partner_id
            level += 1

    # ── Smart button action ───────────────────────────────────────────────────

    def action_view_commissions(self):
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
        'mlm.commission',
        'order_line_id',
        string='Commissions',
    )

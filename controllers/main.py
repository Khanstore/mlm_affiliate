import logging

from odoo import http
from odoo.http import request
from odoo.addons.auth_signup.controllers.main import AuthSignupHome

_logger = logging.getLogger(__name__)


class AffiliateController(http.Controller):

    # ── Referral redirect ─────────────────────────────────────────────────────

    @http.route('/ref/<string:code>', type='http', auth='public',
                website=True, sitemap=False)
    def referral_redirect(self, code, redirect='/', **kwargs):
        return self._do_referral_redirect(code, redirect or '/')

    @http.route('/ref/<string:code>/<path:subpath>', type='http', auth='public',
                website=True, sitemap=False)
    def referral_redirect_subpath(self, code, subpath='', **kwargs):
        return self._do_referral_redirect(code, '/' + subpath)

    def _do_referral_redirect(self, code, destination):
        # Safety: only redirect to internal paths
        if not destination or not destination.startswith('/'):
            destination = '/shop'

        partner = request.env['res.partner'].sudo().search(
            [('referral_code', '=', code)], limit=1
        )

        response = request.redirect(destination)
        if partner:
            response.set_cookie('mlm_ref', code, max_age=30 * 24 * 60 * 60,
                                httponly=True, samesite='Lax')
            # FEATURE: increment click counter
            try:
                from odoo.fields import Datetime
                partner.sudo().write({
                    'referral_click_count': partner.referral_click_count + 1,
                    'referral_last_click': Datetime.now(),
                })
            except Exception:
                _logger.exception("MLM: failed to update click count for partner %s", partner.id)
        return response

    # ── Wallet: apply to current cart ─────────────────────────────────────────

    @http.route('/shop/wallet/apply', type='json', auth='user', website=True)
    def wallet_apply(self, **kwargs):
        order = request.website.sale_get_order()
        if not order:
            return {'error': 'No active cart.'}

        partner = request.env.user.partner_id.sudo()

        # FIX: use a savepoint to prevent concurrent double-spend
        with request.env.cr.savepoint():
            # Re-read balance inside the savepoint with a write lock
            request.env.cr.execute(
                'SELECT id FROM res_partner WHERE id = %s FOR UPDATE NOWAIT',
                (partner.id,)
            )
            partner.invalidate_recordset(['affiliate_wallet_balance'])
            balance = partner.affiliate_wallet_balance

            if balance <= 0:
                return {'error': 'No wallet balance available.'}

            amount_to_use = round(min(balance, order.amount_total), 2)
            order.sudo().write({
                'wallet_amount_used': amount_to_use,
                'wallet_partner_id':  partner.id,
            })

        remaining = round(order.amount_total - amount_to_use, 2)
        return {
            'success':       True,
            'wallet_used':   amount_to_use,
            'remaining':     remaining,
            'fully_covered': remaining <= 0,
        }

    # ── Wallet: remove from current cart ─────────────────────────────────────

    @http.route('/shop/wallet/remove', type='json', auth='user', website=True)
    def wallet_remove(self, **kwargs):
        order = request.website.sale_get_order()
        if not order:
            return {'error': 'No active cart.'}
        order.sudo().write({'wallet_amount_used': 0.0, 'wallet_partner_id': False})
        return {'success': True}

    # ── Wallet: complete checkout with wallet ─────────────────────────────────

    @http.route('/shop/wallet/pay', type='http', auth='user',
                website=True, methods=['POST'])
    def wallet_pay(self, **kwargs):
        order = request.website.sale_get_order()
        if not order or not order.order_line:
            return request.redirect('/shop/cart')

        # FIX: guard against re-confirming an already-processed order
        if order.state in ('sale', 'done', 'cancel'):
            return request.redirect('/shop/cart')

        partner = request.env.user.partner_id.sudo()
        balance = partner.affiliate_wallet_balance

        if balance < order.amount_total:
            return request.redirect('/shop/cart?wallet_error=1')

        order.sudo().write({
            'wallet_amount_used': order.amount_total,
            'wallet_partner_id':  partner.id,
        })
        order.sudo().with_context(send_email=True).action_confirm()
        request.website.sale_reset()
        return request.redirect(
            f'/shop/confirmation?order_id={order.id}&access_token={order.access_token}'
        )

    # ── Affiliate portal dashboard ────────────────────────────────────────────

    @http.route('/affiliate/dashboard', type='http', auth='user', website=True)
    def affiliate_dashboard(self, **kwargs):
        partner = request.env.user.partner_id.sudo()

        if not partner.referral_code:
            partner.action_generate_referral_code()
            partner.invalidate_recordset(['referral_code', 'is_affiliate'])

        base_url = (
            request.env['ir.config_parameter'].sudo()
            .get_param('web.base.url', '').rstrip('/')
        )
        referral_url = (
            f"{base_url}/ref/{partner.referral_code}"
            if partner.referral_code else ''
        )

        # FEATURE: generate QR code as base64 PNG
        qr_code_b64 = None
        if referral_url:
            try:
                import qrcode
                from io import BytesIO
                import base64
                img = qrcode.make(referral_url)
                buf = BytesIO()
                img.save(buf, format='PNG')
                qr_code_b64 = base64.b64encode(buf.getvalue()).decode('ascii')
            except Exception:
                pass  # qrcode library not installed; QR section is hidden in template

        commissions = request.env['mlm.commission'].sudo().search(
            [('partner_id', '=', partner.id)], order='create_date desc', limit=100,
        )

        def _sum(recs):
            return round(sum(recs.mapped('amount')), 2)

        non_cancelled  = commissions.filtered(lambda c: c.state != 'cancelled')
        approved_recs  = commissions.filtered(lambda c: c.state == 'approved')
        paid_recs      = commissions.filtered(lambda c: c.state == 'paid')
        wallet_approved = commissions.filtered(
            lambda c: c.state == 'approved' and c.payout_method == 'wallet'
        )
        wallet_paid = commissions.filtered(
            lambda c: c.state == 'paid' and c.payout_method == 'wallet'
        )

        wallet_orders = request.env['sale.order'].sudo().search([
            ('wallet_partner_id', '=', partner.id),
            ('state', 'in', ['sale', 'done']),
        ])
        wallet_spent   = round(sum(wallet_orders.mapped('wallet_amount_used')), 2)
        wallet_balance = round(_sum(wallet_approved) - _sum(wallet_paid) - wallet_spent, 2)

        stats = {
            'total_earned':       _sum(non_cancelled),
            'pending':            _sum(commissions.filtered(lambda c: c.state == 'pending')),
            'approved':           _sum(approved_recs),
            'paid':               _sum(paid_recs),
            'wallet_balance':     wallet_balance,
            'wallet_spent':       wallet_spent,
            'commission_count':   len(non_cancelled),
            'click_count':        partner.referral_click_count,
            'last_click':         partner.referral_last_click,
        }

        payout_labels = {
            'wallet': 'Wallet Credit',
            'bank':   'Bank Transfer',
            'discount': 'Discount Coupon',
        }
        payout_breakdown = [
            {
                'method': m, 'label': l,
                'amount': _sum(non_cancelled.filtered(lambda c, m=m: c.payout_method == m)),
                'count':  len(non_cancelled.filtered(lambda c, m=m: c.payout_method == m)),
            }
            for m, l in payout_labels.items()
            if non_cancelled.filtered(lambda c, m=m: c.payout_method == m)
        ]

        downline = request.env['res.partner'].sudo().search(
            [('upline_partner_id', '=', partner.id)]
        )

        wallet_order_history = request.env['sale.order'].sudo().search([
            ('wallet_partner_id', '=', partner.id),
            ('state', 'in', ['sale', 'done']),
        ], order='date_order desc', limit=20)

        # FEATURE: Top 10 leaderboard (public, only names + amounts)
        leaderboard = request.env['res.partner'].sudo().search_read(
            [('is_affiliate', '=', True), ('total_commission_earned', '>', 0)],
            fields=['name', 'total_commission_earned', 'tier_id', 'downline_count'],
            order='total_commission_earned desc',
            limit=10,
        )

        return request.render('mlm_affiliate.portal_affiliate_dashboard', {
            'partner':              partner,
            'referral_url':         referral_url,
            'qr_code_b64':          qr_code_b64,
            'commissions':          commissions[:50],
            'stats':                stats,
            'downline':             downline,
            'payout_breakdown':     payout_breakdown,
            'wallet_order_history': wallet_order_history,
            'leaderboard':          leaderboard,
        })


# ── Signup hook ───────────────────────────────────────────────────────────────

class AffiliateSignupController(AuthSignupHome):

    @http.route()
    def web_auth_signup(self, *args, **kw):
        uid_before = request.session.uid
        response = super().web_auth_signup(*args, **kw)
        uid_after = request.session.uid
        if uid_after and uid_after != uid_before:
            try:
                user = request.env['res.users'].sudo().browse(uid_after)
                if user.exists() and user.partner_id:
                    self._mlm_link_new_user(user.partner_id)
            except Exception:
                # FIX: log instead of silently swallowing the exception
                _logger.exception("MLM: failed to link upline for new user uid=%s", uid_after)
        return response

    @staticmethod
    def _mlm_link_new_user(partner):
        ref_code = request.httprequest.cookies.get('mlm_ref', '').strip()
        if not ref_code:
            return
        referrer = request.env['res.partner'].sudo().search(
            [('referral_code', '=', ref_code)], limit=1
        )
        if not referrer or referrer == partner:
            return
        partner.sudo().write({'upline_partner_id': referrer.id, 'is_affiliate': True})
        if not partner.referral_code:
            partner.sudo().action_generate_referral_code()

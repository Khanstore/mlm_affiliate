from odoo import http
from odoo.http import request


class AffiliateController(http.Controller):
    """
    Two routes:
      /ref/<code>              – pretty referral link, sets cookie, redirects to /shop
      /affiliate/dashboard     – portal page for affiliates
    """

    # ── Referral redirect ─────────────────────────────────────────────────────

    @http.route(
        '/ref/<string:code>',
        type='http',
        auth='public',
        website=True,
        sitemap=False,
    )
    def referral_redirect(self, code, redirect='/', **kwargs):
        """
        Set a 30-day mlm_ref cookie and redirect to /shop.
        The cookie is later read by sale.order._attach_referrer_from_cookie()
        when the visitor adds a product to the cart.

        Usage:  https://yoursite.com/ref/ABC12345
        Custom: https://yoursite.com/ref/ABC12345?redirect=/shop/product-slug
        """
        partner = request.env['res.partner'].sudo().search(
            [('referral_code', '=', code)], limit=1
        )

        # Only redirect to relative paths to prevent open-redirect attacks
        redirect_url = redirect if (redirect and redirect.startswith('/')) else '/shop'
        response = request.redirect(redirect_url)

        if partner:
            response.set_cookie(
                'mlm_ref',
                code,
                max_age=30 * 24 * 60 * 60,  # 30 days in seconds
                httponly=True,
                samesite='Lax',
            )

        return response

    # ── Affiliate portal dashboard ────────────────────────────────────────────

    @http.route(
        '/affiliate/dashboard',
        type='http',
        auth='user',
        website=True,
    )
    def affiliate_dashboard(self, **kwargs):
        partner = request.env.user.partner_id

        # Auto-generate a referral code on first visit
        if not partner.referral_code:
            partner.sudo().action_generate_referral_code()
            # Re-read after sudo write
            partner = request.env.user.partner_id

        base_url = (
            request.env['ir.config_parameter']
            .sudo()
            .get_param('web.base.url', '')
            .rstrip('/')
        )
        referral_url = (
            f"{base_url}/ref/{partner.referral_code}"
            if partner.referral_code
            else ''
        )

        commissions = request.env['mlm.commission'].sudo().search(
            [('partner_id', '=', partner.id)],
            order='create_date desc',
            limit=100,
        )

        def _sum(recs):
            return round(sum(recs.mapped('amount')), 2)

        stats = {
            'total_earned':   _sum(commissions.filtered(lambda c: c.state != 'cancelled')),
            'pending':        _sum(commissions.filtered(lambda c: c.state == 'pending')),
            'approved':       _sum(commissions.filtered(lambda c: c.state == 'approved')),
            'paid':           _sum(commissions.filtered(lambda c: c.state == 'paid')),
            'wallet_balance': round(partner.affiliate_wallet_balance, 2),
        }

        downline = request.env['res.partner'].sudo().search(
            [('upline_partner_id', '=', partner.id)]
        )

        return request.render('mlm_affiliate.portal_affiliate_dashboard', {
            'partner':      partner,
            'referral_url': referral_url,
            'commissions':  commissions[:50],
            'stats':        stats,
            'downline':     downline,
        })

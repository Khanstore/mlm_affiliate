import re
from odoo import http
from odoo.http import request
from odoo.addons.auth_signup.controllers.main import AuthSignupHome


# ─────────────────────────────────────────────────────────────────────────────
# 1. Referral link + Portal dashboard
# ─────────────────────────────────────────────────────────────────────────────

class AffiliateController(http.Controller):

    @http.route(
        ['/ref/<string:code>',
        '/ref/<string:code>/<path:subpath>'],
        type='http',
        auth='public',
        website=True,
        sitemap=False,
    )
    def referral_redirect(self, code, subpath='', **kwargs):
        """
        Sets the mlm_ref cookie then either:
          - Renders an OG-tagged intermediate page (when a product is found)
            so Facebook/WhatsApp/etc. can generate a rich link preview, OR
          - Falls back to a plain 302 redirect for non-product paths.

        Facebook's crawler never follows 302 redirects for OG scraping, so
        a bare redirect produces no preview.  This page contains all the
        og: tags the crawler needs, plus an instant JS redirect for humans.
        """
        partner = request.env['res.partner'].sudo().search(
            [('referral_code', '=', code)], limit=1
        )

        redirect_url = '/{}'.format(subpath.lstrip('/')) if subpath else '/shop'
        # if not subpath:
        #     response = request.redirect(redirect_url)
        # ── Try to find the product for OG tags ──────────────────────────
        product = self._product_from_subpath(subpath)

        if product:
            base_url = (
                request.env['ir.config_parameter']
                .sudo()
                .get_param('web.base.url', '')
                .rstrip('/')
            )
            # Full canonical referral URL (what was shared)
            referral_url = '{}/ref/{}/{}'.format(base_url, code, subpath.lstrip('/'))

            response = request.render(
                'mlm_affiliate.referral_og_redirect',
                {
                    'product':      product,
                    'redirect_url': redirect_url,
                    'referral_url': referral_url,
                    'base_url':     base_url,
                }
            )
        else:
            response = request.redirect(redirect_url)

        # ── Set referral cookie regardless of path ────────────────────────
        if partner:
            response.set_cookie(
                'mlm_ref',
                code,
                max_age=30 * 24 * 60 * 60,
                httponly=True,
                samesite='Lax',
            )

        return response

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _product_from_subpath(subpath):
        """
        Extract a product.template from a URL subpath like:
            shop/prb3forms-prb-3-forms-154
            shop/product/awesome-tee-123

        Odoo appends the product template ID as the last numeric segment,
        so we pull the trailing integer and do a direct browse().
        """
        if not subpath:
            return None

        # last segment of the path, e.g. "prb3forms-prb-3-forms-154"
        slug = subpath.rstrip('/').split('/')[-1]
        match = re.search(r'-(\d+)$', slug)
        if not match:
            # try the whole segment being numeric
            match = re.fullmatch(r'(\d+)', slug)
        if not match:
            return None

        product_id = int(match.group(1))
        product = request.env['product.template'].sudo().browse(product_id)
        return product if product.exists() else None

    @http.route(
        '/affiliate/dashboard',
        type='http',
        auth='user',
        website=True,
    )
    def affiliate_dashboard(self, **kwargs):
        partner = request.env.user.partner_id

        if not partner.referral_code:
            partner.sudo().action_generate_referral_code()
            partner = request.env.user.partner_id

        base_url = (
            request.env['ir.config_parameter']
            .sudo()
            .get_param('web.base.url', '')
            .rstrip('/')
        )
        referral_url = (
            f"{base_url}/ref/{partner.referral_code}"
            if partner.referral_code else ''
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


# ─────────────────────────────────────────────────────────────────────────────
# 2. Signup hook — link new user as downline of the referrer
# ─────────────────────────────────────────────────────────────────────────────

class AffiliateSignupController(AuthSignupHome):
    def web_auth_signup(self, *args, **kw):
        uid_before = request.session.uid
        response = super().web_auth_signup(*args, **kw)
        uid_after = request.session.uid

        if uid_after and uid_after != uid_before:
            try:
                new_user = request.env['res.users'].sudo().browse(uid_after)
                if new_user.exists() and new_user.partner_id:
                    self._mlm_link_new_user(new_user.partner_id)
            except Exception:
                pass

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

        partner.sudo().write({
            'upline_partner_id': referrer.id,
            'is_affiliate': True,
        })

        if not partner.referral_code:
            partner.sudo().action_generate_referral_code()

from odoo import http
from odoo.http import request
from odoo.addons.auth_signup.controllers.main import AuthSignupHome


# ─────────────────────────────────────────────────────────────────────────────
# 1. Referral link + Portal dashboard
# ─────────────────────────────────────────────────────────────────────────────

class AffiliateController(http.Controller):

    @http.route(
        '/ref/<string:code>/<path:subpath>',
        type='http',
        auth='public',
        website=True,
        sitemap=False,
    )
    def referral_redirect(self, code, subpath='', **kwargs):  # ← added subpath
        partner = request.env['res.partner'].sudo().search(
            [('referral_code', '=', code)], limit=1
        )

        # Build redirect: use subpath from URL, fall back to /shop
        redirect_url = '/{}'.format(subpath.lstrip('/')) if subpath else '/shop'  # ← use subpath
        response = request.redirect(redirect_url)

        if partner:
            response.set_cookie(
                'mlm_ref',
                code,
                max_age=30 * 24 * 60 * 60,
                httponly=True,
                samesite='Lax',
            )

        return response

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
    """
    Extends Odoo's standard signup to auto-link the new user to their referrer.

    When someone who clicked a referral link (cookie present) registers an
    account within 30 days, we:
      • set  partner.upline_partner_id  = referrer partner
      • set  partner.is_affiliate       = True  (they can now refer others)
      • auto-generate their own referral code so they can start sharing

    This runs ONLY on successful new-account creation (not on login).
    Errors in MLM logic never block the signup itself.
    """

    def web_auth_signup(self, *args, **kw):
        # Capture session uid before signup attempt
        uid_before = request.session.uid

        response = super().web_auth_signup(*args, **kw)

        # Capture session uid after signup
        uid_after = request.session.uid

        # A new login happened (uid changed and is now a real user)
        if uid_after and uid_after != uid_before:
            try:
                new_user = (
                    request.env['res.users']
                    .sudo()
                    .browse(uid_after)
                )
                if new_user.exists() and new_user.partner_id:
                    self._mlm_link_new_user(new_user.partner_id)
            except Exception:
                # Never let MLM logic crash the signup
                pass

        return response

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _mlm_link_new_user(partner):
        """
        Read the mlm_ref cookie and, if valid, set the new partner's upline,
        enable affiliate status, and generate their own referral code.
        """
        ref_code = request.httprequest.cookies.get('mlm_ref', '').strip()
        if not ref_code:
            return

        referrer = request.env['res.partner'].sudo().search(
            [('referral_code', '=', ref_code)], limit=1
        )

        if not referrer or referrer == partner:
            return

        # Link the new user as direct downline of the referrer
        partner.sudo().write({
            'upline_partner_id': referrer.id,
            'is_affiliate': True,
        })

        # Give the new user their own referral code immediately
        # so they can start referring others right away
        if not partner.referral_code:
            partner.sudo().action_generate_referral_code()

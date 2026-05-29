import logging

from odoo import http
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.addons.auth_signup.controllers.main import AuthSignupHome

_logger = logging.getLogger(__name__)


class AffiliatePortal(CustomerPortal):
    """
    Extends the standard customer portal to inject the Affiliate & Earnings
    entry into /my/home and serve the full dashboard at /affiliate/dashboard.
    """

    # ── Portal home count ─────────────────────────────────────────────────────

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'affiliate_commission_count' in counters:
            partner = request.env.user.partner_id
            values['affiliate_commission_count'] = (
                request.env['mlm.commission'].sudo().search_count(
                    [('partner_id', '=', partner.id),
                     ('state', '!=', 'cancelled')]
                )
            )
        return values

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
        if not destination or not destination.startswith('/'):
            destination = '/shop'
        partner = request.env['res.partner'].sudo().search(
            [('referral_code', '=', code)], limit=1
        )
        response = request.redirect(destination)
        if partner:
            response.set_cookie('mlm_ref', code, max_age=30 * 24 * 60 * 60,
                                httponly=True, samesite='Lax')
            try:
                from odoo.fields import Datetime
                partner.sudo().write({
                    'referral_click_count': partner.referral_click_count + 1,
                    'referral_last_click': Datetime.now(),
                })
            except Exception:
                _logger.exception('MLM: click count update failed for partner %s', partner.id)
        return response

    # ── Wallet: apply to current cart ─────────────────────────────────────────

    @http.route('/shop/wallet/apply', type='json', auth='user', website=True)
    def wallet_apply(self, **kwargs):
        order = request.website.sale_get_order()
        if not order:
            return {'error': 'No active cart.'}
        partner = request.env.user.partner_id.sudo()
        with request.env.cr.savepoint():
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

    @http.route('/shop/wallet/remove', type='json', auth='user', website=True)
    def wallet_remove(self, **kwargs):
        order = request.website.sale_get_order()
        if not order:
            return {'error': 'No active cart.'}
        order.sudo().write({'wallet_amount_used': 0.0, 'wallet_partner_id': False})
        return {'success': True}

    @http.route('/shop/wallet/pay', type='http', auth='user',
                website=True, methods=['POST'])
    def wallet_pay(self, **kwargs):
        order = request.website.sale_get_order()
        if not order or not order.order_line:
            return request.redirect('/shop/cart')
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

    @http.route(['/my/affiliate', '/affiliate/dashboard'],
                type='http', auth='user', website=True)
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

        # QR code
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
                pass

        commissions = request.env['mlm.commission'].sudo().search(
            [('partner_id', '=', partner.id)], order='create_date desc', limit=100,
        )

        def _sum(recs):
            return round(sum(recs.mapped('amount')), 2)

        non_cancelled   = commissions.filtered(lambda c: c.state != 'cancelled')
        approved_wallet = commissions.filtered(
            lambda c: c.state == 'approved' and c.payout_method == 'wallet'
        )
        paid_wallet = commissions.filtered(
            lambda c: c.state == 'paid' and c.payout_method == 'wallet'
        )

        wallet_orders = request.env['sale.order'].sudo().search([
            ('wallet_partner_id', '=', partner.id),
            ('state', 'in', ['sale', 'done']),
        ])
        wallet_spent   = round(sum(wallet_orders.mapped('wallet_amount_used')), 2)
        wallet_balance = round(_sum(approved_wallet) - _sum(paid_wallet) - wallet_spent, 2)

        # Monthly earnings for chart (last 12 months)
        from datetime import date, timedelta
        import calendar
        monthly_data = []
        today = date.today()
        for i in range(11, -1, -1):
            d = today.replace(day=1)
            for _ in range(i):
                d = (d - timedelta(days=1)).replace(day=1)
            last_day = calendar.monthrange(d.year, d.month)[1]
            month_end = d.replace(day=last_day)
            month_comms = non_cancelled.filtered(
                lambda c, s=d.isoformat(), e=month_end.isoformat():
                    c.order_date and s <= c.order_date.date().isoformat() <= e
            )
            monthly_data.append({'label': d.strftime('%b %Y'), 'amount': _sum(month_comms)})

        stats = {
            'total_earned':   _sum(non_cancelled),
            'pending':        _sum(commissions.filtered(lambda c: c.state == 'pending')),
            'approved':       _sum(commissions.filtered(lambda c: c.state == 'approved')),
            'paid':           _sum(commissions.filtered(lambda c: c.state == 'paid')),
            'wallet_balance': wallet_balance,
            'wallet_spent':   wallet_spent,
            'commission_count': len(non_cancelled),
            'click_count':    partner.referral_click_count,
            'last_click':     partner.referral_last_click,
        }

        downline = request.env['res.partner'].sudo().search(
            [('upline_partner_id', '=', partner.id)]
        )

        wallet_order_history = request.env['sale.order'].sudo().search([
            ('wallet_partner_id', '=', partner.id),
            ('state', 'in', ['sale', 'done']),
        ], order='date_order desc', limit=20)

        leaderboard_partners = request.env['res.partner'].sudo().search_read(
            [('is_affiliate', '=', True), ('total_commission_earned', '>', 0)],
            fields=['name', 'total_commission_earned', 'tier_id', 'downline_count'],
        )
        leaderboard = sorted(
            leaderboard_partners,
            key=lambda p: p['total_commission_earned'],
            reverse=True,
        )[:10]

        payout_requests = request.env['mlm.payout.request'].sudo().search([
            ('partner_id', '=', partner.id),
        ], order='create_date desc', limit=10)

        active_campaign = request.env['mlm.campaign'].sudo().get_active_campaign(partner.id)

        MilestoneModel = request.env['mlm.milestone'].sudo()
        AwardModel = request.env['mlm.partner.milestone'].sudo()
        all_milestones = MilestoneModel.search([('active', '=', True)])
        awarded_ids = AwardModel.search([('partner_id', '=', partner.id)]).mapped('milestone_id').ids
        milestones_display = [{
            'name':         ms.name,
            'min_earned':   ms.min_earned,
            'min_referrals': ms.min_referrals,
            'bonus_amount': ms.bonus_amount,
            'achieved':     ms.id in awarded_ids,
            'note':         ms.note or '',
        } for ms in all_milestones]

        values = {
            'partner':              partner,
            'referral_url':         referral_url,
            'qr_code_b64':          qr_code_b64,
            'commissions':          commissions[:50],
            'stats':                stats,
            'downline':             downline,
            'wallet_order_history': wallet_order_history,
            'leaderboard':          leaderboard,
            'monthly_data':         monthly_data,
            'payout_requests':      payout_requests,
            'active_campaign':      active_campaign,
            'milestones_display':   milestones_display,
            'page_name':            'affiliate',
        }
        return request.render('mlm_affiliate.portal_affiliate_dashboard', values)

    # ── Payout request submission ─────────────────────────────────────────────

    @http.route('/affiliate/payout/request', type='http', auth='user',
                website=True, methods=['POST'])
    def affiliate_payout_request(self, amount=0, payout_method='bank',
                                  bank_account='', note='', **kwargs):
        partner = request.env.user.partner_id.sudo()
        try:
            amount = float(amount)
        except (ValueError, TypeError):
            return request.redirect('/my/affiliate?payout_error=1')

        if amount <= 0 or amount > partner.affiliate_wallet_balance:
            return request.redirect('/my/affiliate?payout_error=1')

        approved_comms = request.env['mlm.commission'].sudo().search([
            ('partner_id', '=', partner.id),
            ('state', '=', 'approved'),
            ('payout_method', '=', 'wallet'),
        ])

        request.env['mlm.payout.request'].sudo().create({
            'partner_id':       partner.id,
            'amount_requested': amount,
            'payout_method':    payout_method,
            'bank_account':     bank_account or partner.affiliate_bank_account,
            'note':             note,
            'commission_ids':   [(6, 0, approved_comms.ids)],
        })
        return request.redirect('/my/affiliate?payout_submitted=1')


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
                _logger.exception('MLM: failed to link upline for new user uid=%s', uid_after)
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
        require_approval = request.env['ir.config_parameter'].sudo().get_param(
            'mlm_affiliate.require_application', 'False'
        ).lower() in ('1', 'true', 'yes')
        status = 'pending' if require_approval else 'approved'
        partner.sudo().write({
            'upline_partner_id': referrer.id,
            'is_affiliate':      True,
            'affiliate_status':  status,
        })
        if not partner.referral_code:
            partner.sudo().action_generate_referral_code()

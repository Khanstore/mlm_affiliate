import logging

from odoo import http
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.addons.auth_signup.controllers.main import AuthSignupHome

_logger = logging.getLogger(__name__)


class AffiliatePortal(CustomerPortal):

    # ── Portal home count ─────────────────────────────────────────────────────
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'affiliate_commission_count' in counters:
            partner = request.env.user.partner_id
            values['affiliate_commission_count'] = (
                request.env['mlm.commission'].sudo().search_count(
                    [('partner_id', '=', partner.id), ('state', '!=', 'cancelled')]
                )
            )
        return values

    # ── Referral redirect ─────────────────────────────────────────────────────
    @http.route('/ref/<string:code>', type='http', auth='public', website=True, sitemap=False)
    def referral_redirect(self, code, redirect='/', **kwargs):
        return self._do_referral_redirect(code, redirect or '/')

    @http.route('/ref/<string:code>/<path:subpath>', type='http', auth='public', website=True, sitemap=False)
    def referral_redirect_subpath(self, code, subpath='', **kwargs):
        return self._do_referral_redirect(code, '/' + subpath)

    def _do_referral_redirect(self, code, destination):
        if not destination or not destination.startswith('/'):
            destination = '/shop'
        partner = request.env['res.partner'].sudo().search(
            [('referral_code', '=', code)], limit=1)
        response = request.redirect(destination)
        if partner:
            response.set_cookie('mlm_ref', code, max_age=30*24*60*60,
                                httponly=True, samesite='Lax')
            try:
                from odoo.fields import Datetime
                partner.sudo().write({
                    'referral_click_count': partner.referral_click_count + 1,
                    'referral_last_click':  Datetime.now(),
                })
            except Exception:
                _logger.exception('MLM: click count update failed for partner %s', partner.id)
        return response

    # ── Wallet helpers ────────────────────────────────────────────────────────

    def _get_wallet_discount_product(self):
        """Return the Wallet Credit service product (creates it if missing).
        Also self-heals if the product's list_price was changed from 0."""
        env = request.env
        prod_tmpl = env.ref(
            'mlm_affiliate.product_wallet_discount', raise_if_not_found=False)

        if not prod_tmpl:
            prod_tmpl = env['product.template'].sudo().search(
                [('name', '=', 'Affiliate Wallet Credit'), ('type', '=', 'service')], limit=1)

        if not prod_tmpl:
            prod_tmpl = env['product.template'].sudo().create({
                'name': 'Affiliate Wallet Credit',
                'type': 'service',
                'list_price': 0.0,
                'sale_ok': True,
                'purchase_ok': False,
                'website_published': False,
                'taxes_id': [(5, 0, 0)],
                'invoice_policy': 'order',
            })

        # Self-heal: if list_price was changed to non-zero by an admin, reset it
        prod_tmpl = prod_tmpl.sudo()
        if prod_tmpl.list_price != 0.0 or prod_tmpl.taxes_id:
            prod_tmpl.write({'list_price': 0.0, 'taxes_id': [(5, 0, 0)]})

        return prod_tmpl.product_variant_id

    def _apply_wallet_discount_line(self, order, amount):
        """
        Add (or update) a negative order line for the wallet discount.
        Uses direct SQL to set price_unit so Odoo ORM onchanges cannot reset it.
        """
        product = self._get_wallet_discount_product()
        if not product:
            return

        cr = request.env.cr

        # Find any existing wallet line (regardless of current price sign)
        existing = order.sudo().order_line.filtered(
            lambda l: l.product_id.id == product.id)

        neg = -abs(amount)

        if existing:
            if len(existing) > 1:
                existing[1:].sudo().unlink()
            line_id = existing[0].id
        else:
            # Create via ORM with no_recompute context to minimise onchange side-effects
            env = request.env
            SolSudo = env['sale.order.line'].sudo().with_context(
                no_recompute=True,
                mail_notrack=True,
            )
            new_line = SolSudo.create({
                'order_id':        order.id,
                'product_id':      product.id,
                'name':            'Affiliate Wallet Credit',
                'product_uom_qty': 1,
                'price_unit':      0.0,
                'discount':        0.0,
                'sequence':        999,
            })
            line_id = new_line.id

        # Overwrite price_unit via SQL to bypass ORM onchanges/computes
        cr.execute(
            "UPDATE sale_order_line SET price_unit = %s, discount = 0.0 WHERE id = %s",
            (neg, line_id)
        )

        # Clear any taxes on this line (Odoo 18 table name)
        cr.execute(
            "DELETE FROM account_tax_sale_order_line_rel WHERE sale_order_line_id = %s",
            (line_id,)
        )

        # Recompute price_subtotal/price_total on the line from the new price_unit
        line_rec = request.env['sale.order.line'].sudo().browse(line_id)
        line_rec.invalidate_recordset()
        # Trigger recompute of stored monetary fields using the corrected price_unit
        cr.execute("""
            UPDATE sale_order_line
            SET price_subtotal = %s,
                price_total    = %s
            WHERE id = %s
        """, (neg, neg, line_id))

        # Invalidate ORM cache so amount_total recomputes from DB
        order.sudo().invalidate_recordset(['order_line', 'amount_untaxed',
                                           'amount_tax', 'amount_total'])


    def _remove_wallet_discount_line(self, order):
        """Remove the wallet discount line from the order."""
        product = self._get_wallet_discount_product()
        if not product:
            return
        discount_lines = order.order_line.filtered(
            lambda l: l.product_id.id == product.id)
        discount_lines.sudo().unlink()

    # ── Wallet: status ────────────────────────────────────────────────────────
    @http.route('/shop/wallet/status', type='json', auth='user', website=True)
    def wallet_status(self, **kwargs):
        if request.env.user._is_public():
            return {'authenticated': False}
        partner = request.env.user.partner_id.sudo()
        order   = request.website.sale_get_order()
        balance = round(partner.affiliate_wallet_balance, 2)
        applied = round(order.wallet_amount_used, 2) if order else 0.0
        order_total = round(order.amount_total, 2) if order else 0.0
        return {
            'authenticated': True,
            'balance':       balance,
            'applied':       applied,
            'order_total':   order_total,
            'fully_covered': applied > 0 and applied >= order_total,
            'csrf_token':    request.csrf_token(),
        }

    # ── Wallet: apply ─────────────────────────────────────────────────────────
    @http.route('/shop/wallet/apply', type='json', auth='user', website=True)
    def wallet_apply(self, **kwargs):
        order = request.website.sale_get_order()
        if not order or not order.order_line:
            return {'error': 'No active cart. Please add items to your cart first.'}

        partner = request.env.user.partner_id.sudo()
        partner.invalidate_recordset(['affiliate_wallet_balance'])
        balance = partner.affiliate_wallet_balance

        if balance <= 0:
            return {'error': 'No wallet balance available.'}

        # Gross = order total before any wallet discount already applied
        gross = order.amount_total + order.wallet_amount_used
        amount_to_use = round(min(balance, gross), 2)

        if amount_to_use <= 0:
            return {'error': 'Nothing to apply.'}

        # Save wallet metadata on the order
        order.sudo().write({
            'wallet_amount_used': amount_to_use,
            'wallet_partner_id':  partner.id,
        })

        # Apply the negative discount line (uses direct SQL internally)
        try:
            self._apply_wallet_discount_line(order, amount_to_use)
        except Exception as e:
            _logger.exception('MLM wallet_apply: _apply_wallet_discount_line failed: %s', e)
            return {'error': 'Failed to apply wallet credit. Check server logs.'}

        # Re-read updated totals from DB
        order.invalidate_recordset(['amount_total', 'amount_untaxed'])
        remaining     = round(max(order.amount_total, 0), 2)
        fully_covered = remaining <= 0.01

        return {
            'success':       True,
            'wallet_used':   amount_to_use,
            'remaining':     remaining,
            'fully_covered': fully_covered,
        }

    # ── Wallet: remove ────────────────────────────────────────────────────────
    @http.route('/shop/wallet/remove', type='json', auth='user', website=True)
    def wallet_remove(self, **kwargs):
        order = request.website.sale_get_order()
        if not order:
            return {'error': 'No active cart.'}
        # FIX: also remove the discount line so amount_total is restored
        self._remove_wallet_discount_line(order)
        order.sudo().write({'wallet_amount_used': 0.0, 'wallet_partner_id': False})
        return {'success': True}

    # ── Wallet: full-wallet checkout ──────────────────────────────────────────
    @http.route('/shop/wallet/pay', type='http', auth='user', website=True, methods=['POST'])
    def wallet_pay(self, **kwargs):
        order = request.website.sale_get_order()
        if not order or not order.order_line:
            return request.redirect('/shop/cart')
        if order.state in ('sale', 'done', 'cancel'):
            return request.redirect('/shop/cart')
        partner = request.env.user.partner_id.sudo()

        # After the discount line is applied, amount_total should be ≈ 0
        if partner.affiliate_wallet_balance < order.wallet_amount_used:
            return request.redirect('/shop/cart?wallet_error=1')

        # Ensure discount line is present
        if order.wallet_amount_used > 0:
            self._apply_wallet_discount_line(order, order.wallet_amount_used)

        order.sudo().with_context(send_email=True).action_confirm()
        request.website.sale_reset()
        return request.redirect(
            f'/shop/confirmation?order_id={order.id}&access_token={order.access_token}')

    # ── Affiliate portal dashboard ─────────────────────────────────────────────
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
            lambda c: c.state == 'approved' and c.payout_method == 'wallet')
        paid_wallet     = commissions.filtered(
            lambda c: c.state == 'paid' and c.payout_method == 'wallet')

        # Use the stored computed field to avoid double-counting draft orders
        wallet_balance = round(partner.affiliate_wallet_balance, 2)
        wallet_orders = request.env['sale.order'].sudo().search([
            ('wallet_partner_id', '=', partner.id),
            ('state', 'in', ['draft', 'sent', 'sale', 'done']),
            ('wallet_amount_used', '>', 0),
        ])
        wallet_spent = round(sum(wallet_orders.mapped('wallet_amount_used')), 2)

        # ── BUG FIX: compute sub-totals individually as plain Python floats ──
        pending_total  = _sum(commissions.filtered(lambda c: c.state == 'pending'))
        approved_total = _sum(commissions.filtered(lambda c: c.state == 'approved'))
        paid_total     = _sum(commissions.filtered(lambda c: c.state == 'paid'))
        total_earned   = _sum(non_cancelled)

        stats = {
            'total_earned':     total_earned,
            'pending':          pending_total,
            'approved':         approved_total,
            'paid':             paid_total,
            'wallet_balance':   wallet_balance,  # uses partner.affiliate_wallet_balance
            'wallet_spent':     wallet_spent,
            'commission_count': len(non_cancelled),
            'click_count':      partner.referral_click_count,
            'last_click':       partner.referral_last_click,
        }

        from datetime import date, timedelta
        import calendar
        monthly_data = []
        today = date.today()
        for i in range(11, -1, -1):
            d = today.replace(day=1)
            for _ in range(i):
                d = (d - timedelta(days=1)).replace(day=1)
            last_day  = calendar.monthrange(d.year, d.month)[1]
            month_end = d.replace(day=last_day)
            mc = non_cancelled.filtered(
                lambda c, s=d.isoformat(), e=month_end.isoformat():
                    c.order_date and s <= c.order_date.date().isoformat() <= e
            )
            monthly_data.append({'label': d.strftime('%b %Y'), 'amount': _sum(mc)})

        downline = request.env['res.partner'].sudo().search(
            [('upline_partner_id', '=', partner.id)])

        wallet_order_history = request.env['sale.order'].sudo().search([
            ('wallet_partner_id', '=', partner.id),
            ('state', 'in', ['sale', 'done']),
        ], order='date_order desc', limit=20)

        leaderboard = sorted(
            request.env['res.partner'].sudo().search_read(
                [('is_affiliate', '=', True), ('total_commission_earned', '>', 0)],
                fields=['name', 'total_commission_earned', 'tier_id', 'downline_count'],
            ),
            key=lambda p: p['total_commission_earned'], reverse=True,
        )[:10]

        payout_requests = request.env['mlm.payout.request'].sudo().search(
            [('partner_id', '=', partner.id)], order='create_date desc', limit=10)

        active_campaign = request.env['mlm.campaign'].sudo().get_active_campaign(partner.id)

        all_milestones = request.env['mlm.milestone'].sudo().search([('active', '=', True)])
        awarded_ids = request.env['mlm.partner.milestone'].sudo().search(
            [('partner_id', '=', partner.id)]).mapped('milestone_id').ids
        milestones_display = [{
            'name':          ms.name,
            'min_earned':    ms.min_earned,
            'min_referrals': ms.min_referrals,
            'bonus_amount':  ms.bonus_amount,
            'achieved':      ms.id in awarded_ids,
            'note':          ms.note or '',
        } for ms in all_milestones]

        return request.render('mlm_affiliate.portal_affiliate_dashboard', {
            'partner':              partner,
            'referral_url':         referral_url,
            'qr_code_b64':          qr_code_b64,
            'commissions':          commissions[:50],
            'stats':                stats,
            # ── also pass as standalone floats so any template version can use them ──
            'pending_total':        pending_total,
            'approved_total':       approved_total,
            'paid_total':           paid_total,
            'total_earned':         total_earned,
            'wallet_balance':       wallet_balance,
            # ────────────────────────────────────────────────────────────────────────
            'downline':             downline,
            'wallet_order_history': wallet_order_history,
            'leaderboard':          leaderboard,
            'monthly_data':         monthly_data,
            'payout_requests':      payout_requests,
            'active_campaign':      active_campaign,
            'milestones_display':   milestones_display,
            'page_name':            'affiliate',
        })

    # ── Payout request ────────────────────────────────────────────────────────
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
        payout_req = request.env['mlm.payout.request'].sudo().create({
            'partner_id':       partner.id,
            'amount_requested': amount,
            'payout_method':    payout_method,
            'bank_account':     bank_account or partner.affiliate_bank_account,
            'note':             note,
            'commission_ids':   [(6, 0, approved_comms.ids)],
        })
        # Notify admin users with MLM access
        try:
            admin_users = request.env['res.users'].sudo().search([
                ('groups_id', 'in', [request.env.ref('mlm_affiliate.group_mlm_manager').id]),
                ('email', '!=', False),
            ])
            if admin_users:
                payout_req.sudo().message_post(
                    body=(
                        f'New payout request <b>{payout_req.name}</b> submitted by '
                        f'<b>{partner.name}</b> for amount <b>{amount:.2f}</b> '
                        f'via {payout_method}.'
                    ),
                    partner_ids=admin_users.mapped('partner_id').ids,
                    subtype_xmlid='mail.mt_comment',
                )
        except Exception:
            _logger.exception('MLM: failed to notify admin of payout request %s', payout_req.name)
        return request.redirect('/my/affiliate?payout_submitted=1')


# ── Signup hook ───────────────────────────────────────────────────────────────
class AffiliateSignupController(AuthSignupHome):

    @http.route()
    def web_auth_signup(self, *args, **kw):
        uid_before = request.session.uid
        response   = super().web_auth_signup(*args, **kw)
        uid_after  = request.session.uid
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
            [('referral_code', '=', ref_code)], limit=1)
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
        # Clear the referral cookie — upline is now permanently linked
        # so the cookie is no longer needed and should not be reused
        try:
            request.future_response.set_cookie('mlm_ref', '', max_age=0, expires=0)
        except Exception:
            pass

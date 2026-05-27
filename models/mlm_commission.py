import logging
import random
import string

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class MlmCommission(models.Model):
    """
    One record per commission earned per level per order line.
    Auto-created when a referred sale order is confirmed.

    NEW: Sends email notifications to earners on approve and pay state transitions.
    NEW: Monthly summary cron helper.
    """
    _name = 'mlm.commission'
    _description = 'MLM Commission Record'
    _order = 'create_date desc'
    _rec_name = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Reference', readonly=True, copy=False, default='/')

    partner_id = fields.Many2one('res.partner', string='Earner',
        required=True, index=True, ondelete='restrict')

    is_l1_split = fields.Boolean(string='L1 Split', default=False)
    split_partner_id = fields.Many2one('res.partner', string='Split With', ondelete='set null')
    is_admin_allocation = fields.Boolean(string='Admin Allocation', default=False)

    order_id = fields.Many2one('sale.order', string='Sale Order',
        required=True, ondelete='cascade', index=True)
    order_line_id = fields.Many2one('sale.order.line', string='Order Line', ondelete='set null')
    product_id = fields.Many2one('product.product', string='Product', ondelete='set null')
    buyer_partner_id = fields.Many2one('res.partner', string='Buyer', ondelete='set null')

    level = fields.Integer(string='MLM Level', required=True)
    level_rate = fields.Float(string='Level Rate (%)', digits=(6, 2))
    total_commission = fields.Float(string='Total Commission Pot', digits=(16, 2))
    amount = fields.Float(string='Commission Amount', required=True, digits=(16, 2))

    currency_id = fields.Many2one('res.currency', related='order_id.currency_id',
        store=True, string='Currency')

    state = fields.Selection(
        [('pending', 'Pending'), ('approved', 'Approved'),
         ('paid', 'Paid'), ('cancelled', 'Cancelled')],
        string='Status', default='pending', index=True, tracking=True)
    payout_method = fields.Selection(
        [('wallet', 'Wallet Credit'), ('bank', 'Bank Transfer'), ('discount', 'Discount Coupon')],
        string='Payout Method', default='wallet')
    coupon_code = fields.Char(string='Coupon Code', readonly=True, copy=False)
    note = fields.Text(string='Admin Notes')

    order_date = fields.Datetime(related='order_id.date_order', string='Order Date', store=True)
    order_amount = fields.Monetary(related='order_id.amount_total',
        string='Order Total', store=True, currency_field='currency_id')

    # ── ORM ───────────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('mlm.commission') or '/'
        return super().create(vals_list)

    # ── State actions ─────────────────────────────────────────────────────────

    def action_approve(self):
        for rec in self:
            if rec.state == 'pending':
                rec.state = 'approved'
                # FEATURE: notify earner on approval
                rec._send_commission_notification('approved')

    def action_pay(self):
        cfg = self.env['ir.config_parameter'].sudo()
        min_threshold = float(cfg.get_param('mlm_affiliate.min_payout_threshold', 0.0))

        for rec in self:
            if rec.state != 'approved':
                continue
            # FEATURE: enforce minimum payout threshold
            if min_threshold > 0 and rec.amount < min_threshold:
                from odoo.exceptions import UserError
                raise UserError(
                    f'Commission amount {rec.amount:.2f} is below the minimum '
                    f'payout threshold of {min_threshold:.2f}. '
                    f'Adjust the threshold in MLM Affiliate settings.'
                )
            rec.state = 'paid'
            if rec.payout_method == 'discount' and not rec.coupon_code:
                rec.coupon_code = self._generate_coupon_code()
            # FEATURE: notify earner on payment
            rec._send_commission_notification('paid')

    def action_cancel(self):
        for rec in self:
            if rec.state in ('pending', 'approved'):
                rec.state = 'cancelled'

    def action_reset_to_pending(self):
        for rec in self:
            if rec.state == 'cancelled':
                rec.state = 'pending'

    # ── FEATURE: Email notifications ──────────────────────────────────────────

    def _send_commission_notification(self, new_state):
        """Send email to the earner when their commission is approved or paid."""
        self.ensure_one()
        if not self.partner_id.email:
            return
        template_map = {
            'approved': 'mlm_affiliate.email_template_commission_approved',
            'paid':     'mlm_affiliate.email_template_commission_paid',
        }
        xml_id = template_map.get(new_state)
        if not xml_id:
            return
        try:
            template = self.env.ref(xml_id, raise_if_not_found=False)
            if template:
                template.send_mail(self.id, force_send=False)
        except Exception:
            _logger.exception(
                "MLM: failed to send commission notification for record %s (state=%s)",
                self.id, new_state
            )

    # ── FEATURE: Monthly summary cron ────────────────────────────────────────

    @api.model
    def _cron_send_monthly_summary(self):
        """
        Scheduled action: email every active affiliate their monthly
        commission summary (pending, approved, total earned this month).
        """
        from datetime import date, timedelta
        today = date.today()
        first_day = today.replace(day=1)
        last_month_end = first_day - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)

        template = self.env.ref(
            'mlm_affiliate.email_template_monthly_summary', raise_if_not_found=False
        )
        if not template:
            _logger.warning("MLM: monthly summary email template not found — skipping cron.")
            return

        affiliates = self.env['res.partner'].sudo().search([
            ('is_affiliate', '=', True),
            ('email', '!=', False),
        ])
        for partner in affiliates:
            month_commissions = self.sudo().search([
                ('partner_id', '=', partner.id),
                ('order_date', '>=', last_month_start.strftime('%Y-%m-%d')),
                ('order_date', '<=', last_month_end.strftime('%Y-%m-%d 23:59:59')),
                ('state', '!=', 'cancelled'),
            ])
            if not month_commissions:
                continue
            total = sum(month_commissions.mapped('amount'))
            # pass summary as context so the template can render it
            ctx = {
                'month_name': last_month_end.strftime('%B %Y'),
                'month_total': round(total, 2),
                'commission_count': len(month_commissions),
                'wallet_balance': round(partner.affiliate_wallet_balance, 2),
            }
            try:
                template.with_context(**ctx).send_mail(partner.id, force_send=False)
            except Exception:
                _logger.exception("MLM: monthly summary failed for partner %s", partner.id)

    # ── Static helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _generate_coupon_code():
        return 'AFF-' + ''.join(
            random.choices(string.ascii_uppercase + string.digits, k=8)
        )

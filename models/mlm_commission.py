import logging
import random
import string
from datetime import date, timedelta

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MlmCommission(models.Model):
    """
    One record per commission earned per level per order line.
    Auto-created when a referred sale order is confirmed.
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
    is_milestone_bonus = fields.Boolean(string='Milestone Bonus', default=False)

    order_id = fields.Many2one('sale.order', string='Sale Order',
        ondelete='cascade', index=True)
    order_line_id = fields.Many2one('sale.order.line', string='Order Line', ondelete='set null')
    product_id = fields.Many2one('product.product', string='Product', ondelete='set null')
    buyer_partner_id = fields.Many2one('res.partner', string='Buyer', ondelete='set null')

    level = fields.Integer(string='MLM Level', required=True)
    level_rate = fields.Float(string='Level Rate (%)', digits=(6, 2))
    total_commission = fields.Float(string='Total Commission Pot', digits=(16, 2))
    amount = fields.Float(string='Commission Amount', required=True, digits=(16, 2))
    campaign_multiplier = fields.Float(string='Campaign Multiplier', default=1.0, digits=(6, 3))

    currency_id = fields.Many2one('res.currency', related='order_id.currency_id',
        store=True, string='Currency')

    # ── Hold period (fraud protection) ───────────────────────────────────────
    hold_until = fields.Date(string='Hold Until',
        help='Commission cannot be approved before this date (return/refund window).')
    on_hold = fields.Boolean(string='On Hold', compute='_compute_on_hold', store=False)

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

    # ── Accounting ────────────────────────────────────────────────────────────
    account_move_id = fields.Many2one('account.move', string='Expense Journal Entry',
        readonly=True, copy=False,
        help='Journal entry recording this commission as a marketing expense.')

    # ── ORM ───────────────────────────────────────────────────────────────────

    @api.depends('hold_until')
    def _compute_on_hold(self):
        today = date.today()
        for rec in self:
            rec.on_hold = bool(rec.hold_until and rec.hold_until > today)

    @api.model_create_multi
    def create(self, vals_list):
        # Apply hold period from config
        hold_days = int(
            self.env['ir.config_parameter'].sudo()
            .get_param('mlm_affiliate.commission_hold_days', 0)
        )
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('mlm.commission') or '/'
            if hold_days > 0 and not vals.get('hold_until'):
                vals['hold_until'] = (date.today() + timedelta(days=hold_days)).isoformat()
        return super().create(vals_list)

    # ── State actions ─────────────────────────────────────────────────────────

    def action_approve(self):
        held = self.env['mlm.commission']

        for rec in self:
            if rec.state != 'pending':
                continue
            if rec.on_hold:
                _logger.warning(
                    'MLM: commission %s is on hold until %s — skipping auto-approve',
                    rec.name, rec.hold_until
                )
                held |= rec
                continue
            rec.state = 'approved'
            rec._create_accounting_entry()
            rec._send_commission_notification('approved')

        if held:
            names = '\n'.join(
                f'• {r.name} — held until {r.hold_until}' for r in held
            )
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': f'{len(held)} Commission(s) Still On Hold',
                    'message': (
                        f'The following commission(s) were skipped because '
                        f'their hold period has not yet expired:\n\n{names}'
                    ),
                    'type': 'warning',
                    'sticky': True,
                },
            }

    def action_pay(self):
        cfg = self.env['ir.config_parameter'].sudo()
        min_threshold = float(cfg.get_param('mlm_affiliate.min_payout_threshold', 0.0))

        for rec in self:
            if rec.state != 'approved':
                continue
            if min_threshold > 0 and rec.amount < min_threshold:
                raise UserError(
                    f'Commission amount {rec.amount:.2f} is below the minimum '
                    f'payout threshold of {min_threshold:.2f}. '
                    f'Adjust the threshold in MLM Affiliate settings.'
                )
            rec.state = 'paid'
            if rec.payout_method == 'discount' and not rec.coupon_code:
                rec.coupon_code = self._generate_coupon_code()
            rec._send_commission_notification('paid')

    def action_cancel(self):
        for rec in self:
            if rec.state in ('pending', 'approved'):
                rec.state = 'cancelled'
                # Reverse accounting entry if any
                if rec.account_move_id and rec.account_move_id.state == 'posted':
                    try:
                        rec.account_move_id.button_draft()
                        rec.account_move_id.button_cancel()
                    except Exception:
                        _logger.exception('MLM: could not reverse journal entry for %s', rec.name)

    def action_reset_to_pending(self):
        for rec in self:
            if rec.state == 'cancelled':
                rec.state = 'pending'

    # ── Accounting integration ────────────────────────────────────────────────

    def _create_accounting_entry(self):
        """
        Post a journal entry recording this commission as a marketing/affiliate expense.
        Debit: MLM Commission Expense account
        Credit: MLM Commissions Payable account
        Both account XML IDs are configured in settings; if not set, skip silently.
        """
        self.ensure_one()
        if self.account_move_id:
            return  # already created

        cfg = self.env['ir.config_parameter'].sudo()
        expense_account_id = int(cfg.get_param('mlm_affiliate.expense_account_id', 0))
        payable_account_id = int(cfg.get_param('mlm_affiliate.payable_account_id', 0))

        if not expense_account_id or not payable_account_id:
            return  # accounting not configured — skip gracefully

        AccountAccount = self.env['account.account'].sudo()
        expense_account = AccountAccount.browse(expense_account_id)
        payable_account = AccountAccount.browse(payable_account_id)

        if not expense_account.exists() or not payable_account.exists():
            return

        journal_id = int(cfg.get_param('mlm_affiliate.journal_id', 0))
        if not journal_id:
            # Fall back to the first miscellaneous journal
            journal = self.env['account.journal'].sudo().search(
                [('type', '=', 'general')], limit=1
            )
            if not journal:
                return
            journal_id = journal.id

        currency = self.currency_id or self.env.company.currency_id
        move_vals = {
            'journal_id': journal_id,
            'ref': f'MLM Commission — {self.name} / {self.partner_id.name}',
            'date': fields.Date.today(),
            'line_ids': [
                (0, 0, {
                    'account_id': expense_account.id,
                    'name': f'MLM Commission {self.name} — Level {self.level}',
                    'partner_id': self.partner_id.id,
                    'debit': self.amount,
                    'credit': 0.0,
                    'currency_id': currency.id,
                }),
                (0, 0, {
                    'account_id': payable_account.id,
                    'name': f'MLM Commission Payable {self.name}',
                    'partner_id': self.partner_id.id,
                    'debit': 0.0,
                    'credit': self.amount,
                    'currency_id': currency.id,
                }),
            ],
        }
        try:
            move = self.env['account.move'].sudo().create(move_vals)
            move.action_post()
            self.account_move_id = move
        except Exception:
            _logger.exception('MLM: failed to create accounting entry for commission %s', self.name)

    # ── Email notifications ───────────────────────────────────────────────────

    def _send_commission_notification(self, new_state):
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
                'MLM: failed to send commission notification for record %s (state=%s)',
                self.id, new_state
            )

    # ── Monthly summary cron ──────────────────────────────────────────────────

    @api.model
    def _cron_send_monthly_summary(self):
        send_enabled = self.env['ir.config_parameter'].sudo().get_param(
            'mlm_affiliate.send_monthly_summary', 'True'
        )
        if send_enabled.lower() not in ('1', 'true', 'yes'):
            return

        today = date.today()
        first_day = today.replace(day=1)
        last_month_end = first_day - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)

        template = self.env.ref(
            'mlm_affiliate.email_template_monthly_summary', raise_if_not_found=False
        )
        if not template:
            _logger.warning('MLM: monthly summary email template not found — skipping cron.')
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
            ctx = {
                'month_name': last_month_end.strftime('%B %Y'),
                'month_total': round(total, 2),
                'commission_count': len(month_commissions),
                'wallet_balance': round(partner.affiliate_wallet_balance, 2),
            }
            try:
                template.with_context(**ctx).send_mail(partner.id, force_send=False)
            except Exception:
                _logger.exception('MLM: monthly summary failed for partner %s', partner.id)

    # ── Hold period cron ──────────────────────────────────────────────────────

    @api.model
    def _cron_release_held_commissions(self):
        """Auto-approve commissions whose hold period has expired."""
        today = date.today()
        held = self.sudo().search([
            ('state', '=', 'pending'),
            ('hold_until', '!=', False),
            ('hold_until', '<=', fields.Date.to_string(today)),
        ])
        if held:
            _logger.info('MLM: releasing %d held commissions', len(held))
            # action_approve may return a notification dict — ignore it in cron context
            for commission in held:
                try:
                    commission.action_approve()
                except Exception:
                    _logger.exception('MLM: auto-approve failed for commission %s', commission.name)

    # ── Static helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _generate_coupon_code():
        return 'AFF-' + ''.join(
            random.choices(string.ascii_uppercase + string.digits, k=8)
        )

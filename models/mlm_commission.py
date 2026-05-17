from odoo import models, fields, api


class MlmCommission(models.Model):
    """
    One record per commission earned.
    Auto-created when a referred sale order is confirmed.
    Inherits mail.thread so state changes are logged in the chatter.
    """
    _name = 'mlm.commission'
    _description = 'MLM Commission Record'
    _order = 'create_date desc'
    _rec_name = 'name'
    # mail.thread  → enables tracking= on fields and <chatter/> in views
    # mail.activity.mixin → enables activities (schedule call, reminder, etc.)
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string='Reference',
        readonly=True,
        copy=False,
        default='/',
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Affiliate / Earner',
        required=True,
        index=True,
        ondelete='restrict',
    )
    order_id = fields.Many2one(
        'sale.order',
        string='Sale Order',
        required=True,
        ondelete='cascade',
        index=True,
    )
    order_line_id = fields.Many2one(
        'sale.order.line',
        string='Order Line',
        ondelete='set null',
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        ondelete='set null',
    )
    buyer_partner_id = fields.Many2one(
        'res.partner',
        string='Buyer',
        ondelete='set null',
    )
    level = fields.Integer(
        string='MLM Level',
        required=True,
        help='1 = direct referrer, 2 = upline, 3 = upline-of-upline, etc.',
    )
    commission_type = fields.Selection(
        [('percent', 'Percentage (%)'), ('fixed', 'Fixed Amount')],
        string='Commission Type',
    )
    commission_value = fields.Float(
        string='Rate / Amount',
        digits=(16, 4),
    )
    amount = fields.Float(
        string='Commission Amount',
        required=True,
        digits=(16, 2),
    )
    # currency_id is populated via related so Monetary fields can display currency
    currency_id = fields.Many2one(
        'res.currency',
        related='order_id.currency_id',
        store=True,
        string='Currency',
    )
    state = fields.Selection(
        [
            ('pending', 'Pending'),
            ('approved', 'Approved'),
            ('paid', 'Paid'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='pending',
        index=True,
        tracking=True,   # safe now that we have mail.thread
    )
    payout_method = fields.Selection(
        [
            ('wallet', 'Wallet Credit'),
            ('bank', 'Bank Transfer'),
            ('discount', 'Discount Coupon'),
        ],
        string='Payout Method',
        default='wallet',
    )
    coupon_code = fields.Char(
        string='Coupon Code',
        readonly=True,
        copy=False,
    )
    note = fields.Text(string='Admin Notes')
    order_date = fields.Datetime(
        related='order_id.date_order',
        string='Order Date',
        store=True,
    )
    # Monetary field MUST declare currency_field explicitly
    order_amount = fields.Monetary(
        related='order_id.amount_total',
        string='Order Total',
        store=True,
        currency_field='currency_id',   # ← required, prevents crash on render
    )

    # ── ORM ──────────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == '/':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('mlm.commission') or '/'
                )
        return super().create(vals_list)

    # ── Button actions ────────────────────────────────────────────────────────

    def action_approve(self):
        for rec in self:
            if rec.state == 'pending':
                rec.state = 'approved'

    def action_pay(self):
        for rec in self:
            if rec.state == 'approved':
                rec.state = 'paid'
                if rec.payout_method == 'discount' and not rec.coupon_code:
                    rec.coupon_code = self._generate_coupon_code()

    def action_cancel(self):
        for rec in self:
            if rec.state in ('pending', 'approved'):
                rec.state = 'cancelled'

    def action_reset_to_pending(self):
        for rec in self:
            if rec.state == 'cancelled':
                rec.state = 'pending'

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _generate_coupon_code():
        import random
        import string
        chars = string.ascii_uppercase + string.digits
        return 'AFF-' + ''.join(random.choices(chars, k=8))

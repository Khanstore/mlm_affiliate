from odoo import models, fields, api


class MlmCommission(models.Model):
    _name = 'mlm.commission'
    _description = 'MLM Commission Record'
    _order = 'create_date desc'
    _rec_name = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Reference', readonly=True, copy=False, default='/')

    partner_id = fields.Many2one(
        'res.partner', string='Earner',
        required=True, index=True, ondelete='restrict',
    )
    is_admin_allocation = fields.Boolean(
        string='Admin Allocation', default=False,
        help='True when the upline level was empty and commission went to admin account.',
    )
    is_l1_split = fields.Boolean(
        string='L1 Split', default=False,
        help=(
            'True when the buyer already had an existing upline AND purchased '
            'through a different referrer\'s link. '
            'The Level-1 commission is shared equally between the referrer '
            'and the buyer\'s existing upline.'
        ),
    )
    # Who the other half of the L1 split went to (informational)
    split_partner_id = fields.Many2one(
        'res.partner', string='Split With',
        help='The other partner who received the other half of the L1 split.',
        ondelete='set null',
    )

    order_id = fields.Many2one(
        'sale.order', string='Sale Order',
        required=True, ondelete='cascade', index=True,
    )
    order_line_id = fields.Many2one(
        'sale.order.line', string='Order Line', ondelete='set null',
    )
    product_id = fields.Many2one(
        'product.product', string='Product', ondelete='set null',
    )
    buyer_partner_id = fields.Many2one(
        'res.partner', string='Buyer', ondelete='set null',
    )

    level = fields.Integer(
        string='MLM Level', required=True,
    )
    level_rate = fields.Float(
        string='Level Rate (%)', digits=(6, 2),
        help='The % of the total commission assigned to this level.',
    )
    total_commission = fields.Float(
        string='Total Commission Pot', digits=(16, 2),
        help='Total commission for this product line before level split.',
    )
    amount = fields.Float(
        string='Commission Amount', required=True, digits=(16, 2),
    )
    currency_id = fields.Many2one(
        'res.currency', related='order_id.currency_id',
        store=True, string='Currency',
    )
    state = fields.Selection(
        [('pending', 'Pending'), ('approved', 'Approved'),
         ('paid', 'Paid'), ('cancelled', 'Cancelled')],
        string='Status', default='pending', index=True, tracking=True,
    )
    payout_method = fields.Selection(
        [('wallet', 'Wallet Credit'), ('bank', 'Bank Transfer'),
         ('discount', 'Discount Coupon')],
        string='Payout Method', default='wallet',
    )
    coupon_code = fields.Char(string='Coupon Code', readonly=True, copy=False)
    note = fields.Text(string='Admin Notes')
    order_date = fields.Datetime(
        related='order_id.date_order', string='Order Date', store=True,
    )
    order_amount = fields.Monetary(
        related='order_id.amount_total',
        string='Order Total', store=True, currency_field='currency_id',
    )

    # ── ORM ───────────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == '/':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('mlm.commission') or '/'
                )
        return super().create(vals_list)

    # ── Buttons ───────────────────────────────────────────────────────────────

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

    @staticmethod
    def _generate_coupon_code():
        import random, string
        return 'AFF-' + ''.join(
            random.choices(string.ascii_uppercase + string.digits, k=8)
        )

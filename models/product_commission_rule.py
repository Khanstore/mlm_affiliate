from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ProductCommissionRule(models.Model):
    """
    Total commission for a product.  ONE record per product.

    The commission is the TOTAL pot for that product sale.
    How that pot is split across MLM levels is defined globally in
    mlm.level.rate — not here.

    Example:
        Product "Shirt" → 10% commission
        Sale price = 1 000 BDT  →  total pot = 100 BDT
        mlm.level.rate: L1=80%, L2=10%, L3=6%, L4=4%
        → L1 earns 80, L2 earns 10, L3 earns 6, L4 earns 4
          (empty levels → admin account)
    """
    _name = 'product.commission.rule'
    _description = 'MLM Product Commission Rule'
    _order = 'product_tmpl_id'
    _rec_name = 'rule_label'

    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product',
        required=True,
        ondelete='cascade',
        index=True,
    )
    commission_type = fields.Selection(
        [('percent', 'Percentage (%)'), ('fixed', 'Fixed Amount')],
        string='Commission Type',
        required=True,
        default='percent',
        help=(
            'Percentage: commission = value% of the order line subtotal.\n'
            'Fixed: commission = exact amount regardless of price.'
        ),
    )
    commission_value = fields.Float(
        string='Total Commission',
        required=True,
        digits=(16, 4),
        help=(
            'The TOTAL commission pot for this product per sale.\n'
            'This pot is distributed across MLM levels using the '
            'global Level Distribution Rates.'
        ),
    )
    active = fields.Boolean(default=True)
    rule_label = fields.Char(
        string='Rule Label',
        compute='_compute_rule_label',
        store=True,
    )

    # ── Computed ──────────────────────────────────────────────────────────────

    @api.depends('product_tmpl_id', 'commission_type', 'commission_value')
    def _compute_rule_label(self):
        for rule in self:
            pname = rule.product_tmpl_id.name or '?'
            val = (
                f"{rule.commission_value}%"
                if rule.commission_type == 'percent'
                else f"{rule.commission_value} (fixed)"
            )
            rule.rule_label = f"{pname}: {val} total"

    # ── Constraints ───────────────────────────────────────────────────────────

    @api.constrains('commission_value', 'commission_type')
    def _check_value(self):
        for rule in self:
            if rule.commission_value < 0:
                raise ValidationError('Commission value cannot be negative.')
            if rule.commission_type == 'percent' and rule.commission_value > 100:
                raise ValidationError('Percentage commission cannot exceed 100.')

    _sql_constraints = [
        (
            'unique_product',
            'UNIQUE(product_tmpl_id)',
            'A commission rule already exists for this product.',
        )
    ]

    # ── Business ─────────────────────────────────────────────────────────────

    def compute_total_commission(self, price_subtotal):
        """Return the TOTAL commission pot for a given order line subtotal."""
        self.ensure_one()
        if self.commission_type == 'percent':
            return round(price_subtotal * self.commission_value / 100, 2)
        return round(self.commission_value, 2)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    commission_rule_ids = fields.One2many(
        'product.commission.rule',
        'product_tmpl_id',
        string='Commission Rule',
    )
    has_commission = fields.Boolean(
        string='Has Commission Rule',
        compute='_compute_has_commission',
        store=True,
    )

    @api.depends('commission_rule_ids')
    def _compute_has_commission(self):
        for tmpl in self:
            tmpl.has_commission = bool(tmpl.commission_rule_ids)

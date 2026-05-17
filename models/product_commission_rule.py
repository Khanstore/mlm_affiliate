from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ProductCommissionRule(models.Model):
    """
    Commission rate per product per MLM level.
    One record = one level for one product.
    Add multiple records (Level 1, 2, 3 ...) via the product form tab.
    """
    _name = 'product.commission.rule'
    _description = 'MLM Product Commission Rule'
    _order = 'product_tmpl_id, level'
    # NOTE: do NOT use _rec_name = 'display_name' — display_name is reserved
    # in Odoo's BaseModel. We use 'rule_label' for our computed name.
    _rec_name = 'rule_label'

    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product',
        required=True,
        ondelete='cascade',
        index=True,
    )
    level = fields.Integer(
        string='MLM Level',
        required=True,
        default=1,
        help='Level 1 = direct referrer, Level 2 = their upline, etc.',
    )
    commission_type = fields.Selection(
        [('percent', 'Percentage (%)'), ('fixed', 'Fixed Amount')],
        string='Commission Type',
        required=True,
        default='percent',
    )
    commission_value = fields.Float(
        string='Value',
        required=True,
        digits=(16, 4),
        help='For Percentage: enter 10 for 10%.  For Fixed: enter the amount.',
    )
    active = fields.Boolean(default=True)

    # Computed label — NOT named display_name (that is reserved in BaseModel)
    rule_label = fields.Char(
        string='Rule Label',
        compute='_compute_rule_label',
        store=True,
    )

    # ── Computes ────────────────────────────────────────────────────────────

    @api.depends('product_tmpl_id', 'level', 'commission_type', 'commission_value')
    def _compute_rule_label(self):
        for rule in self:
            pname = rule.product_tmpl_id.name or '?'
            val = (
                f"{rule.commission_value}%"
                if rule.commission_type == 'percent'
                else f"{rule.commission_value} (fixed)"
            )
            rule.rule_label = f"{pname} — L{rule.level}: {val}"

    # ── Constraints ─────────────────────────────────────────────────────────

    @api.constrains('level')
    def _check_level(self):
        for rule in self:
            if rule.level < 1:
                raise ValidationError('MLM Level must be 1 or higher.')

    @api.constrains('commission_value', 'commission_type')
    def _check_value(self):
        for rule in self:
            if rule.commission_value < 0:
                raise ValidationError('Commission value cannot be negative.')
            if rule.commission_type == 'percent' and rule.commission_value > 100:
                raise ValidationError('Percentage commission cannot exceed 100.')

    _sql_constraints = [
        (
            'unique_product_level',
            'UNIQUE(product_tmpl_id, level)',
            'A commission rule already exists for this product at this level.',
        )
    ]

    # ── Business ─────────────────────────────────────────────────────────────

    def compute_commission(self, price_subtotal):
        """Return the commission amount for a given order line subtotal."""
        self.ensure_one()
        if self.commission_type == 'percent':
            return round(price_subtotal * self.commission_value / 100, 2)
        return round(self.commission_value, 2)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    commission_rule_ids = fields.One2many(
        'product.commission.rule',
        'product_tmpl_id',
        string='Commission Rules',
    )
    has_commission = fields.Boolean(
        string='Has Commission Rules',
        compute='_compute_has_commission',
        store=True,
    )

    @api.depends('commission_rule_ids')
    def _compute_has_commission(self):
        for tmpl in self:
            tmpl.has_commission = bool(tmpl.commission_rule_ids)

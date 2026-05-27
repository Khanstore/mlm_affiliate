from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ProductCommissionRule(models.Model):
    """
    Three-tier commission rule with optional pricelist targeting.

    Lookup priority (highest → lowest):
      ── Pricelist-specific rules (buyer is on that pricelist) ──
      1. Variant   + pricelist
      2. Template  + pricelist
      3. Category  + pricelist   (walks up the category tree)
      ── General / public rules (pricelist_id is empty) ──
      4. Variant   (no pricelist)
      5. Template  (no pricelist)
      6. Category  (no pricelist, walks up tree)

    Examples:
      • Public pricelist buyers        → uses rules with pricelist_id = empty
      • Reseller pricelist buyers      → uses rules with pricelist_id = Reseller PL
                                         (falls back to general if no reseller rule)
      • Any buyer with no match        → no commission
    """
    _name = 'product.commission.rule'
    _description = 'MLM Commission Rule'
    _order = 'sequence, id'
    _rec_name = 'rule_label'

    sequence = fields.Integer(string='Priority', default=10)

    rule_type = fields.Selection(
        [
            ('category', 'Product Category  (all products in category)'),
            ('template', 'Product  (all variants)'),
            ('variant',  'Specific Variant'),
        ],
        string='Apply To', required=True, default='template',
    )

    # ── Target ────────────────────────────────────────────────────────────────
    categ_id = fields.Many2one(
        'product.category', string='Product Category',
        index=True, ondelete='cascade',
    )
    product_tmpl_id = fields.Many2one(
        'product.template', string='Product (Template)',
        index=True, ondelete='cascade',
    )
    product_id = fields.Many2one(
        'product.product', string='Product Variant',
        index=True, ondelete='cascade',
    )

    # ── Pricelist scope ───────────────────────────────────────────────────────
    pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Pricelist',
        index=True,
        ondelete='cascade',
        help=(
            'Leave EMPTY → rule applies to public / default pricelist buyers '
            '(and as a fallback for any pricelist that has no specific rule).\n\n'
            'Set a pricelist → rule applies ONLY when the buyer\'s order uses '
            'that specific pricelist (e.g. Reseller, VIP, Wholesale).\n\n'
            'A pricelist-specific rule always overrides the general (empty) rule '
            'for that same product/category level.'
        ),
    )
    pricelist_label = fields.Char(
        string='Scope',
        compute='_compute_pricelist_label',
        store=True,
    )

    # ── Commission ────────────────────────────────────────────────────────────
    commission_type = fields.Selection(
        [('percent', 'Percentage (%)'), ('fixed', 'Fixed Amount')],
        string='Commission Type', required=True, default='percent',
    )
    commission_value = fields.Float(
        string='Total Commission', required=True, digits=(16, 4),
        help=(
            'Total commission pot per sale. '
            'Distributed across MLM levels via the global Level Distribution Rates.'
        ),
    )
    active = fields.Boolean(default=True)
    rule_label = fields.Char(compute='_compute_rule_label', store=True)

    # ── Onchange ──────────────────────────────────────────────────────────────

    @api.onchange('rule_type')
    def _onchange_rule_type(self):
        if self.rule_type == 'category':
            self.product_tmpl_id = False
            self.product_id = False
        elif self.rule_type == 'template':
            self.categ_id = False
            self.product_id = False
        elif self.rule_type == 'variant':
            self.categ_id = False
            self.product_tmpl_id = False

    # ── Computes ──────────────────────────────────────────────────────────────

    @api.depends('pricelist_id')
    def _compute_pricelist_label(self):
        for rule in self:
            rule.pricelist_label = (
                rule.pricelist_id.name if rule.pricelist_id else 'Public / All'
            )

    @api.depends('rule_type', 'categ_id', 'product_tmpl_id', 'product_id',
                 'pricelist_id', 'commission_type', 'commission_value')
    def _compute_rule_label(self):
        for rule in self:
            if rule.rule_type == 'category':
                target = rule.categ_id.complete_name or '?'
            elif rule.rule_type == 'template':
                target = rule.product_tmpl_id.name or '?'
            else:
                target = rule.product_id.display_name or '?'

            val = (
                f"{rule.commission_value}%"
                if rule.commission_type == 'percent'
                else f"{rule.commission_value} (fixed)"
            )
            pl = f" [{rule.pricelist_id.name}]" if rule.pricelist_id else " [Public]"
            rule.rule_label = f"[{rule.rule_type.title()}]{pl} {target}: {val}"

    # ── Constraints ───────────────────────────────────────────────────────────

    @api.constrains('rule_type', 'categ_id', 'product_tmpl_id', 'product_id')
    def _check_target_set(self):
        for rule in self:
            if rule.rule_type == 'category' and not rule.categ_id:
                raise ValidationError('Please select a Product Category.')
            if rule.rule_type == 'template' and not rule.product_tmpl_id:
                raise ValidationError('Please select a Product.')
            if rule.rule_type == 'variant' and not rule.product_id:
                raise ValidationError('Please select a Product Variant.')

    @api.constrains('commission_value', 'commission_type')
    def _check_value(self):
        for rule in self:
            if rule.commission_value < 0:
                raise ValidationError('Commission value cannot be negative.')
            if rule.commission_type == 'percent' and rule.commission_value > 100:
                raise ValidationError('Percentage cannot exceed 100%.')

    @api.constrains('rule_type', 'categ_id', 'product_tmpl_id',
                    'product_id', 'pricelist_id')
    def _check_unique(self):
        """One active rule per target + pricelist combination."""
        for rule in self:
            pl_id = rule.pricelist_id.id if rule.pricelist_id else False
            domain = [
                ('rule_type', '=', rule.rule_type),
                ('id', '!=', rule.id),
                ('active', '=', True),
            ]
            if pl_id:
                domain.append(('pricelist_id', '=', pl_id))
            else:
                domain.append(('pricelist_id', '=', False))

            if rule.rule_type == 'category' and rule.categ_id:
                domain.append(('categ_id', '=', rule.categ_id.id))
                dup_name = rule.categ_id.complete_name
            elif rule.rule_type == 'template' and rule.product_tmpl_id:
                domain.append(('product_tmpl_id', '=', rule.product_tmpl_id.id))
                dup_name = rule.product_tmpl_id.name
            elif rule.rule_type == 'variant' and rule.product_id:
                domain.append(('product_id', '=', rule.product_id.id))
                dup_name = rule.product_id.display_name
            else:
                continue

            if self.search(domain, limit=1):
                pl_label = rule.pricelist_id.name if rule.pricelist_id else 'Public'
                raise ValidationError(
                    f'A commission rule already exists for '
                    f'"{dup_name}" on pricelist "{pl_label}".'
                )

    # ── Business ─────────────────────────────────────────────────────────────

    def compute_total_commission(self, price_subtotal, qty=1.0):
        self.ensure_one()
        if self.commission_type == 'percent':
            # price_subtotal already = unit_price * qty, so percent is correct as-is
            return round(price_subtotal * self.commission_value / 100, 2)
        # Fixed: rate per unit × quantity ordered
        return round(self.commission_value * qty, 2)

    @api.model
    def find_rule_for_product(self, product, pricelist=None):
        """
        Find the best matching commission rule for a product variant.

        Priority:
          1-3. Pricelist-specific rules (variant → template → category)
          4-6. General / public rules    (variant → template → category)

        The pricelist-specific tier is checked first if `pricelist` is provided.
        General rules act as fallback for any pricelist without specific rules.
        """
        def _search(rule_type, target_domain, pl_id):
            """Helper: search active rule for one type+target+pricelist."""
            domain = [
                ('rule_type', '=', rule_type),
                ('active', '=', True),
            ]
            if pl_id:
                domain.append(('pricelist_id', '=', pl_id))
            else:
                domain.append(('pricelist_id', '=', False))
            domain += target_domain
            return self.search(domain, order='sequence', limit=1)

        pl_id = pricelist.id if pricelist else False

        # ── Tier 1: pricelist-specific ────────────────────────────────────────
        if pl_id:
            # 1. Variant + pricelist
            r = _search('variant', [('product_id', '=', product.id)], pl_id)
            if r:
                return r

            # 2. Template + pricelist
            r = _search('template',
                        [('product_tmpl_id', '=', product.product_tmpl_id.id)],
                        pl_id)
            if r:
                return r

            # 3. Category + pricelist (walk up tree)
            categ = product.categ_id
            while categ:
                r = _search('category', [('categ_id', '=', categ.id)], pl_id)
                if r:
                    return r
                categ = categ.parent_id

        # ── Tier 2: general / public rules (pricelist_id = False) ────────────
        # 4. Variant
        r = _search('variant', [('product_id', '=', product.id)], False)
        if r:
            return r

        # 5. Template
        r = _search('template',
                    [('product_tmpl_id', '=', product.product_tmpl_id.id)],
                    False)
        if r:
            return r

        # 6. Category (walk up tree)
        categ = product.categ_id
        while categ:
            r = _search('category', [('categ_id', '=', categ.id)], False)
            if r:
                return r
            categ = categ.parent_id

        return self.browse()   # no rule found


# ─────────────────────────────────────────────────────────────────────────────
# product.template helpers
# ─────────────────────────────────────────────────────────────────────────────

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    tmpl_commission_ids = fields.One2many(
        'product.commission.rule', 'product_tmpl_id',
        string='Template Commission Rules',
        domain=[('rule_type', '=', 'template')],
    )
    variant_commission_ids = fields.One2many(
        'product.commission.rule', 'product_tmpl_id',
        string='Variant Commission Rules',
        domain=[('rule_type', '=', 'variant')],
    )
    has_any_commission = fields.Boolean(
        compute='_compute_has_any_commission', store=True,
    )

    @api.depends('tmpl_commission_ids', 'variant_commission_ids')
    def _compute_has_any_commission(self):
        for t in self:
            t.has_any_commission = bool(
                t.tmpl_commission_ids or t.variant_commission_ids
            )


# ─────────────────────────────────────────────────────────────────────────────
# product.category helper
# ─────────────────────────────────────────────────────────────────────────────

class ProductCategory(models.Model):
    _inherit = 'product.category'

    commission_rule_ids = fields.One2many(
        'product.commission.rule', 'categ_id',
        string='Commission Rules',
        domain=[('rule_type', '=', 'category')],
    )
    has_commission = fields.Boolean(
        compute='_compute_has_commission', store=True,
    )

    @api.depends('commission_rule_ids')
    def _compute_has_commission(self):
        for cat in self:
            cat.has_commission = bool(cat.commission_rule_ids)

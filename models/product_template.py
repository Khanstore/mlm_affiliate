from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = "product.template"

    mlm_commission_line_ids = fields.One2many(
        "mlm.product.commission",
        "product_tmpl_id",
        string="MLM Commission Rules",
    )
    mlm_commission_summary = fields.Char(
        string="MLM Commission",
        compute="_compute_mlm_commission_summary",
    )
    mlm_loyalty_enabled = fields.Boolean(string="Reward MLM Commission as Loyalty")
    mlm_loyalty_program_id = fields.Many2one(
        "loyalty.program",
        string="MLM Loyalty Program",
        domain=[("program_type", "in", ("loyalty", "ewallet"))],
        help="Loyalty or eWallet program used when MLM commissions are credited as points.",
    )
    mlm_loyalty_points_per_currency = fields.Float(
        string="Loyalty Points per Commission Amount",
        default=1.0,
        help="Example: 1.0 means a commission amount of 100 creates 100 loyalty points.",
    )

    def _compute_mlm_commission_summary(self):
        for product in self:
            lines = product.mlm_commission_line_ids.filtered(
                lambda line: line.active and line.commission_percent
            ).sorted("level")
            product.mlm_commission_summary = ", ".join(
                _("L%(level)s: %(percent).2f%%")
                % {
                    "level": line.level,
                    "percent": line.commission_percent,
                }
                for line in lines
            )

    @api.constrains(
        "mlm_loyalty_enabled",
        "mlm_loyalty_program_id",
        "mlm_loyalty_points_per_currency",
    )
    def _check_mlm_loyalty_settings(self):
        for product in self:
            if not product.mlm_loyalty_enabled:
                continue
            if not product.mlm_loyalty_program_id:
                raise ValidationError(_("Select an MLM loyalty program for this product."))
            if product.mlm_loyalty_points_per_currency <= 0:
                raise ValidationError(_("Loyalty points per commission amount must be greater than zero."))


class MLMProductCommission(models.Model):
    _name = "mlm.product.commission"
    _description = "Product MLM Commission Rule"
    _order = "product_tmpl_id, level"

    product_tmpl_id = fields.Many2one(
        "product.template",
        string="Product",
        required=True,
        index=True,
        ondelete="cascade",
    )
    level = fields.Integer(required=True, default=1)
    commission_percent = fields.Float(string="Commission (%)", digits="Discount")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "product_level_unique",
            "unique(product_tmpl_id, level)",
            "Each product can have only one MLM commission rule per level.",
        ),
        (
            "level_between_one_and_four",
            "CHECK(level >= 1 AND level <= 4)",
            "The MLM commission level must be between 1 and 4.",
        ),
        (
            "commission_percent_range",
            "CHECK(commission_percent >= 0 AND commission_percent <= 100)",
            "The MLM commission percentage must be between 0 and 100.",
        ),
    ]

    @api.constrains("level", "commission_percent")
    def _check_values(self):
        for line in self:
            if line.level < 1 or line.level > 4:
                raise ValidationError(_("MLM commission levels must be between 1 and 4."))
            if line.commission_percent < 0 or line.commission_percent > 100:
                raise ValidationError(_("MLM commission percentage must be between 0 and 100."))

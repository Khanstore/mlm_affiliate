from odoo import models, fields, api
from odoo.exceptions import ValidationError


class MlmLevelRate(models.Model):
    """
    Global distribution rates per MLM level.

    Each level gets a percentage of the product's total commission pot.
    Rates do NOT have to sum to 100% — any unallocated remainder simply
    stays with the company.  This makes it easy to add/remove levels
    without having to rebalance every other row simultaneously.

    Example:  Level 1 → 60%,  Level 2 → 20%,  Level 3 → 10%
              (remaining 10% is not paid out)
    """
    _name = 'mlm.level.rate'
    _description = 'MLM Level Distribution Rate'
    _order = 'level'
    _rec_name = 'level_label'

    level = fields.Integer(
        string='Level', required=True,
        help='1 = direct referrer, 2 = their upline, etc.')
    level_label = fields.Char(
        string='Label', compute='_compute_level_label', store=True)
    description = fields.Char(
        string='Description',
        help='e.g. "Direct Referrer", "Level 2 Upline"')
    rate = fields.Float(
        string='Rate (%)', required=True, digits=(6, 2),
        help='Percentage of the product total commission that goes to this level.')
    active = fields.Boolean(default=True)

    # Computed running total — shown in the list footer, never enforced
    total_rate = fields.Float(
        string='Total of All Active Rates (%)',
        compute='_compute_total_rate', digits=(6, 2))

    @api.depends('level', 'rate')
    def _compute_level_label(self):
        for rec in self:
            rec.level_label = f'Level {rec.level} ({rec.rate}%)'

    @api.depends()  # recomputes when any record in the set changes
    def _compute_total_rate(self):
        all_active = self.sudo().search([('active', '=', True)])
        total = sum(all_active.mapped('rate'))
        for rec in self:
            rec.total_rate = total

    @api.constrains('level')
    def _check_level(self):
        for rec in self:
            if rec.level < 1:
                raise ValidationError('Level must be 1 or higher.')

    @api.constrains('rate')
    def _check_rate(self):
        for rec in self:
            if not (0 < rec.rate <= 100):
                raise ValidationError('Rate must be between 0 and 100.')

    _sql_constraints = [
        ('unique_level', 'UNIQUE(level)',
         'A rate already exists for this level.'),
    ]

    @api.model
    def get_total_rate(self):
        """Return sum of all active rates."""
        rates = self.search([('active', '=', True)])
        return sum(rates.mapped('rate'))

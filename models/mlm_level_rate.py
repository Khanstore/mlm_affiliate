from odoo import models, fields, api
from odoo.exceptions import ValidationError


class MlmLevelRate(models.Model):
    """
    Global distribution rates per MLM level.
    Example:  Level 1 → 80%,  Level 2 → 10%,  Level 3 → 6%,  Level 4 → 4%

    FIX: Added @api.constrains that warns when active rates no longer sum to 100%.
    """
    _name = 'mlm.level.rate'
    _description = 'MLM Level Distribution Rate'
    _order = 'level'
    _rec_name = 'level_label'

    level = fields.Integer(string='Level', required=True,
        help='1 = direct referrer, 2 = their upline, etc.')
    level_label = fields.Char(string='Label', compute='_compute_level_label', store=True)
    description = fields.Char(string='Description',
        help='e.g. "Direct Referrer", "Level 2 Upline"')
    rate = fields.Float(string='Rate (%)', required=True, digits=(6, 2),
        help='Percentage of the product total commission that goes to this level.')
    active = fields.Boolean(default=True)

    @api.depends('level', 'rate')
    def _compute_level_label(self):
        for rec in self:
            rec.level_label = f'Level {rec.level} ({rec.rate}%)'

    @api.constrains('level')
    def _check_level(self):
        for rec in self:
            if rec.level < 1:
                raise ValidationError('Level must be 1 or higher.')

    @api.constrains('rate')
    def _check_rate(self):
        for rec in self:
            if rec.rate < 0 or rec.rate > 100:
                raise ValidationError('Rate must be between 0 and 100.')

    # FIX: validate that all active rates sum to 100 (±0.01 tolerance)
    @api.constrains('rate', 'active')
    def _check_total_rate(self):
        total = self.get_total_rate()
        if abs(total - 100.0) > 0.01:
            raise ValidationError(
                f'Active level rates must sum to exactly 100%%. '
                f'Current total: {total:.2f}%%. '
                f'Please adjust rates before saving.'
            )

    _sql_constraints = [
        ('unique_level', 'UNIQUE(level)', 'A rate already exists for this level.'),
    ]

    @api.model
    def get_total_rate(self):
        """Return sum of all active rates (must equal 100)."""
        rates = self.search([('active', '=', True)])
        return sum(rates.mapped('rate'))

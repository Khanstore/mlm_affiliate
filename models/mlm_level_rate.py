from odoo import models, fields, api
from odoo.exceptions import ValidationError


class MlmLevelRate(models.Model):
    """
    Global distribution rates per MLM level.

    Example setup:
        Level 1 → 80%   (direct referrer)
        Level 2 → 10%   (their upline)
        Level 3 →  6%
        Level 4 →  4%
        Total   = 100%

    When an order is confirmed:
      - The product's total commission is calculated.
      - That total is split according to these rates.
      - If NO partner exists at a given level in the upline chain,
        that portion is credited to the configured Admin Account instead.
    """
    _name = 'mlm.level.rate'
    _description = 'MLM Level Distribution Rate'
    _order = 'level'
    _rec_name = 'level_label'

    level = fields.Integer(
        string='Level',
        required=True,
        help='1 = direct referrer, 2 = their upline, 3 = next upline, etc.',
    )
    level_label = fields.Char(
        string='Label',
        compute='_compute_level_label',
        store=True,
    )
    description = fields.Char(
        string='Description',
        help='e.g. Direct Referrer, Upline Level 2 …',
    )
    rate = fields.Float(
        string='Rate (%)',
        required=True,
        digits=(6, 2),
        help='Percentage of the product total commission assigned to this level.',
    )
    active = fields.Boolean(default=True)

    # ── Computed ──────────────────────────────────────────────────────────────

    @api.depends('level', 'rate')
    def _compute_level_label(self):
        for rec in self:
            rec.level_label = f'Level {rec.level}  ({rec.rate} %)'

    # ── Constraints ───────────────────────────────────────────────────────────

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

    _sql_constraints = [
        ('unique_level', 'UNIQUE(level)', 'A rate already exists for this level.'),
    ]

    # ── Helpers ───────────────────────────────────────────────────────────────

    @api.model
    def total_rate(self):
        """Sum of all active rates — should equal 100."""
        return sum(self.search([('active', '=', True)]).mapped('rate'))

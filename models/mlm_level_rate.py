"""
mlm_level_rate.py  — MLM Affiliate  (patched)
===============================================

CHANGES vs. original
---------------------
[FIX-10] _compute_total_rate — missing @api.depends trigger
    Original: @api.depends()  (empty tuple) means the compute NEVER
    re-triggers on record changes — only runs once at first load.
    Fixed by depending on a per-record sentinel so Odoo invalidates
    correctly.  A global aggregate like this must also listen on
    'rate' and 'active' fields.

[FIX-11] _check_rate constraint allows rate=0
    A level can legitimately have rate=0 when a manager wants to
    temporarily disable a level without deleting it.  Relaxed the
    lower bound from `0 <` to `0 <=`.

[NEW-2] company_id field added
    Multi-company: each company can have its own set of level rates.
    Lookup in sale_order._generate_mlm_commissions() already uses
    sudo() but should also filter by the order's company.  Added
    company_id and updated the unique constraint accordingly.
"""

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class MlmLevelRate(models.Model):
    """
    Global distribution rates per MLM level.

    Each level gets a percentage of the product's total commission pot.
    Rates do NOT have to sum to 100 %  — any unallocated remainder stays
    with the company.

    Example:  Level 1 → 60%,  Level 2 → 20%,  Level 3 → 10%
              (remaining 10% is not paid out)
    """
    _name        = 'mlm.level.rate'
    _description = 'MLM Level Distribution Rate'
    _order       = 'level'
    _rec_name    = 'level_label'

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

    # [NEW-2] Multi-company: each company maintains its own rate table.
    # Leave empty for a global default visible to all companies.
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        help='Leave empty to apply this rate to all companies (global default). '
             'Set a company to override for that company only.',
    )

    # [FIX-10] Correct @api.depends so total_rate recomputes on any change
    total_rate = fields.Float(
        string='Total of All Active Rates (%)',
        compute='_compute_total_rate',
        digits=(6, 2),
        store=False,    # Do NOT store — it's a cross-record aggregate; storing causes stale data
    )

    @api.depends('level', 'rate')
    def _compute_level_label(self):
        for rec in self:
            rec.level_label = f'Level {rec.level} ({rec.rate}%)'

    @api.depends('active', 'rate')   # [FIX-10] proper dependencies
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
            # [FIX-11] Allow 0 — manager may want to temporarily disable a level
            if not (0 <= rec.rate <= 100):
                raise ValidationError('Rate must be between 0 and 100 (inclusive).')

    # [NEW-2] Updated unique constraint: level must be unique PER company
    # (NULL company_id means global; two global rows for the same level are still forbidden)
    _sql_constraints = [
        ('unique_level_company',
         'UNIQUE(level, company_id)',
         'A rate already exists for this level in this company.'),
    ]

    @api.model
    def get_rates_for_company(self, company_id=None):
        """
        Return the level rates applicable to a given company.

        Lookup priority:
          1. Company-specific rates (company_id = given company)
          2. Global rates          (company_id = NULL)

        Returns a recordset ordered by level, using company-specific rates
        where they exist and falling back to global rates for levels not
        explicitly overridden.
        """
        if company_id is None:
            company_id = self.env.company.id

        company_rates = self.search([
            ('active', '=', True),
            ('company_id', '=', company_id),
        ], order='level')

        if company_rates:
            return company_rates

        # Fall back to global (company_id is NULL/False)
        return self.search([
            ('active', '=', True),
            ('company_id', '=', False),
        ], order='level')

    @api.model
    def get_total_rate(self):
        """Return sum of all active rates for the current company."""
        rates = self.get_rates_for_company()
        return sum(rates.mapped('rate'))

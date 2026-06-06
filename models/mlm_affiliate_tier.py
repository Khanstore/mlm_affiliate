"""
mlm_affiliate_tier.py  — MLM Affiliate  (patched)
==================================================

CHANGES vs. original
---------------------
[FIX-13] N+1 in _compute_partner_count
    Original: called search_count() once PER tier record.
    Fixed with a single read_group() that counts all partners grouped by
    tier_id in one SQL query.
"""

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class MlmAffiliateTier(models.Model):
    _name        = 'mlm.affiliate.tier'
    _description = 'Affiliate Tier'
    _order       = 'min_earned'
    _rec_name    = 'name'

    name        = fields.Char(string='Tier Name', required=True, translate=True)
    description = fields.Text(string='Description')
    min_earned  = fields.Float(
        string='Min. Total Earned (Lifetime)',
        required=True, default=0.0,
        help='Minimum cumulative commission earned for a partner to reach this tier.',
    )
    min_referrals = fields.Integer(
        string='Min. Direct Referrals',
        default=0,
        help='Minimum number of direct referrals required alongside the earning threshold.',
    )
    commission_multiplier = fields.Float(
        string='Commission Multiplier',
        default=1.0, digits=(6, 3),
        help='All commissions earned by partners at this tier are multiplied by this factor. '
             '1.0 = no bonus.',
    )
    color  = fields.Integer(string='Colour Index')
    active = fields.Boolean(default=True)

    partner_count = fields.Integer(
        compute='_compute_partner_count',
        string='Affiliates in Tier',
    )

    def _compute_partner_count(self):
        """
        [FIX-13] Single read_group replaces one search_count per tier.
        """
        if not self.ids:
            for tier in self:
                tier.partner_count = 0
            return
        groups = self.env['res.partner'].sudo().read_group(
            domain=[('tier_id', 'in', self.ids)],
            fields=['tier_id'],
            groupby=['tier_id'],
        )
        count_map = {g['tier_id'][0]: g['tier_id_count'] for g in groups}
        for tier in self:
            tier.partner_count = count_map.get(tier.id, 0)

    @api.constrains('min_earned', 'commission_multiplier')
    def _check_values(self):
        for rec in self:
            if rec.min_earned < 0:
                raise ValidationError('Minimum earned must be 0 or greater.')
            if rec.commission_multiplier <= 0:
                raise ValidationError('Commission multiplier must be a positive number.')

    _sql_constraints = [
        ('unique_name', 'UNIQUE(name)', 'A tier with this name already exists.'),
    ]

    def action_view_tier_partners(self):
        self.ensure_one()
        return {
            'type':      'ir.actions.act_window',
            'name':      'Affiliates in %s' % self.name,
            'res_model': 'res.partner',
            'view_mode': 'list,form',
            'domain':    [('tier_id', '=', self.id)],
            'context':   {'default_tier_id': self.id, 'default_is_affiliate': True},
        }

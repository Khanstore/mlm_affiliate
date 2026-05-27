from odoo import models, fields, api
from odoo.exceptions import ValidationError


class MlmAffiliateTier(models.Model):
    """
    Named affiliate tiers (Bronze, Silver, Gold, …).
    Partners are promoted automatically based on total earnings and/or
    direct referral count.  Each tier can optionally carry a commission
    multiplier that is applied by the commission engine.
    """
    _name = 'mlm.affiliate.tier'
    _description = 'Affiliate Tier'
    _order = 'min_earned'
    _rec_name = 'name'

    name = fields.Char(string='Tier Name', required=True, translate=True)
    description = fields.Text(string='Description')
    min_earned = fields.Float(
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
    color = fields.Integer(string='Colour Index')
    active = fields.Boolean(default=True)

    partner_count = fields.Integer(
        compute='_compute_partner_count',
        string='Affiliates in Tier',
    )

    def _compute_partner_count(self):
        for tier in self:
            tier.partner_count = self.env['res.partner'].search_count(
                [('tier_id', '=', tier.id)]
            )

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
            'type': 'ir.actions.act_window',
            'name': 'Affiliates in %s' % self.name,
            'res_model': 'res.partner',
            'view_mode': 'list,form',
            'domain': [('tier_id', '=', self.id)],
            'context': {'default_tier_id': self.id, 'default_is_affiliate': True},
        }

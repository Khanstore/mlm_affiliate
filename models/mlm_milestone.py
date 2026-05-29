from odoo import models, fields, api
from odoo.exceptions import ValidationError


class MlmMilestone(models.Model):
    """
    One-time bonus commissions when an affiliate crosses a threshold.
    Checked automatically after every tier update (action_update_tier).
    """
    _name = 'mlm.milestone'
    _description = 'MLM Milestone Bonus'
    _order = 'min_earned'

    name = fields.Char(string='Milestone Name', required=True)
    min_earned = fields.Float(string='Min. Total Earned', default=0.0,
        help='Award this bonus once the affiliate\'s lifetime earnings reach this amount.')
    min_referrals = fields.Integer(string='Min. Direct Referrals', default=0)
    bonus_amount = fields.Float(string='Bonus Amount', required=True, digits=(16, 2))
    active = fields.Boolean(default=True)
    note = fields.Text(string='Description shown to affiliate')

    @api.constrains('bonus_amount')
    def _check_bonus(self):
        for rec in self:
            if rec.bonus_amount <= 0:
                raise ValidationError('Bonus amount must be positive.')


class ResPartnerMilestone(models.Model):
    """Tracks which milestones a partner has already received."""
    _name = 'mlm.partner.milestone'
    _description = 'Partner Milestone Award'

    partner_id = fields.Many2one('res.partner', required=True, index=True, ondelete='cascade')
    milestone_id = fields.Many2one('mlm.milestone', required=True, ondelete='cascade')
    awarded_date = fields.Date(string='Awarded Date')
    commission_id = fields.Many2one('mlm.commission', string='Bonus Commission', readonly=True)

    _sql_constraints = [
        ('unique_partner_milestone', 'UNIQUE(partner_id, milestone_id)',
         'This milestone has already been awarded to this affiliate.'),
    ]

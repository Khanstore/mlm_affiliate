from odoo import models, fields, api
from odoo.exceptions import ValidationError


class MlmCampaign(models.Model):
    """
    Affiliate-specific promo campaigns.
    An affiliate can have an active campaign that boosts their commission
    rate by a multiplier for a defined date range.
    Optionally a buyer-facing promo code gives the buyer a discount.
    """
    _name = 'mlm.campaign'
    _description = 'MLM Affiliate Campaign'
    _order = 'date_start desc'

    name = fields.Char(string='Campaign Name', required=True)
    partner_id = fields.Many2one('res.partner', string='Affiliate',
        required=True, index=True, domain="[('is_affiliate','=',True)]")
    date_start = fields.Date(string='Start Date', required=True)
    date_end = fields.Date(string='End Date', required=True)
    commission_multiplier = fields.Float(
        string='Commission Multiplier', default=1.5, digits=(6, 3),
        help='All commissions earned by this affiliate during the campaign are '
             'multiplied by this factor. 1.5 = 50% bonus.')
    promo_code = fields.Char(string='Buyer Promo Code', copy=False,
        help='Optional discount code to give buyers. Not yet linked to sale discounts '
             'automatically — use as a marketing code.')
    active = fields.Boolean(default=True)
    note = fields.Text(string='Notes')

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_end < rec.date_start:
                raise ValidationError('End date must be after start date.')

    @api.constrains('commission_multiplier')
    def _check_multiplier(self):
        for rec in self:
            if rec.commission_multiplier <= 0:
                raise ValidationError('Commission multiplier must be positive.')

    def get_active_campaign(self, partner_id):
        """Return the active campaign for a partner on today's date, or empty."""
        from odoo.fields import Date
        today = Date.today()
        return self.search([
            ('partner_id', '=', partner_id),
            ('active', '=', True),
            ('date_start', '<=', today),
            ('date_end', '>=', today),
        ], limit=1)

import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MlmPayoutRequest(models.Model):
    """
    Affiliate-initiated payout request.
    Affiliates submit via the portal; admin reviews and approves.
    On approval the linked approved commissions are marked as paid.
    """
    _name = 'mlm.payout.request'
    _description = 'MLM Payout Request'
    _order = 'create_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Reference', readonly=True, copy=False, default='/')
    partner_id = fields.Many2one('res.partner', string='Affiliate',
        required=True, index=True, ondelete='restrict')
    amount_requested = fields.Float(string='Amount Requested', digits=(16, 2), required=True)
    payout_method = fields.Selection(
        [('wallet', 'Wallet Credit'), ('bank', 'Bank Transfer'), ('discount', 'Discount Coupon')],
        string='Payout Method', required=True, default='bank')
    bank_account = fields.Char(string='Bank / Wallet Account',
        help='IBAN or mobile wallet number for this payout.')
    note = fields.Text(string='Affiliate Note')
    admin_note = fields.Text(string='Admin Note')
    state = fields.Selection(
        [('draft', 'Submitted'), ('approved', 'Approved'),
         ('paid', 'Paid'), ('rejected', 'Rejected')],
        string='Status', default='draft', index=True, tracking=True)
    commission_ids = fields.Many2many(
        'mlm.commission', 'mlm_payout_request_commission_rel',
        'request_id', 'commission_id',
        string='Commissions Included',
        domain="[('partner_id', '=', partner_id), ('state', '=', 'approved')]")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == '/':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('mlm.payout.request') or '/'
                )
        return super().create(vals_list)

    def action_approve(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError('Only submitted requests can be approved.')
            rec.state = 'approved'
            rec.message_post(body='Payout request approved.', subtype_xmlid='mail.mt_note')

    def action_pay(self):
        for rec in self:
            if rec.state != 'approved':
                raise UserError('Only approved requests can be marked as paid.')
            rec.commission_ids.filtered(lambda c: c.state == 'approved').action_pay()
            rec.state = 'paid'
            rec.message_post(body='Payout request marked as paid.', subtype_xmlid='mail.mt_note')

    def action_reject(self):
        for rec in self:
            if rec.state in ('paid',):
                raise UserError('Cannot reject a paid request.')
            rec.state = 'rejected'
            rec.message_post(body='Payout request rejected.', subtype_xmlid='mail.mt_note')

import logging
from odoo import models

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    """
    Auto-approve pending MLM commissions when the linked invoice is paid.

    Trigger: whenever an invoice's payment_state transitions to
    'in_payment' or 'paid'. Both states mean real money has moved
    (the difference is only whether bank reconciliation is done), so we
    approve commissions at the earlier of the two to keep the workflow
    responsive.
    """
    _inherit = 'account.move'

    _PAID_STATES = frozenset({'in_payment', 'paid'})

    def write(self, vals):
        moves_to_approve = self.env['account.move']

        if 'payment_state' in vals:
            new_payment_state = vals['payment_state']
            moves_to_approve = self.filtered(
                lambda m: (
                    m.move_type in ('out_invoice', 'out_refund')
                    and m.payment_state not in self._PAID_STATES
                    and new_payment_state in self._PAID_STATES
                )
            )

        res = super().write(vals)

        if moves_to_approve:
            moves_to_approve._approve_related_commissions()

        return res

    def _approve_related_commissions(self):
        """
        Find all pending commissions linked to this invoice's sale orders,
        approve them (firing email notifications), then trigger tier updates
        for every affected affiliate.
        """
        Commission = self.env['mlm.commission'].sudo()

        for move in self:
            sale_orders = move.mapped('invoice_line_ids.sale_line_ids.order_id')
            if not sale_orders:
                continue

            pending_commissions = Commission.search([
                ('order_id', 'in', sale_orders.ids),
                ('state', '=', 'pending'),
            ])

            if not pending_commissions:
                continue

            # Use action_approve() so email notifications fire properly
            pending_commissions.action_approve()

            # Collect unique earners and update their tiers
            earners = pending_commissions.mapped('partner_id')
            try:
                earners.action_update_tier()
            except Exception:
                _logger.exception("MLM: tier update failed after payment %s", move.name)

            # Post a chatter note on each affected sale order
            for order in sale_orders:
                order_comms = pending_commissions.filtered(lambda c: c.order_id == order)
                if order_comms:
                    names = ', '.join(order_comms.mapped('partner_id.name'))
                    order.message_post(
                        body=(
                            f"✅ {len(order_comms)} commission(s) automatically approved "
                            f"after payment validation of <b>{move.name}</b>.<br/>"
                            f"Earner(s): {names}"
                        ),
                        subtype_xmlid='mail.mt_note',
                    )

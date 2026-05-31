import logging
from odoo import models

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    """
    Auto-approve pending MLM commissions when the linked invoice is paid.
    Also handles refund clawback: when a credit note is validated,
    cancel any approved/pending commissions on the originating sale orders.
    """
    _inherit = 'account.move'

    _PAID_STATES = frozenset({'in_payment', 'paid'})

    def write(self, vals):
        # Capture pre-write payment states for comparison after write
        # (payment_state is computed in Odoo 18 — not always in vals)
        pre_states = {}
        if 'payment_state' in vals or True:
            pre_states = {m.id: m.payment_state for m in self}

        res = super().write(vals)

        moves_to_approve = self.env['account.move']
        moves_to_clawback = self.env['account.move']

        for move in self:
            old_state = pre_states.get(move.id, '')
            new_state = move.payment_state
            if old_state == new_state or new_state not in self._PAID_STATES:
                continue
            if move.move_type == 'out_invoice':
                moves_to_approve |= move
            elif move.move_type == 'out_refund':
                moves_to_clawback |= move

        if moves_to_approve:
            moves_to_approve._approve_related_commissions()
        if moves_to_clawback:
            moves_to_clawback._clawback_related_commissions()

        return res

    def _invoice_paid_hook(self):
        """Odoo 18 calls this explicitly when an invoice transitions to paid.
        This is the reliable hook — use it as a second safety net."""
        res = super()._invoice_paid_hook()
        invoices = self.filtered(
            lambda m: m.move_type == 'out_invoice'
            and m.payment_state in self._PAID_STATES
        )
        if invoices:
            invoices._approve_related_commissions()
        return res

    def _approve_related_commissions(self):
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

            pending_commissions.action_approve()

            earners = pending_commissions.mapped('partner_id')
            try:
                earners.action_update_tier()
            except Exception:
                _logger.exception('MLM: tier update failed after payment %s', move.name)

            for order in sale_orders:
                order_comms = pending_commissions.filtered(lambda c: c.order_id == order)
                if order_comms:
                    names = ', '.join(order_comms.mapped('partner_id.name'))
                    order.message_post(
                        body=(
                            f'✅ {len(order_comms)} commission(s) automatically approved '
                            f'after payment validation of <b>{move.name}</b>.<br/>'
                            f'Earner(s): {names}'
                        ),
                        subtype_xmlid='mail.mt_note',
                    )

    def _clawback_related_commissions(self):
        """Cancel pending/approved commissions when a refund is validated."""
        Commission = self.env['mlm.commission'].sudo()

        for move in self:
            # A credit note links back to the original invoice via reversed_entry_id
            original_invoice = move.reversed_entry_id
            if not original_invoice:
                continue
            sale_orders = original_invoice.mapped('invoice_line_ids.sale_line_ids.order_id')
            if not sale_orders:
                continue

            clawback_commissions = Commission.search([
                ('order_id', 'in', sale_orders.ids),
                ('state', 'in', ('pending', 'approved')),
            ])

            if not clawback_commissions:
                continue

            clawback_commissions.action_cancel()

            for order in sale_orders:
                order_comms = clawback_commissions.filtered(lambda c: c.order_id == order)
                if order_comms:
                    order.message_post(
                        body=(
                            f'↩️ {len(order_comms)} commission(s) cancelled due to '
                            f'refund <b>{move.name}</b>.'
                        ),
                        subtype_xmlid='mail.mt_note',
                    )

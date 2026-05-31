import logging
from odoo import models

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    """
    Hook into online payment (Stripe, PayPal, etc.) confirmation.
    When a transaction is confirmed as 'done', re-protect the wallet
    discount line price_unit which Odoo's payment flow may reset.
    Also ensures wallet_amount_used is preserved through payment processing.
    """
    _inherit = 'payment.transaction'

    def _post_process(self):
        """Called by Odoo after a successful online payment."""
        res = super()._post_process()
        for tx in self.filtered(lambda t: t.state == 'done' and t.sale_order_ids):
            for order in tx.sale_order_ids:
                if order.wallet_amount_used > 0:
                    try:
                        order._mlm_reapply_wallet_line_sql()
                    except Exception:
                        _logger.exception(
                            'MLM: failed to reapply wallet line after payment tx %s', tx.reference)
        return res

    def _set_done(self):
        """Fallback hook — called when transaction transitions to done state."""
        res = super()._set_done()
        for tx in self.filtered(lambda t: t.sale_order_ids):
            for order in tx.sale_order_ids:
                if order.wallet_amount_used > 0:
                    try:
                        order._mlm_reapply_wallet_line_sql()
                    except Exception:
                        _logger.exception(
                            'MLM: _set_done wallet reapply failed for order %s', order.name)
        return res

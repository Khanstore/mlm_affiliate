"""
Pre-migration 2.3.0
1. Reset the portal_affiliate_dashboard template so the XML recreates it clean.
   (Odoo marks customised views as noupdate — wiping the ir.ui.view record forces
    a fresh write from the module XML on the next load.)
2. Ensure the wallet_discount_product_id system param exists placeholder so the
   post-install hook can create the product if missing.
"""
import logging
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # ── 1. Reset stale portal template ───────────────────────────────────────
    cr.execute("""
        DELETE FROM ir_ui_view
        WHERE key = 'mlm_affiliate.portal_affiliate_dashboard'
           OR (model = '' AND name = 'Affiliate Dashboard'
               AND type = 'qweb')
    """)
    deleted = cr.rowcount
    _logger.info("MLM migrate 2.3.0: removed %d stale portal_affiliate_dashboard view(s)", deleted)

    # ── 2. Ensure wallet_amount_used column exists ────────────────────────────
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name='sale_order' AND column_name='wallet_amount_used'
    """)
    if not cr.fetchone():
        cr.execute(
            "ALTER TABLE sale_order ADD COLUMN wallet_amount_used NUMERIC(16,2) DEFAULT 0.0"
        )
        _logger.info("MLM migrate 2.3.0: added sale_order.wallet_amount_used column")

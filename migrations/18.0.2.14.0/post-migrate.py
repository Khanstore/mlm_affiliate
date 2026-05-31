"""
Migration 18.0.2.4.0 (post) — Invalidate cached portal template
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Touch our views so Odoo reloads them from disk
    cr.execute("""
        UPDATE ir_ui_view
        SET write_date = NOW()
        WHERE key LIKE 'mlm_affiliate.portal_affiliate%'
           OR key LIKE 'mlm_affiliate.cart_wallet%'
           OR key LIKE 'mlm_affiliate.checkout_wallet%'
    """)
    _logger.info('MLM migration post: touched %d view(s) for reload', cr.rowcount)

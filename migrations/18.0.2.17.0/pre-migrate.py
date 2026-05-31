"""
Migration 18.0.2.6.0 — Fix wallet discount lines using Odoo 18 correct tables.

Confirmed Odoo 18 facts from server log:
- price_reduce column does NOT exist on sale_order_line
- tax relation table is account_tax_sale_order_line_rel (not account_tax_sale_order_line_rel)
"""
import logging
_logger = logging.getLogger(__name__)


def _safe(cr, label, sql, params=None):
    cr.execute("SAVEPOINT mlm_%s" % label)
    try:
        cr.execute(sql, params)
        n = cr.rowcount
        _logger.info('MLM migration [%s]: %d row(s)', label, n)
        cr.execute("RELEASE SAVEPOINT mlm_%s" % label)
        return n
    except Exception as e:
        cr.execute("ROLLBACK TO SAVEPOINT mlm_%s" % label)
        _logger.warning('MLM migration [%s] skipped: %s', label, e)
        return 0


def migrate(cr, version):
    # Find wallet product via XML ID
    cr.execute("""
        SELECT res_id FROM ir_model_data
        WHERE module = 'mlm_affiliate'
          AND name   = 'product_wallet_discount'
          AND model  = 'product.template'
        LIMIT 1
    """)
    row = cr.fetchone()
    if not row:
        _logger.warning('MLM migration: XML ID not found; skipping.')
        return

    tmpl_id = row[0]

    # Reset list_price to 0
    _safe(cr, 'reset_price', """
        UPDATE product_template
        SET list_price = 0.0
        WHERE id = %s
    """, (tmpl_id,))

    # Clear sales taxes on product template
    _safe(cr, 'clear_tmpl_taxes', """
        DELETE FROM product_taxes_rel WHERE prod_id = %s
    """, (tmpl_id,))

    # Get variant IDs
    cr.execute("SELECT id FROM product_product WHERE product_tmpl_id = %s", (tmpl_id,))
    variant_ids = [r[0] for r in cr.fetchall()]
    if not variant_ids:
        return

    # Fix ALL wallet lines with positive price_unit (any order state)
    cr.execute("""
        SELECT sol.id, sol.price_unit, so.wallet_amount_used
        FROM sale_order_line sol
        JOIN sale_order so ON sol.order_id = so.id
        WHERE sol.product_id = ANY(%s)
          AND sol.price_unit > 0
    """, (variant_ids,))
    bad_lines = cr.fetchall()
    _logger.info('MLM migration: fixing %d broken wallet line(s)', len(bad_lines))

    for line_id, current_price, wallet_used in bad_lines:
        correct = -abs(wallet_used) if wallet_used and wallet_used > 0 else -abs(current_price)
        # Odoo 18: no price_reduce column
        _safe(cr, 'fix_%d' % line_id, """
            UPDATE sale_order_line
            SET price_unit = %s, discount = 0.0
            WHERE id = %s
        """, (correct, line_id))

    # Clear taxes using Odoo 18 table name
    _safe(cr, 'clear_taxes', """
        DELETE FROM account_tax_sale_order_line_rel
        WHERE sale_order_line_id IN (
            SELECT id FROM sale_order_line WHERE product_id = ANY(%s)
        )
    """, (variant_ids,))

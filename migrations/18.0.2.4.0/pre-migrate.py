"""
Migration 18.0.2.4.0 — Fix Affiliate Wallet Credit product and order lines

In Odoo 18, product_template.name is JSONB — we use XML ID to find it.
Each statement runs in a savepoint so failures are non-fatal.
"""
import logging

_logger = logging.getLogger(__name__)


def _safe(cr, label, sql, params=None):
    cr.execute("SAVEPOINT mlm_mig_%s" % label.replace(' ', '_'))
    try:
        cr.execute(sql, params)
        n = cr.rowcount
        _logger.info('MLM migration [%s]: %d row(s)', label, n)
        cr.execute("RELEASE SAVEPOINT mlm_mig_%s" % label.replace(' ', '_'))
        return n
    except Exception as e:
        cr.execute("ROLLBACK TO SAVEPOINT mlm_mig_%s" % label.replace(' ', '_'))
        _logger.warning('MLM migration [%s] skipped: %s', label, e)
        return 0


def migrate(cr, version):
    # Find the wallet product via XML ID (safe in Odoo 18 JSONB)
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
    _logger.info('MLM migration: wallet product template id = %s', tmpl_id)

    # 1. Reset list_price to 0
    _safe(cr, 'reset_price', """
        UPDATE product_template
        SET list_price = 0.0
        WHERE id = %s
    """, (tmpl_id,))

    # 2. Clear sales taxes on product template
    _safe(cr, 'clear_template_taxes', """
        DELETE FROM product_taxes_rel WHERE prod_id = %s
    """, (tmpl_id,))

    # 3. Get variant IDs
    cr.execute("SELECT id FROM product_product WHERE product_tmpl_id = %s", (tmpl_id,))
    variant_ids = [r[0] for r in cr.fetchall()]
    if not variant_ids:
        return
    _logger.info('MLM migration: variant ids = %s', variant_ids)

    # 4. Find ALL wallet discount order lines (any state, positive price_unit)
    cr.execute("""
        SELECT sol.id, sol.price_unit, so.wallet_amount_used, so.state
        FROM sale_order_line sol
        JOIN sale_order so ON sol.order_id = so.id
        WHERE sol.product_id = ANY(%s)
          AND sol.price_unit > 0
    """, (variant_ids,))
    bad_lines = cr.fetchall()
    _logger.info('MLM migration: found %d broken wallet lines to fix', len(bad_lines))

    # 5. Fix each broken line using the wallet_amount_used as the correct amount
    for line_id, current_price, wallet_used, state in bad_lines:
        # Use wallet_amount_used if available, otherwise flip current price
        correct_amount = -abs(wallet_used) if wallet_used and wallet_used > 0 else -abs(current_price)
        _safe(cr, 'fix_line_%d' % line_id, """
            UPDATE sale_order_line
            SET price_unit      = %s,
                price_reduce    = %s,
                discount        = 0.0
            WHERE id = %s
        """, (correct_amount, correct_amount, line_id))
        _logger.info('MLM migration: fixed line id=%d state=%s: %s -> %s',
                     line_id, state, current_price, correct_amount)

    # 6. Clear taxes on all wallet lines (try both Odoo 17 and 18 table names)
    _safe(cr, 'clear_line_taxes_v17', """
        DELETE FROM account_tax_sale_order_line_rel
        WHERE order_line_id IN (
            SELECT id FROM sale_order_line WHERE product_id = ANY(%s)
        )
    """, (variant_ids,))

    _safe(cr, 'clear_line_taxes_v18', """
        DELETE FROM account_tax_sale_order_line_rel
        WHERE sale_order_line_id IN (
            SELECT id FROM sale_order_line WHERE product_id = ANY(%s)
        )
    """, (variant_ids,))

"""
pre-migrate.py  —  mlm_affiliate 18.0.2.0.0
============================================
Runs BEFORE the ORM processes this module on both fresh install and upgrade.
Idempotently adds every new column to res_partner (and other tables) so that
Odoo never queries a column that doesn't exist yet.

Why here and not only in pre_init_hook?
  pre_init_hook fires on fresh install only.
  Migration scripts fire on EVERY upgrade, which is what we need here.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Add new res_partner columns introduced in v2 of mlm_affiliate."""

    # ── res_partner new columns ───────────────────────────────────────────────
    partner_columns = [
        # (column_name, DDL type,               safe default)
        ("tier_id",                  "INTEGER",                          None),
        ("affiliate_bank_account",   "TEXT",                             None),
        ("referral_click_count",     "INTEGER",                          "0"),
        ("referral_last_click",      "TIMESTAMP WITH TIME ZONE",         None),
        ("affiliate_status",         "VARCHAR(20)",                      "'approved'"),
    ]

    for col_name, col_type, default in partner_columns:
        cr.execute("""
            SELECT 1
            FROM information_schema.columns
            WHERE table_name  = 'res_partner'
              AND column_name = %s
        """, (col_name,))

        if cr.fetchone():
            _logger.debug("mlm_affiliate migrate: res_partner.%s already exists — skip", col_name)
            continue

        if default:
            ddl = (
                f'ALTER TABLE res_partner '
                f'ADD COLUMN "{col_name}" {col_type} NOT NULL DEFAULT {default}'
            )
        else:
            ddl = (
                f'ALTER TABLE res_partner '
                f'ADD COLUMN "{col_name}" {col_type}'
            )

        _logger.info("mlm_affiliate migrate: adding column res_partner.%s", col_name)
        cr.execute(ddl)

    # ── mlm_commission new columns ────────────────────────────────────────────
    commission_columns = [
        ("hold_until",            "DATE",                  None),
        ("campaign_multiplier",   "NUMERIC(6,3)",          "1.0"),
        ("account_move_id",       "INTEGER",               None),
        ("is_milestone_bonus",    "BOOLEAN",               "FALSE"),
    ]

    # Table may not exist yet on a fresh install — guard with existence check
    cr.execute("""
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'mlm_commission'
    """)
    if cr.fetchone():
        for col_name, col_type, default in commission_columns:
            cr.execute("""
                SELECT 1
                FROM information_schema.columns
                WHERE table_name  = 'mlm_commission'
                  AND column_name = %s
            """, (col_name,))

            if cr.fetchone():
                _logger.debug(
                    "mlm_affiliate migrate: mlm_commission.%s already exists — skip", col_name
                )
                continue

            if default:
                ddl = (
                    f'ALTER TABLE mlm_commission '
                    f'ADD COLUMN "{col_name}" {col_type} NOT NULL DEFAULT {default}'
                )
            else:
                ddl = (
                    f'ALTER TABLE mlm_commission '
                    f'ADD COLUMN "{col_name}" {col_type}'
                )

            _logger.info("mlm_affiliate migrate: adding column mlm_commission.%s", col_name)
            cr.execute(ddl)

    # ── sale_order wallet columns ─────────────────────────────────────────────
    sale_order_columns = [
        ("wallet_amount_used",  "NUMERIC(16,2)",  "0.0"),
        ("wallet_partner_id",   "INTEGER",        None),
    ]

    cr.execute("""
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'sale_order'
    """)
    if cr.fetchone():
        for col_name, col_type, default in sale_order_columns:
            cr.execute("""
                SELECT 1
                FROM information_schema.columns
                WHERE table_name  = 'sale_order'
                  AND column_name = %s
            """, (col_name,))

            if cr.fetchone():
                continue

            if default:
                ddl = (
                    f'ALTER TABLE sale_order '
                    f'ADD COLUMN "{col_name}" {col_type} NOT NULL DEFAULT {default}'
                )
            else:
                ddl = (
                    f'ALTER TABLE sale_order '
                    f'ADD COLUMN "{col_name}" {col_type}'
                )

            _logger.info("mlm_affiliate migrate: adding column sale_order.%s", col_name)
            cr.execute(ddl)

    _logger.info("mlm_affiliate migrate: pre-migration complete for v2.0.0")

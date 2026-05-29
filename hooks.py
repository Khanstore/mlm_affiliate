"""
hooks.py — lifecycle hooks for mlm_affiliate
============================================
pre_init_hook : fires on FRESH INSTALL only (before ORM).
post_init_hook: fires after ORM on fresh install (safety net).

For UPGRADES the migration script at
  migrations/18.0.2.0.0/pre-migrate.py
handles the column additions — it runs before the ORM on every upgrade.
"""
import logging

_logger = logging.getLogger(__name__)


def _ensure_columns(cr):
    """
    Idempotently add every new column this module needs.
    Called from both pre_init_hook and the migration script so there
    is no code duplication.
    """
    partner_columns = [
        ("tier_id",                   "INTEGER",                   None),
        ("affiliate_bank_account",    "TEXT",                      None),
        ("referral_click_count",      "INTEGER",                   "0"),
        ("referral_last_click",       "TIMESTAMP WITH TIME ZONE",  None),
        ("affiliate_status",          "VARCHAR(20)",               "'approved'"),
    ]

    for col_name, col_type, default in partner_columns:
        cr.execute("""
            SELECT 1
            FROM information_schema.columns
            WHERE table_name  = 'res_partner'
              AND column_name = %s
        """, (col_name,))

        if cr.fetchone():
            continue

        if default:
            cr.execute(
                f'ALTER TABLE res_partner '
                f'ADD COLUMN "{col_name}" {col_type} NOT NULL DEFAULT {default}'
            )
        else:
            cr.execute(
                f'ALTER TABLE res_partner '
                f'ADD COLUMN "{col_name}" {col_type}'
            )
        _logger.info("mlm_affiliate hooks: added res_partner.%s", col_name)


def pre_init_hook(env):
    _ensure_columns(env.cr)


def post_init_hook(env):
    # Safety net: if pre_init_hook was skipped for any reason
    _ensure_columns(env.cr)

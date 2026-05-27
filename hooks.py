"""
hooks.py — lifecycle hooks for mlm_affiliate
=============================================
pre_init_hook: runs BEFORE the ORM processes this module.
This ensures all new res.partner columns exist in the DB before Odoo's
internal upgrade machinery runs its early `res.company.country_id` query,
which would otherwise crash with:
    psycopg2.errors.UndefinedColumn: column res_partner.tier_id does not exist
"""
import logging

_logger = logging.getLogger(__name__)


def pre_init_hook(env):
    """
    Called by Odoo before installing OR upgrading this module.
    Idempotently adds the new res_partner columns so the ORM never
    queries a column that doesn't exist yet.
    """
    cr = env.cr

    columns = [
        # (column_name, column_definition)
        ("tier_id",                  "INTEGER"),
        ("affiliate_bank_account",   "TEXT"),
        ("referral_click_count",     "INTEGER DEFAULT 0"),
        ("referral_last_click",      "TIMESTAMP WITH TIME ZONE"),
    ]

    for col_name, col_def in columns:
        # Check if column already exists before trying to add it
        cr.execute("""
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'res_partner'
              AND column_name = %s
        """, (col_name,))

        if not cr.fetchone():
            _logger.info("mlm_affiliate: adding column res_partner.%s", col_name)
            cr.execute(
                f'ALTER TABLE res_partner ADD COLUMN "{col_name}" {col_def}'
            )
        else:
            _logger.debug("mlm_affiliate: column res_partner.%s already exists", col_name)

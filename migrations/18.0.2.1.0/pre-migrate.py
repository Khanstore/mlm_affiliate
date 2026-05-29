"""
pre-migrate.py — mlm_affiliate 18.0.2.1.0
==========================================
- Drops total_commission_earned from res_partner if it was accidentally
  created as a stored column in v2.0.x (field is now store=False).
- Ensures all other custom res_partner columns exist.
"""
import logging
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Drop the accidental stored column if it exists
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'res_partner'
          AND column_name = 'total_commission_earned'
    """)
    if cr.fetchone():
        _logger.info(
            "mlm_affiliate 2.1.0: dropping res_partner.total_commission_earned "
            "(field changed to store=False)"
        )
        cr.execute("ALTER TABLE res_partner DROP COLUMN total_commission_earned")

    # Ensure affiliate_status exists (belt-and-suspenders for old DBs)
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'res_partner' AND column_name = 'affiliate_status'
    """)
    if not cr.fetchone():
        cr.execute("""
            ALTER TABLE res_partner
            ADD COLUMN affiliate_status VARCHAR(20) NOT NULL DEFAULT 'approved'
        """)
        _logger.info("mlm_affiliate 2.1.0: added res_partner.affiliate_status")

    _logger.info("mlm_affiliate 2.1.0: pre-migration complete")

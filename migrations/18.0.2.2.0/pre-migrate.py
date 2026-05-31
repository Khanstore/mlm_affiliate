"""
pre-migrate.py — mlm_affiliate 18.0.2.2.0
==========================================
Bug-fix release: no schema changes needed.
All fixes are in Python/XML logic only.
"""
import logging
_logger = logging.getLogger(__name__)

def migrate(cr, version):
    _logger.info("mlm_affiliate 2.2.0: pre-migration — no schema changes needed")

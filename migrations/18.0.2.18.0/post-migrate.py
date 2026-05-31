"""
18.0.2.18.0 post-migrate
========================
Re-runs _setup_accounting_params so that users who had the broken
MLM-EXP / MLM-PAY account codes (rejected by Odoo 18's alphanumeric
validation) get their ir.config_parameter entries wired up automatically
after upgrading to the fixed version.
"""
import logging
from odoo.addons.mlm_affiliate.hooks import _setup_accounting_params

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info('mlm_affiliate 18.0.2.18.0: wiring accounting config params')
    from odoo import api, registry as Registry
    with Registry(cr.dbname).cursor() as new_cr:
        env = api.Environment(new_cr, 1, {})
        _setup_accounting_params(env)
        new_cr.commit()

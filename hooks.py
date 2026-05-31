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
    # Wire the accounting records into ir.config_parameter
    _setup_accounting_params(env)


def _setup_accounting_params(env):
    """
    After install/upgrade, write the MLM account/journal IDs into
    ir.config_parameter so mlm_commission._create_accounting_entry()
    picks them up automatically.

    Strategy (in order):
      1. Try env.ref() — works on clean installs where XML loaded fine.
      2. Fall back to searching by account code / journal code — handles
         cases where noupdate=1 XML was previously broken (e.g. hyphen
         in code) but the records were later created correctly.

    Only sets params that are not already configured (respects admin changes).
    """
    cfg = env['ir.config_parameter'].sudo()
    AccountAccount = env['account.account'].sudo()
    AccountJournal = env['account.journal'].sudo()

    try:
        # ── Expense account ──────────────────────────────────────────────
        if not cfg.get_param('mlm_affiliate.expense_account_id'):
            acc = env.ref('mlm_affiliate.account_mlm_commission_expense',
                          raise_if_not_found=False)
            if not acc:
                acc = AccountAccount.search(
                    [('code', '=', '501108')], limit=1)
            if not acc:
                acc = AccountAccount.search(
                    [('name', 'ilike', 'MLM Commission Expense')], limit=1)
            if acc:
                cfg.set_param('mlm_affiliate.expense_account_id', str(acc.id))
                _logger.info('MLM hooks: set expense_account_id = %s (code %s)',
                             acc.id, acc.code)
            else:
                _logger.warning('MLM hooks: expense account not found — '
                                'configure manually in Settings > MLM')

        # ── Payable account ──────────────────────────────────────────────
        if not cfg.get_param('mlm_affiliate.payable_account_id'):
            acc = env.ref('mlm_affiliate.account_mlm_commission_payable',
                          raise_if_not_found=False)
            if not acc:
                acc = AccountAccount.search(
                    [('code', '=', '300201')], limit=1)
            if not acc:
                acc = AccountAccount.search(
                    [('name', 'ilike', 'MLM Commission Payable')], limit=1)
            if acc:
                cfg.set_param('mlm_affiliate.payable_account_id', str(acc.id))
                _logger.info('MLM hooks: set payable_account_id = %s (code %s)',
                             acc.id, acc.code)
            else:
                _logger.warning('MLM hooks: payable account not found — '
                                'configure manually in Settings > MLM')

        # ── Journal ──────────────────────────────────────────────────────
        if not cfg.get_param('mlm_affiliate.journal_id'):
            journal = env.ref('mlm_affiliate.journal_mlm_commission',
                              raise_if_not_found=False)
            if not journal:
                journal = AccountJournal.search(
                    [('code', '=', 'MLMC')], limit=1)
            if not journal:
                journal = AccountJournal.search(
                    [('name', 'ilike', 'MLM Commission')], limit=1)
            if journal:
                cfg.set_param('mlm_affiliate.journal_id', str(journal.id))
                _logger.info('MLM hooks: set journal_id = %s (code %s)',
                             journal.id, journal.code)
            else:
                _logger.warning('MLM hooks: MLM journal not found — '
                                'configure manually in Settings > MLM')

    except Exception:
        _logger.exception('MLM hooks: failed to set accounting config params')

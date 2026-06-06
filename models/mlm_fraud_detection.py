"""
mlm_fraud_detection.py  — NEW FILE
====================================
Referral Fraud Detection subsystem.

Signals checked
---------------
1. IP address  — multiple referred partners registered from the same IP
2. Shipping address (street + city + zip) — referred partners share a physical address
3. Device fingerprint cookie (`mlm_fp`) — browser fingerprint hash set by the JS snippet
   (see static/src/js/referral_tracker.js extension below)

How it works
------------
* On every new portal/website registration that carries a referral cookie, the
  controller calls `MlmFraudChecker.check_new_partner()`.
* The checker counts how many OTHER partners that were referred by the SAME
  upline share the same signal value.  If it exceeds the configurable threshold
  (default: 3) the new partner's `mlm_fraud_flag` is set and an internal note is
  posted so the MLM manager can review.
* A scheduled cron (`_cron_scan_fraud`) re-scans existing partners nightly so
  that fraud patterns emerging over time are caught retroactively.

Database columns added to res_partner
--------------------------------------
mlm_registration_ip      VARCHAR(45)   — stored at registration time by the controller
mlm_device_fingerprint   VARCHAR(64)   — SHA-256 of browser fingerprint (optional)

Both are admin-only fields; portal users cannot read them.
"""

import logging
from collections import defaultdict

from odoo import models, fields, api

_logger = logging.getLogger(__name__)

# How many shared-signal hits trigger a fraud flag by default.
# Configurable via ir.config_parameter 'mlm_affiliate.fraud_threshold'.
_DEFAULT_FRAUD_THRESHOLD = 3


class ResPartnerFraudFields(models.Model):
    """
    Mixin-style extension to res.partner adding fraud-tracking columns.
    Kept in a separate model class so the patch is self-contained.
    """
    _inherit = 'res.partner'

    mlm_registration_ip    = fields.Char(
        string='Registration IP',
        groups='mlm_affiliate.group_mlm_manager',
        help='IP address captured when the partner registered via a referral link.',
    )
    mlm_device_fingerprint = fields.Char(
        string='Device Fingerprint',
        groups='mlm_affiliate.group_mlm_manager',
        help='Browser fingerprint hash (SHA-256) set by the referral tracking script.',
    )

    def _auto_init(self):
        res = super()._auto_init()
        self._mlm_ensure_fraud_columns()
        return res

    @api.model
    def _mlm_ensure_fraud_columns(self):
        extra = [
            ('mlm_registration_ip',    'VARCHAR(45)', None),
            ('mlm_device_fingerprint', 'VARCHAR(64)', None),
        ]
        cr = self.env.cr
        for col, col_type, _ in extra:
            cr.execute("""
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'res_partner' AND column_name = %s
            """, (col,))
            if not cr.fetchone():
                cr.execute(f'ALTER TABLE res_partner ADD COLUMN "{col}" {col_type}')


class MlmFraudChecker(models.AbstractModel):
    """
    Stateless service model — call methods on this to run fraud checks.
    Using AbstractModel keeps it out of the DB while allowing env access.
    """
    _name        = 'mlm.fraud.checker'
    _description = 'MLM Fraud Detection Service'

    @api.model
    def _get_threshold(self):
        return int(
            self.env['ir.config_parameter'].sudo()
            .get_param('mlm_affiliate.fraud_threshold', _DEFAULT_FRAUD_THRESHOLD)
        )

    @api.model
    def check_new_partner(self, partner):
        """
        Run all fraud checks for a freshly created referred partner.
        Call this from the registration controller immediately after
        the partner record is created.

        :param partner: res.partner record (single)
        """
        if not partner or not partner.upline_partner_id:
            return
        reasons = []
        threshold = self._get_threshold()

        reasons += self._check_ip(partner, threshold)
        reasons += self._check_address(partner, threshold)
        reasons += self._check_fingerprint(partner, threshold)

        if reasons:
            self._flag_partner(partner, reasons)

    @api.model
    def _check_ip(self, partner, threshold):
        """Flag if ≥ threshold OTHER referred partners share the same IP."""
        ip = partner.mlm_registration_ip
        if not ip:
            return []
        count = self.env['res.partner'].sudo().search_count([
            ('upline_partner_id', '=', partner.upline_partner_id.id),
            ('mlm_registration_ip', '=', ip),
            ('id', '!=', partner.id),
        ])
        if count >= threshold:
            return [f'IP address {ip} is shared by {count + 1} referred partners '
                    f'under the same upline (threshold: {threshold}).']
        return []

    @api.model
    def _check_address(self, partner, threshold):
        """Flag if ≥ threshold OTHER referred partners share street+city+zip."""
        street = (partner.street or '').strip().lower()
        city   = (partner.city or '').strip().lower()
        zipcode = (partner.zip or '').strip()
        if not (street and city):
            return []
        count = self.env['res.partner'].sudo().search_count([
            ('upline_partner_id', '=', partner.upline_partner_id.id),
            ('street', 'ilike', street),
            ('city',   'ilike', city),
            ('zip',    '=', zipcode),
            ('id', '!=', partner.id),
        ])
        if count >= threshold:
            return [f'Shipping address "{partner.street}, {partner.city} {partner.zip}" '
                    f'is shared by {count + 1} referred partners '
                    f'under the same upline (threshold: {threshold}).']
        return []

    @api.model
    def _check_fingerprint(self, partner, threshold):
        """Flag if ≥ threshold OTHER referred partners share the device fingerprint."""
        fp = partner.mlm_device_fingerprint
        if not fp:
            return []
        count = self.env['res.partner'].sudo().search_count([
            ('upline_partner_id', '=', partner.upline_partner_id.id),
            ('mlm_device_fingerprint', '=', fp),
            ('id', '!=', partner.id),
        ])
        if count >= threshold:
            return [f'Device fingerprint "{fp[:12]}…" is shared by {count + 1} referred '
                    f'partners under the same upline (threshold: {threshold}).']
        return []

    @api.model
    def _flag_partner(self, partner, reasons):
        """Set fraud flag and post an internal chatter note for the manager."""
        reason_text = '\n• '.join(reasons)
        partner.sudo().write({
            'mlm_fraud_flag':   True,
            'mlm_fraud_reason': '• ' + reason_text,
        })
        # Post a red chatter note visible only to internal users
        try:
            partner.sudo().message_post(
                body=(
                    '<b>🚨 MLM Fraud Suspected</b><br/>'
                    + reason_text.replace('\n', '<br/>')
                ),
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )
        except Exception:
            _logger.exception('MLM fraud: failed to post chatter note for partner %s', partner.id)
        _logger.warning(
            'MLM fraud flag set on partner %s (id=%s): %s',
            partner.display_name, partner.id, reason_text
        )

    # ── Nightly batch scan ────────────────────────────────────────────────────

    @api.model
    def _cron_scan_fraud(self):
        """
        Nightly scan: group referred partners by (upline, signal) and flag any
        upline whose downline exceeds the threshold for any signal.

        Uses read_group + GROUP BY to minimise round trips.
        """
        threshold = self._get_threshold()
        Partner   = self.env['res.partner'].sudo()

        # --- IP scan ---
        groups = Partner.read_group(
            domain=[
                ('upline_partner_id', '!=', False),
                ('mlm_registration_ip', '!=', False),
            ],
            fields=['upline_partner_id', 'mlm_registration_ip'],
            groupby=['upline_partner_id', 'mlm_registration_ip'],
            lazy=False,
        )
        suspicious_ip = defaultdict(list)
        for g in groups:
            if g['__count'] >= threshold:
                upline_id = g['upline_partner_id'][0]
                ip        = g['mlm_registration_ip']
                suspicious_ip[upline_id].append((ip, g['__count']))

        # --- Address scan ---
        # street + city + zip grouping
        self.env.cr.execute("""
            SELECT upline_partner_id, street, city, zip, COUNT(*) AS cnt
            FROM res_partner
            WHERE upline_partner_id IS NOT NULL
              AND COALESCE(street, '') != ''
              AND COALESCE(city, '')   != ''
            GROUP BY upline_partner_id, LOWER(street), LOWER(city), zip
            HAVING COUNT(*) >= %s
        """, (threshold,))
        suspicious_address_partners = set()
        for row in self.env.cr.fetchall():
            upline_id, street, city, zipcode, cnt = row
            # Find all partners in this group
            matches = Partner.search([
                ('upline_partner_id', '=', upline_id),
                ('street', 'ilike', street),
                ('city',   'ilike', city),
                ('zip',    '=',     zipcode),
            ])
            for p in matches:
                if not p.mlm_fraud_flag:
                    suspicious_address_partners.add(p.id)
                    self._flag_partner(p, [
                        f'Nightly scan: address "{street}, {city} {zipcode}" '
                        f'shared by {cnt} referred partners under the same upline.'
                    ])

        # --- Flag partners from IP scan ---
        for upline_id, ip_counts in suspicious_ip.items():
            for ip, cnt in ip_counts:
                matches = Partner.search([
                    ('upline_partner_id', '=', upline_id),
                    ('mlm_registration_ip', '=', ip),
                    ('mlm_fraud_flag', '=', False),
                ])
                for p in matches:
                    self._flag_partner(p, [
                        f'Nightly scan: IP {ip} shared by {cnt} referred partners '
                        f'under the same upline.'
                    ])

        _logger.info('MLM fraud scan complete.')

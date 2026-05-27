/** @odoo-module **/
/**
 * FIX: Added referral code sanitization (alphanumeric 4-16 chars only).
 * FIX: Removed console.debug calls.
 */
(function () {
    'use strict';

    const COOKIE_NAME = 'mlm_ref';
    const COOKIE_DAYS = 30;
    // FIX: whitelist pattern — only safe alphanumeric codes are accepted
    const CODE_PATTERN = /^[A-Z0-9]{4,16}$/;

    function setCookie(name, value, days) {
        const expires = new Date(Date.now() + days * 864e5).toUTCString();
        document.cookie =
            encodeURIComponent(name) + '=' + encodeURIComponent(value) +
            '; expires=' + expires + '; path=/; SameSite=Lax';
    }

    function init() {
        const params = new URLSearchParams(window.location.search);
        const rawCode = (params.get('ref') || '').trim().toUpperCase();

        // FIX: reject codes that don't match the expected format
        if (!rawCode || !CODE_PATTERN.test(rawCode)) {
            return;
        }

        setCookie(COOKIE_NAME, rawCode, COOKIE_DAYS);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

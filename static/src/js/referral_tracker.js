/** @odoo-module **/
/**
 * mlm_affiliate/static/src/js/referral_tracker.js
 *
 * Reads the ?ref=CODE query parameter from any page URL and sets the
 * mlm_ref cookie (30 days) so that the referral is captured even when
 * the user does NOT go through the /ref/<code> redirect route.
 *
 * Example: https://yoursite.com/shop?ref=ABC12345
 */

(function () {
    'use strict';

    const COOKIE_NAME = 'mlm_ref';
    const COOKIE_DAYS = 30;

    function getCookie(name) {
        const match = document.cookie.match(
            new RegExp('(?:^|;\\s*)' + name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '=([^;]*)')
        );
        return match ? decodeURIComponent(match[1]) : null;
    }

    function setCookie(name, value, days) {
        const expires = new Date(Date.now() + days * 864e5).toUTCString();
        document.cookie =
            encodeURIComponent(name) +
            '=' +
            encodeURIComponent(value) +
            '; expires=' +
            expires +
            '; path=/; SameSite=Lax';
    }

    function init() {
        const params = new URLSearchParams(window.location.search);
        const refCode = params.get('ref');

        if (refCode && refCode.trim()) {
            // Always refresh the cookie when a ref param is present
            // (lets a new referrer overwrite an old expired one).
            setCookie(COOKIE_NAME, refCode.trim(), COOKIE_DAYS);
            console.debug('[MLM Affiliate] Referral code captured:', refCode.trim());
        }
    }

    // Run on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

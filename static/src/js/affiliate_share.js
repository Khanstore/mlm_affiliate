// MLM Affiliate Share — Odoo 18
// No @odoo-module tag: runs as a plain synchronous script.
//
// Odoo 18 s_share widget confirmed source:
//   const currentUrl = window.location.href;
//   modifiedUrl.searchParams.set(param, currentUrl);
//   window.open(modifiedUrl.toString(), aEl.target, "...");
//
// Fix: use history.replaceState to temporarily swap window.location.href
// to the referral URL in a capture-phase click handler that fires BEFORE
// Odoo's jQuery handler reads window.location.href. Restore immediately
// after via setTimeout(0) once the call stack is done.

(function () {
    'use strict';

    // Read the ref code that the QWeb template injects server-side.
    // Called lazily at click time so DOM readiness doesn't matter.
    var _code;
    function getCode() {
        if (_code !== undefined) return _code;
        var el = document.getElementById('mlm_affiliate_data');
        _code = (el && el.getAttribute('data-ref-code')) || '';
        return _code;
    }

    // Build referral URL: /ref/CODE/shop/... from the current page URL.
    function toRefUrl(href, code) {
        try {
            var u = new URL(href);
            if (u.pathname.indexOf('/ref/') === 0) return href; // already tagged
            u.pathname = '/ref/' + code + u.pathname;
            return u.toString();
        } catch (e) {
            return href;
        }
    }

    // ── Step 1: Capture-phase click handler ───────────────────────────────────
    // Fires before Odoo's jQuery bubble-phase handler on .s_share a clicks.
    // Temporarily replaces window.location.href via history.replaceState so
    // Odoo reads our referral URL instead of the bare product URL.
    document.addEventListener('click', function (ev) {
        var code = getCode();
        if (!code) return;

        // Walk up the DOM to check we are inside .s_share or .oe_share
        var node = ev.target;
        var inside = false;
        for (var i = 0; i < 12; i++) {
            if (!node || node === document) break;
            var cls = node.className || '';
            if (typeof cls === 'string' && (cls.indexOf('s_share') !== -1 || cls.indexOf('oe_share') !== -1)) {
                inside = true;
                break;
            }
            node = node.parentNode;
        }
        if (!inside) return;

        var orig = window.location.href;
        var ref  = toRefUrl(orig, code);
        if (ref === orig) return;

        // Temporarily swap the URL
        try {
            history.replaceState(history.state, '', ref);
        } catch (e) {
            return; // history API blocked — fall through to window.open wrap
        }

        // Restore after the current call stack completes
        // (Odoo calls window.open synchronously inside its click handler,
        //  so setTimeout(0) runs after window.open has already been called)
        setTimeout(function () {
            try { history.replaceState(history.state, '', orig); } catch (e2) {}
        }, 0);

    }, true); // true = capture phase

    // ── Step 2: window.open wrapper (belt-and-suspenders) ────────────────────
    // Even if history.replaceState works, Odoo embeds window.location.href
    // inside the share platform URL params. This wrapper scans all params
    // and rewrites any same-origin URL it finds.
    var _origOpen = window.open;
    window.open = function (url, target, features) {
        var code = getCode();
        if (code && url && typeof url === 'string') {
            try {
                var u = new URL(url);
                var changed = false;
                u.searchParams.forEach(function (val, key) {
                    var next = val.replace(/https?:\/\/[^\s"<>]+/g, function (m) {
                        try {
                            // Only rewrite same-origin URLs
                            var mu = new URL(m);
                            if (mu.hostname !== window.location.hostname) return m;
                            return toRefUrl(m, code);
                        } catch (e) { return m; }
                    });
                    if (next !== val) { u.searchParams.set(key, next); changed = true; }
                });
                if (changed) url = u.toString();
            } catch (e) {}
        }
        return _origOpen.call(window, url, target, features);
    };

})();

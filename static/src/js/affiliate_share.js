/** @odoo-module **/
/**
 * FIX: Removed console.debug calls.
 * Rewrites social-share buttons on a product page with the affiliate's referral URL.
 */
(function () {
    'use strict';

    function getAffiliateCode() {
        const el = document.getElementById('mlm_affiliate_data');
        return el ? (el.dataset.refCode || '').trim() : '';
    }

    function buildAffiliateUrl(refCode) {
        const origin = window.location.origin;
        const path = window.location.pathname.replace(/^\//, '');
        return origin + '/ref/' + refCode + '/' + path;
    }

    const SHARE_PATTERNS = [
        { host: 'facebook.com/sharer',      param: 'u'    },
        { host: 'twitter.com/intent/tweet', param: 'url'  },
        { host: 'x.com/intent/tweet',       param: 'url'  },
        { host: 'linkedin.com/sharing',     param: 'url'  },
        { host: 'pinterest.com/pin/create', param: 'url'  },
        { host: 'wa.me',                    param: 'text' },
        { host: 'api.whatsapp.com/send',    param: 'text' },
        { host: 'mailto:',                  param: 'body' },
    ];

    function patchAnchor(anchor, affiliateUrl) {
        const rawHref = anchor.getAttribute('href') || '';
        if (!rawHref) return;
        for (const pattern of SHARE_PATTERNS) {
            if (!rawHref.includes(pattern.host)) continue;
            try {
                if (pattern.host === 'mailto:') {
                    const patched = rawHref.replace(/body=([^&]*)/, function (_, encoded) {
                        const rewritten = decodeURIComponent(encoded)
                            .replace(/https?:\/\/[^\s"<]+/g, affiliateUrl);
                        return 'body=' + encodeURIComponent(rewritten);
                    });
                    anchor.setAttribute('href', patched);
                    return;
                }
                const url = new URL(rawHref);
                const val = url.searchParams.get(pattern.param);
                if (val) {
                    url.searchParams.set(pattern.param, affiliateUrl);
                    anchor.setAttribute('href', url.toString());
                }
            } catch (e) { /* malformed href */ }
            return;
        }
    }

    function patchAll(affiliateUrl) {
        document.querySelectorAll('a[href]').forEach(function (a) {
            patchAnchor(a, affiliateUrl);
        });
    }

    function watchDOM(affiliateUrl) {
        const observer = new MutationObserver(function (mutations) {
            mutations.forEach(function (mutation) {
                mutation.addedNodes.forEach(function (node) {
                    if (node.nodeType !== 1) return;
                    const anchors = node.tagName === 'A'
                        ? [node]
                        : Array.from(node.querySelectorAll('a[href]'));
                    anchors.forEach(function (a) { patchAnchor(a, affiliateUrl); });
                });
            });
        });
        observer.observe(document.body, { childList: true, subtree: true });
    }

    function init() {
        const refCode = getAffiliateCode();
        if (!refCode) return;
        const affiliateUrl = buildAffiliateUrl(refCode);
        patchAll(affiliateUrl);
        watchDOM(affiliateUrl);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

/** @odoo-module **/
/**
 * mlm_affiliate/static/src/js/affiliate_share.js
 *
 * When a logged-in affiliate views a product page, this script rewrites
 * every social-share button (Facebook, X/Twitter, LinkedIn, WhatsApp,
 * Pinterest, Email) so the link they share already contains their
 * referral code.
 *
 * How it works
 * ─────────────
 *  1. The QWeb template injects a hidden <div id="mlm_affiliate_data">
 *     with a data-ref-code attribute when the viewer is an affiliate.
 *  2. This script reads that attribute.
 *  3. It builds the affiliate product URL:
 *       /ref/<code>/shop/product/<slug>
 *  4. It finds every <a> whose href contains a social-share URL and
 *     replaces the encoded product URL inside it with the affiliate URL.
 */

(function () {
    'use strict';

    // ── 1. Read the affiliate code injected by QWeb ───────────────────────
    function getAffiliateCode() {
        const el = document.getElementById('mlm_affiliate_data');
        return el ? (el.dataset.refCode || '').trim() : '';
    }

    // ── 2. Build the affiliate version of the current product URL ─────────
    function buildAffiliateUrl(refCode) {
        const origin   = window.location.origin;               // http://localhost:8069
        const path     = window.location.pathname.replace(/^\//, ''); // shop/product/awesome-tee
        return origin + '/ref/' + refCode + '/' + path;        // .../ref/CODE/shop/product/…
    }

    // ── 3. Social-share platforms whose hrefs we need to patch ────────────
    //    Each entry is a {param} name OR a sentinel used for email/WhatsApp.
    const SHARE_PATTERNS = [
        { host: 'facebook.com/sharer',          param: 'u'    },
        { host: 'twitter.com/intent/tweet',      param: 'url'  },
        { host: 'x.com/intent/tweet',            param: 'url'  },
        { host: 'linkedin.com/sharing',          param: 'url'  },
        { host: 'pinterest.com/pin/create',      param: 'url'  },
        { host: 'wa.me',                         param: 'text' },
        { host: 'api.whatsapp.com/send',         param: 'text' },
        { host: 'mailto:',                       param: 'body' },  // email
    ];

    // ── 4. Rewrite a single <a> tag if it matches a share pattern ─────────
    function patchAnchor(anchor, affiliateUrl) {
        const rawHref = anchor.getAttribute('href') || '';

        for (const pattern of SHARE_PATTERNS) {
            if (!rawHref.includes(pattern.host)) continue;

            try {
                // mailto: is not a standard URL; handle separately
                if (pattern.host === 'mailto:') {
                    // mailto:?subject=...&body=<encoded_url>
                    const bodyMatch = rawHref.match(/body=([^&]*)/);
                    if (bodyMatch) {
                        const decoded = decodeURIComponent(bodyMatch[1]);
                        // Replace any http(s)://...(/shop/product/...) in the body
                        const patched = decoded.replace(/https?:\/\/[^\s]+\/shop\/[^\s]*/g, affiliateUrl);
                        anchor.setAttribute(
                            'href',
                            rawHref.replace(/body=[^&]*/, 'body=' + encodeURIComponent(patched))
                        );
                    }
                    return;
                }

                // Standard URL with query params
                const url = new URL(rawHref);
                const paramVal = url.searchParams.get(pattern.param);
                if (paramVal) {
                    url.searchParams.set(pattern.param, affiliateUrl);
                    anchor.setAttribute('href', url.toString());
                }
            } catch (e) {
                // Malformed href – skip silently
            }
            return; // matched, no need to check further patterns
        }
    }

    // ── 5. Find and patch all share anchors on the page ───────────────────
    function patchAllShareButtons(affiliateUrl) {
        // Odoo renders share buttons in a <div class="o_share"> or similar;
        // we cast a wide net and check every <a> that looks like a share link.
        const anchors = document.querySelectorAll('a[href]');
        anchors.forEach(function (a) {
            patchAnchor(a, affiliateUrl);
        });
    }

    // ── 6. Also handle dynamically-rendered share widgets (MutationObserver)
    function watchForNewShareButtons(affiliateUrl) {
        const observer = new MutationObserver(function (mutations) {
            mutations.forEach(function (mutation) {
                mutation.addedNodes.forEach(function (node) {
                    if (node.nodeType !== 1) return; // element nodes only
                    const anchors = node.tagName === 'A'
                        ? [node]
                        : Array.from(node.querySelectorAll('a[href]'));
                    anchors.forEach(function (a) { patchAnchor(a, affiliateUrl); });
                });
            });
        });
        observer.observe(document.body, { childList: true, subtree: true });
    }

    // ── 7. Entry point ────────────────────────────────────────────────────
    function init() {
        const refCode = getAffiliateCode();
        if (!refCode) return; // visitor is not an affiliate – do nothing

        // Only run on product pages
        if (!window.location.pathname.includes('/shop/')) return;

        const affiliateUrl = buildAffiliateUrl(refCode);
        console.debug('[MLM Affiliate] Patching share buttons with:', affiliateUrl);

        patchAllShareButtons(affiliateUrl);
        watchForNewShareButtons(affiliateUrl);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

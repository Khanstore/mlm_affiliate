// Affiliate join page — NO @odoo-module tag so this runs as a plain script.
// DOMContentLoaded is reliable because this file loads synchronously.

(function () {
    'use strict';

    // ── JSON-RPC helper for Odoo type='json' routes ───────────────────────────
    function rpc(url, params) {
        return fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
            },
            body: JSON.stringify({
                jsonrpc: '2.0',
                method: 'call',
                id: Math.floor(Math.random() * 1e9),
                params: params || {}
            })
        })
        .then(function (r) { return r.json(); })
        .then(function (r) {
            if (r.error) {
                var msg = (r.error.data && r.error.data.message) || r.error.message || 'Server error';
                throw new Error(msg);
            }
            return r.result;
        });
    }

    // ── Wire up the form once DOM is ready ────────────────────────────────────
    function init() {
        var searchInput  = document.getElementById('o_aff_search');
        var searchBtn    = document.getElementById('o_aff_search_btn');
        var searchResult = document.getElementById('o_aff_search_result');
        var partnerIdEl  = document.getElementById('o_aff_partner_id');
        var nameEl       = document.getElementById('o_aff_name');
        var emailEl      = document.getElementById('o_aff_email');
        var phoneEl      = document.getElementById('o_aff_phone');
        var mobileEl     = document.getElementById('o_aff_mobile');
        var alertEl      = document.getElementById('o_aff_alert');
        var submitBtn    = document.getElementById('o_aff_submit');
        var successEl    = document.getElementById('o_aff_success');
        var successMsg   = document.getElementById('o_aff_success_msg');
        var formEl       = document.getElementById('o_aff_form');
        var stepLookup   = document.getElementById('o_aff_step_lookup');

        // Not on this page
        if (!searchBtn || !submitBtn) return;

        // ── Helpers ───────────────────────────────────────────────────────────
        function showAlert(msg, type) {
            alertEl.className = 'alert alert-' + (type || 'danger') + ' mb-3';
            alertEl.textContent = msg;
        }

        function lockFields(data) {
            partnerIdEl.value  = data.id || '';
            nameEl.value       = data.name   || '';
            emailEl.value      = data.email  || '';
            phoneEl.value      = data.phone  || '';
            mobileEl.value     = data.mobile || '';
            [nameEl, emailEl, phoneEl, mobileEl].forEach(function (el) {
                el.readOnly = true;
                el.classList.add('bg-light');
            });
        }

        function unlockFields() {
            partnerIdEl.value = '';
            [nameEl, emailEl, phoneEl, mobileEl].forEach(function (el) {
                el.readOnly = false;
                el.classList.remove('bg-light');
            });
        }

        // ── Search ────────────────────────────────────────────────────────────
        function doSearch() {
            var q = (searchInput.value || '').trim();
            if (q.length < 4) {
                searchResult.innerHTML =
                    '<small class="text-muted">Enter at least 4 characters.</small>';
                return;
            }

            searchBtn.disabled = true;
            searchBtn.textContent = '…';
            searchResult.innerHTML = '';
            unlockFields();

            rpc('/affiliate/lookup', { search: q })
            .then(function (data) {
                searchBtn.disabled = false;
                searchBtn.textContent = 'Search';

                if (!data || !data.found) {
                    searchResult.innerHTML =
                        '<small class="text-success fw-semibold">' +
                        '✓ No existing account found — fill in your details below.</small>';
                    return;
                }

                if (data.is_affiliate && data.affiliate_status === 'approved') {
                    var loginUrl = '/web/login?redirect=/my/affiliate';
                    if (data.email) {
                        loginUrl += '&login=' + encodeURIComponent(data.email);
                    }
                    searchResult.innerHTML =
                        '<div class="alert alert-success py-2 mb-0">' +
                        '<div class="d-flex align-items-center justify-content-between flex-wrap gap-2">' +
                        '<span><i class="fa fa-check-circle me-1"></i> <strong>' + data.name + '</strong> is already an approved affiliate!</span>' +
                        '<a href="' + loginUrl + '" class="btn btn-success btn-sm">' +
                        '<i class="fa fa-sign-in me-1"></i>Sign in to Dashboard</a>' +
                        '</div>' +
                        '</div>';
                    return;
                }

                if (data.is_affiliate && data.affiliate_status === 'pending') {
                    searchResult.innerHTML =
                        '<div class="alert alert-warning py-2 small mb-0">' +
                        '⏳ <strong>' + data.name + '</strong> — application already pending review.</div>';
                    return;
                }

                // Found, not yet affiliate — offer to use account
                searchResult.innerHTML =
                    '<div class="alert alert-info py-2 small mb-2">' +
                    '✓ Found: <strong>' + data.name + '</strong>' +
                    (data.email ? ' (' + data.email + ')' : '') +
                    ' &nbsp;—&nbsp; ' +
                    '<a href="#" id="o_aff_use_btn">Use this account</a>' +
                    ' &nbsp;|&nbsp; ' +
                    '<a href="#" id="o_aff_notme_btn">Not me</a>' +
                    '</div>';

                var useBtn = document.getElementById('o_aff_use_btn');
                var notMeBtn = document.getElementById('o_aff_notme_btn');

                if (useBtn) {
                    useBtn.addEventListener('click', function (e) {
                        e.preventDefault();
                        lockFields(data);
                        searchResult.innerHTML =
                            '<small class="text-success fw-semibold">' +
                            '✓ Using account: ' + data.name +
                            ' — click Submit below.</small>';
                    });
                }
                if (notMeBtn) {
                    notMeBtn.addEventListener('click', function (e) {
                        e.preventDefault();
                        unlockFields();
                        searchResult.innerHTML =
                            '<small class="text-muted">Fill in your own details below.</small>';
                    });
                }
            })
            .catch(function (err) {
                searchBtn.disabled = false;
                searchBtn.textContent = 'Search';
                searchResult.innerHTML =
                    '<small class="text-danger">Search failed: ' +
                    (err.message || 'please try again') + '</small>';
            });
        }

        searchBtn.addEventListener('click', doSearch);
        searchInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') { e.preventDefault(); doSearch(); }
        });

        // ── Submit ────────────────────────────────────────────────────────────
        submitBtn.addEventListener('click', function () {
            var name   = (nameEl.value   || '').trim();
            var email  = (emailEl.value  || '').trim();
            var phone  = (phoneEl.value  || '').trim();
            var mobile = (mobileEl.value || '').trim();
            var pid    = parseInt(partnerIdEl.value) || 0;

            // Clear previous alert
            alertEl.className = 'd-none';
            alertEl.textContent = '';

            if (!name) {
                showAlert('Please enter your full name.');
                return;
            }
            if (!email && !phone && !mobile) {
                showAlert('Please provide at least one contact detail (email, phone, or mobile).');
                return;
            }

            submitBtn.disabled = true;
            submitBtn.textContent = 'Submitting…';

            rpc('/affiliate/apply', {
                name:       name,
                email:      email,
                phone:      phone,
                mobile:     mobile,
                partner_id: pid || false
            })
            .then(function (result) {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Submit Application';

                if (result && result.success) {
                    if (formEl)    formEl.classList.add('d-none');
                    if (stepLookup) stepLookup.classList.add('d-none');
                    successEl.classList.remove('d-none');
                    successMsg.textContent = result.message || 'Application submitted!';
                } else {
                    showAlert((result && result.error) || 'Something went wrong. Please try again.');
                }
            })
            .catch(function (err) {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Submit Application';
                showAlert(err.message || 'Connection error. Please try again.');
            });
        });
    }

    // Run after DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();

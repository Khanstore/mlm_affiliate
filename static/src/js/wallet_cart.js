/** @odoo-module **/
/**
 * MLM Wallet Cart Widget
 * FIX: Removed dead `import { rpc }` — file uses native fetch() throughout.
 */

document.addEventListener('DOMContentLoaded', function () {
    var applyBtn  = document.getElementById('mlm_apply_wallet');
    var removeBtn = document.getElementById('mlm_remove_wallet');
    var feedback  = document.getElementById('mlm_wallet_feedback');
    var payForm   = document.getElementById('mlm_wallet_pay_form');

    if (!applyBtn) { return; }

    applyBtn.addEventListener('click', function () {
        applyBtn.disabled = true;
        feedback.textContent = 'Applying…';

        fetch('/shop/wallet/apply', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Csrf-Token': _getCsrf(),
            },
            body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: {} }),
        })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            var result = data.result || {};
            if (result.error) {
                feedback.textContent = result.error;
                feedback.className = 'small text-danger ms-2';
                applyBtn.disabled = false;
                return;
            }
            applyBtn.classList.add('d-none');
            removeBtn.classList.remove('d-none');
            if (result.fully_covered) {
                feedback.textContent = 'Wallet covers the full order!';
                feedback.className = 'small text-success ms-2 fw-bold';
                if (payForm) { payForm.classList.remove('d-none'); }
            } else {
                feedback.textContent =
                    'Wallet credit applied. Remaining: ' +
                    parseFloat(result.remaining).toFixed(2);
                feedback.className = 'small text-info ms-2';
                setTimeout(function () { location.reload(); }, 1200);
            }
        })
        .catch(function () {
            feedback.textContent = 'Error. Please try again.';
            feedback.className = 'small text-danger ms-2';
            applyBtn.disabled = false;
        });
    });

    removeBtn.addEventListener('click', function () {
        fetch('/shop/wallet/remove', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Csrf-Token': _getCsrf(),
            },
            body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: {} }),
        })
        .then(function () { location.reload(); })
        .catch(function () { location.reload(); });
    });

    function _getCsrf() {
        var m = document.cookie.match(/csrf_token=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : '';
    }
});

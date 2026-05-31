# MLM Affiliate — Feature Roadmap
## v2.31 → v2.35+ Release Plan

---

## Current State (v2.30 / v2.18.0)

| Feature | Status |
|---|---|
| Multi-level commission engine (n-level) | ✅ Live |
| Affiliate wallet + checkout integration | ✅ Live |
| Payout request workflow (portal + admin) | ✅ Live |
| Commission hold period (fraud protection) | ✅ Live |
| Refund clawback on credit notes | ✅ Live |
| Tier auto-assignment (earnings + referrals) | ✅ Live |
| Milestone bonuses | ✅ Live |
| Campaign/promo code multipliers | ✅ Live |
| Accounting integration (journal entries) | ✅ Live |
| Referral link + QR code | ✅ Live |
| Leaderboard (top 10) | ✅ Live |
| Downline tree view | ✅ Live |
| Monthly summary emails | ✅ Live |
| Pricelist-based commission rules | ✅ Live |
| Self-referral prevention | ✅ Live |
| Affiliate application approval flow | ✅ Live |

---

## v2.31 — Analytics & Reporting Dashboard
**Target: Next release**

### What's missing right now
Admins have no consolidated view of MLM performance. There's no way to see total commissions paid per month, best-performing affiliates over time, or conversion rates from clicks to orders — without running manual reports.

### Features

**1. MLM Analytics Dashboard (Backend)**
- Summary KPI cards: Total commissions paid (MTD/YTD), Active affiliates, Avg commission per order, Wallet balance outstanding
- Line chart: Monthly commission payout trend (last 12 months)
- Bar chart: Top 10 affiliates by earnings (switchable: MTD / YTD / All time)
- Funnel: Referral clicks → confirmed orders → paid commissions (conversion rate)
- Pie: Commission by payout method (wallet / bank / coupon)

**2. Affiliate Performance Report**
- New menu: MLM Affiliate > Reports > Affiliate Performance
- Filterable by: Date range, Tier, Status, Payout method
- Columns: Affiliate, Tier, Direct referrals, Orders referred, Commission earned, Commission paid, Wallet balance, Conversion rate
- Export to XLSX and PDF

**3. Commission Ledger Report**
- Full audit trail: every commission record with order, product, level, amount, status, dates
- Groupable by: Affiliate / Month / Product / Level
- Useful for accounting reconciliation

**4. Portal: Enhanced Affiliate Dashboard**
- Replace current basic portal with full analytics view
- MTD earnings card, total lifetime earnings, pending vs approved split
- Referral click count and conversion rate shown to affiliate
- Monthly earnings bar chart (last 6 months)
- Tier progress bar: "You need $X more to reach Gold"

**Implementation notes:**
- Use `ir.actions.report` for PDF exports
- Use `xlsxwriter` for XLSX exports
- Dashboard uses `web.assets_backend` JS with Chart.js (already available in Odoo 18)
- Portal charts: use inline SVG or Chart.js via `web.assets_frontend`

**Version bump:** 18.0.2.19.0

---

## v2.32 — Promo Code Engine (Buyer-Facing Discounts)
**Target: 2 releases after v2.31**

### What's missing right now
Campaigns have a `promo_code` field but it's not wired to anything. Buyers cannot enter a code at checkout to get a discount, and affiliates cannot share actual working discount codes.

### Features

**1. Promo Code Model (`mlm.promo.code`)**
```
Fields:
  code (char, unique, required)
  affiliate_id (Many2one res.partner, required)
  campaign_id (Many2one mlm.campaign, optional)
  discount_type (selection: percent / fixed)
  discount_value (float)
  max_uses (integer, 0 = unlimited)
  uses_count (integer, computed)
  valid_from / valid_until (Date)
  active (boolean)
  single_use_per_customer (boolean)
```

**2. Checkout Integration**
- Promo code input box on website checkout (before payment step)
- Validates: code exists, not expired, uses remaining, customer hasn't used it if single-use
- Applies discount as an order line (similar to wallet discount line)
- Records which affiliate's code was used → sets `referrer_partner_id` if not already set
- One code per order (replacing any existing code)

**3. Auto-generate codes for campaigns**
- When a campaign is created, optionally auto-generate a unique promo code
- Admin can share code with affiliate, or affiliate sees it on their portal

**4. Promo Code Report**
- Usage report: code, affiliate, uses, total discount given, revenue generated from code

**Implementation notes:**
- Promo code discount line: use same pattern as wallet discount line (SQL protect from ORM resets)
- Portal: show affiliate's active promo codes with copy button

**Version bump:** 18.0.2.20.0

---

## v2.33 — Multi-Company & Multi-Currency Support
**Target: 3 releases after v2.31**

### What's missing right now
The module assumes a single company and single currency. Multi-company Odoo setups will have commission records mixing currencies, and wallet balances will be unreliable across companies.

### Features

**1. Company-scoped commission rules**
- Add `company_id` field to `product.commission.rule` and `mlm.level.rate`
- Commission engine filters rules by `env.company`
- Settings stored per-company via `ir.config_parameter` with company suffix

**2. Multi-currency commission amounts**
- `mlm.commission` already has `currency_id` from `order_id`
- Wallet balance compute: convert all currencies to partner's primary currency using `res.currency._convert()`
- Payout requests: show amount in request currency + company currency equivalent

**3. Cross-company affiliate networks**
- Option: allow an affiliate registered in Company A to earn commissions on sales in Company B
- Controlled by a new setting: `mlm_affiliate.cross_company_enabled`
- Cross-company commissions use the selling company's currency

**4. Wallet spend limited to order currency**
- Currently wallet can be spent regardless of order currency
- Add currency check: wallet can only be spent when order currency matches wallet currency (or add conversion)

**Version bump:** 18.0.2.21.0

---

## v2.34 — Automated Payout Processing
**Target: 4 releases after v2.31**

### What's missing right now
Paying out commissions is 100% manual. Admin clicks "Mark as Paid" one by one. There's no integration with bank transfers, no batch processing, and no receipt sent to affiliates.

### Features

**1. Batch Payout Processing**
- New action on payout requests list: "Process Selected Payouts"
- Validates: approved status, minimum threshold, bank account populated
- Creates a batch payment in `account.payment` (one payment per affiliate)
- Marks all included commissions as Paid
- Posts a confirmation message to each payout request

**2. Bank Transfer Export**
- Export approved payout requests as a bank transfer file
- Formats: SEPA XML (ISO 20022), CSV for manual upload
- Admin downloads file, uploads to online banking

**3. Automatic Payout Scheduling**
- New setting: `mlm_affiliate.auto_payout_schedule` (None / Weekly / Monthly)
- Cron job runs on schedule, finds all approved commissions above threshold for affiliates with `payout_method = 'bank'`, creates payout requests automatically, and notifies admin for review

**4. Payout Receipt Emails**
- When a payout request is marked Paid, send a detailed receipt to affiliate
- Shows: amount, commissions included, bank account used, date
- PDF attachment with official receipt format

**Version bump:** 18.0.2.22.0

---

## v2.35 — Loyalty Points Integration & Gamification
**Target: 5 releases after v2.31**

### What's missing right now
The product model has `mlm_loyalty_enabled` and `mlm_loyalty_program_id` fields but no logic wires them to Odoo's loyalty/eWallet system. Gamification (badges, streaks, challenges) doesn't exist.

### Features

**1. Loyalty Points Payout Method**
- Wire `mlm_loyalty_enabled` to commission creation
- When a commission is approved for a product with loyalty enabled, credit loyalty points instead of (or in addition to) wallet
- Uses `loyalty.card` model in Odoo 18 to add points
- Affiliate portal shows loyalty points balance alongside wallet balance

**2. Affiliate Badges**
- New model: `mlm.affiliate.badge` (name, icon, description, criteria_type, criteria_value)
- Criteria types: first_referral, 10_referrals, 50_referrals, first_commission, 1000_earned, top_leaderboard
- Auto-awarded on tier update and commission approval
- Shown on affiliate portal profile and in backend partner form

**3. Referral Streak Bonuses**
- Track consecutive months with at least 1 referred sale
- Streak multiplier: 2 months = 1.05x, 3 = 1.1x, 6 = 1.2x, 12 = 1.5x
- Streak resets if a month has 0 referred sales
- Shown on affiliate dashboard: "🔥 3-month streak — you earn 10% extra this month"

**4. Leaderboard Prizes**
- Admin can configure prize commissions for leaderboard positions
- End-of-month cron: top 3 affiliates get bonus milestone commissions
- Prize amounts configurable in Settings > MLM > Leaderboard Prizes

**Version bump:** 18.0.2.23.0

---

## Odoo App Store Submission Checklist (v2.31+)

### Required for listing
- [ ] `static/description/index.html` — full module description page
- [ ] `static/description/icon.png` — 128×128px, already present ✅
- [ ] Screenshots in `static/description/` — at minimum 3, recommended 6–8
- [ ] `README.rst` — already present ✅
- [ ] License set to `LGPL-3` — already set ✅
- [ ] `author` field updated to your company/name
- [ ] `website` field added to manifest
- [ ] `support` field added to manifest (email or URL)
- [ ] Price set (free or paid) in partner portal

### Screenshots to prepare (6 recommended)
1. Affiliate Portal Dashboard — earnings chart, wallet balance, referral link
2. Admin Commission List — kanban/list with status badges
3. MLM Settings page — all three accounting fields filled
4. Downline Tree View — multi-level affiliate hierarchy
5. Tier Configuration — Bronze/Silver/Gold with thresholds
6. Payout Request — portal submission form

### Description page `index.html` sections
1. Hero banner with module name + tagline
2. Feature highlights (icons + short descriptions)
3. Screenshots gallery
4. How it works (numbered steps)
5. Configuration quick-start
6. Compatibility: Odoo 18 Community & Enterprise

### Manifest updates needed
```python
'author': 'Your Company Name',
'website': 'https://yourwebsite.com',
'support': 'support@yourwebsite.com',
'price': 0,  # or your price
'currency': 'USD',
'live_test_url': 'https://demo.yourwebsite.com',
```

---

## Technical Debt / Bug Fixes (any version)

| Issue | Priority | Notes |
|---|---|---|
| `mlm_member.py` is empty | High | Either implement or remove from `__init__.py` |
| `product_template.py` has duplicate `_inherit = 'product.template'` — also defined in `product_commission_rule.py` | High | Will cause ORM conflict; consolidate into one file |
| `MLMProductCommission` model in `product_template.py` not referenced in any menu/view | Medium | Either wire it up or remove |
| Wallet balance compute doesn't handle draft/cancelled wallet orders consistently | Medium | Should exclude `cancelled` orders |
| `_mlm_reapply_wallet_line_sql` missing `_logger` import in `sale_order.py` | Low | Will throw `NameError` on exception |
| Campaign `get_active_campaign` is a `def` not decorated `@api.model` | Low | Should be `@api.model` for correctness |
| Portal chart uses inline SVG — migrate to Chart.js for consistency | Low | Cosmetic |


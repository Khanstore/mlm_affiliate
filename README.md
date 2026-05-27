# MLM Affiliate Referral — Odoo 18 Module

**Version:** 18.0.1.0.0  
**Depends:** `website_sale`, `sale_management`, `portal`

---

## Overview

This module adds a full **multi-level marketing (MLM) affiliate referral system** to your Odoo 18 eCommerce site.  
Every customer or approved affiliate gets a unique referral link. When someone clicks that link and completes a purchase, the system automatically calculates and records commissions up the entire MLM upline chain — at rates you configure per product, per level.

---

## How It Works (End-to-End Flow)

```
Affiliate shares link  →  Visitor clicks  →  Cookie set (30 days)
         ↓
Visitor adds to cart / checks out
         ↓
Referrer attached to sale order
         ↓
Admin confirms order  →  Commission records created for every upline level
         ↓
Admin approves & pays commissions  →  Wallet / Bank / Coupon
```

---

## Features

| Feature | Details |
|---|---|
| Referral links | `/ref/CODE` (pretty) or `?ref=CODE` (any URL) |
| Cookie lifetime | 30 days |
| MLM depth | Unlimited levels (configurable per product) |
| Commission types | Percentage (%) or Fixed amount — per product per level |
| Payout methods | Wallet credit, Bank transfer, Discount coupon |
| Commission states | Pending → Approved → Paid (or Cancelled) |
| Affiliate portal | Dashboard with stats, link, history, downline |
| Admin panel | Dedicated **MLM Affiliate** top menu |

---

## Installation

1. Copy the `mlm_affiliate` folder into your Odoo addons path (e.g. `custom_addons/`).
2. Restart the Odoo server.
3. Go to **Settings → Apps → Update App List**.
4. Search for **MLM Affiliate Referral** and click **Install**.

---

## Configuration

### Step 1 — Set Commission Rules on Products

1. Go to any product form (**Sales → Products** or **Website → Products**).
2. Open the **Commission Rules** tab.
3. Add one row per MLM level:

| Level | Type | Value | Meaning |
|---|---|---|---|
| 1 | Percentage | 10 | Direct referrer earns 10% of line subtotal |
| 2 | Percentage | 5  | Upline earns 5% |
| 3 | Fixed | 2.00 | Great-upline earns $2.00 flat |
| 4 | Percentage | 1  | Level 4 earns 1% |

> **Tip:** You only need to add levels you want to pay. If Level 3 has no rule, no commission is created at that level — the chain still continues upward.

### Step 2 — Create Affiliates

**Option A — Manually:**
1. Open **Contacts** → find or create a partner.
2. Open the **Affiliate / MLM** tab.
3. Tick **Is Affiliate**.
4. Click **Generate Referral Code** (auto-generated if left blank).
5. Copy the **Referral Link** and give it to the affiliate.

**Option B — Self-enrol:**
Any logged-in customer who visits `/affiliate/dashboard` automatically gets a referral code assigned.

### Step 3 — Build the Upline Chain

For each affiliate, open their contact form → **Affiliate / MLM** tab → set **Referred By (Upline)** to whoever recruited them.  
This defines which partners receive Level 2, 3, 4+ commissions.

### Step 4 — Share Links

The affiliate's referral link looks like:
```
https://yoursite.com/ref/ABC12345
```
It can also be appended to any product or category URL:
```
https://yoursite.com/shop/product-name?ref=ABC12345
```
Both work — the cookie is set either way.

---

## Admin Workflow — Approving & Paying Commissions

### All Commissions
Go to **MLM Affiliate → Commissions → All Commissions**.

Each commission record shows:
- Who earned it (affiliate)
- Which order triggered it
- Which product on that order
- MLM Level
- Amount
- Current state

### Bulk Approve
1. Filter by **Pending**.
2. Select all rows (checkbox in header).
3. Click **Action → Approve** — or use the green ✓ button per row.

### Mark as Paid
After approving, select commissions and click **Mark Paid**.  
- **Wallet:** balance is added to the affiliate's wallet on their contact record.
- **Bank:** change payout method to Bank on the form before marking paid; record the transfer manually.
- **Discount Coupon:** a unique coupon code (e.g. `AFF-X7KP2M3Q`) is auto-generated; share it with the affiliate.

### Change Payout Method
Open any commission form → change **Payout Method** before clicking Mark as Paid.

---

## Affiliate Portal Dashboard

Affiliates access their dashboard at:
```
https://yoursite.com/affiliate/dashboard
```
Or via **My Account → Affiliate Dashboard**.

The dashboard shows:
- **Referral Link** with one-click copy button
- **Stats cards:** Pending / Approved / Paid / Wallet Balance
- **Commission history table** (latest 50)
- **My Direct Referrals** — list of people they recruited

---

## Sale Order — Referrer Tracking

On any sale order, open the **Other Info** tab:
- **Referred By** — the affiliate whose link was used
- **Referral Code Used** — the exact code from the cookie
- **Total Commissions** — sum of all commission records for this order
- **Commissions smart button** — opens all commission records for this order

---

## Backend Menu Structure

```
MLM Affiliate
├── Commissions
│   ├── All Commissions     (list + graph + pivot)
│   └── Pending Approval    (filtered list)
├── Network
│   └── Affiliates          (filtered contact list)
└── Configuration
    └── Commission Rules    (global rule browser)
```

---

## Models Reference

| Model | Description |
|---|---|
| `product.commission.rule` | Commission rate per product per level |
| `mlm.commission` | Individual commission earned record |
| `res.partner` (extended) | referral_code, upline, wallet, downline |
| `sale.order` (extended) | referrer_partner_id, commission_ids |

---

## Routes

| URL | Auth | Purpose |
|---|---|---|
| `/ref/<code>` | public | Sets cookie, redirects to /shop |
| `/affiliate/dashboard` | user (portal/internal) | Affiliate stats page |

---

## Frequently Asked Questions

**Q: What happens if the same customer clicks two different referral links?**  
A: The most recent click wins — the cookie is overwritten with the latest code.

**Q: Can a customer refer themselves?**  
A: No. The system checks `partner != order.partner_id` before attaching the referrer.

**Q: What if there is no commission rule for a level?**  
A: That level is skipped silently. The chain continues upward to the next level.

**Q: What is the maximum MLM depth?**  
A: There is a safety cap of 20 levels to prevent infinite loops. You can increase this in `models/sale_order.py` (`MAX_LEVELS = 20`).

**Q: When are commissions created?**  
A: When the sale order state changes to **Sale Order** (confirmed). Draft and cancelled orders do not generate commissions.

**Q: Can I re-generate commissions if I made a mistake?**  
A: Cancel the existing commissions via the form, then manually call `order._generate_mlm_commissions()` from the Odoo shell, or unconfirm/reconfirm the order if your workflow allows.

---

## Technical Notes

- Tested on **Odoo 18 Community & Enterprise**.
- Does **not** use deprecated `attrs=` / `states=` syntax (Odoo 17+ compliant).
- Referral cookie: `mlm_ref`, `HttpOnly`, `SameSite=Lax`, 30-day expiry.
- JS tracker (`referral_tracker.js`) handles `?ref=` in any URL without a server round-trip.

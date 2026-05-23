MLM Affiliate Referral — Odoo 18 Module
========================================

**Version:** 18.0.2.0.0

**Depends:** ``website_sale``, ``sale_management``, ``portal``

Overview
--------

This module adds a full **multi-level marketing (MLM) affiliate referral system**
to your Odoo 18 eCommerce site.

Every customer or approved affiliate gets a unique referral link. When someone
clicks that link and completes a purchase, the system automatically calculates
and records commissions up the entire MLM upline chain — at rates you configure
per product, per level.

How It Works (End-to-End Flow)
-------------------------------

1. Affiliate shares link → Visitor clicks → Cookie set (30 days)
2. Visitor adds to cart / checks out
3. Referrer is attached to the sale order
4. Admin confirms order → Commission records created for every upline level
5. Admin approves & pays commissions → Wallet / Bank / Coupon

Features
--------

- **Referral links:** ``/ref/CODE`` (pretty) or ``?ref=CODE`` (any URL)
- **Cookie lifetime:** 30 days
- **MLM depth:** Unlimited levels (configurable per product)
- **Commission types:** Percentage (%) or Fixed amount — per product per level
- **Payout methods:** Wallet credit, Bank transfer, Discount coupon
- **Commission states:** Pending → Approved → Paid (or Cancelled)
- **Affiliate portal:** Dashboard with stats, link, history, downline
- **Admin panel:** Dedicated **MLM Affiliate** top menu

Installation
------------

1. Copy the ``mlm_affiliate`` folder into your Odoo addons path (e.g. ``custom_addons/``).
2. Restart the Odoo server.
3. Go to **Settings → Apps → Update App List**.
4. Search for **MLM Affiliate Referral** and click **Install**.

Configuration
-------------

Step 1 — Set Commission Rules on Products
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Go to any product form (**Sales → Products** or **Website → Products**).
2. Open the **Commission Rules** tab.
3. Add one row per MLM level (e.g. Level 1 = 10%, Level 2 = 5%, etc.).

.. note::
   You only need to add levels you want to pay. If a level has no rule,
   no commission is created at that level — the chain still continues upward.

Step 2 — Create Affiliates
~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Option A — Manually:**

1. Open **Contacts** → find or create a partner.
2. Open the **Affiliate / MLM** tab.
3. Tick **Is Affiliate**.
4. Click **Generate Referral Code** (auto-generated if left blank).
5. Copy the **Referral Link** and give it to the affiliate.

**Option B — Self-enrol:**

Any logged-in customer who visits ``/affiliate/dashboard`` automatically
gets a referral code assigned.

Step 3 — Build the Upline Chain
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For each affiliate, open their contact form → **Affiliate / MLM** tab →
set **Referred By (Upline)** to whoever recruited them. This defines which
partners receive Level 2, 3, 4+ commissions.

Step 4 — Share Links
~~~~~~~~~~~~~~~~~~~~~

The affiliate's referral link looks like::

    https://yoursite.com/ref/ABC12345

It can also be appended to any product or category URL::

    https://yoursite.com/shop/product-name?ref=ABC12345

Admin Workflow — Approving & Paying Commissions
------------------------------------------------

Go to **MLM Affiliate → Commissions → All Commissions**.

- Filter by **Pending**, select rows, click **Action → Approve**.
- After approving, select commissions and click **Mark Paid**.

  - **Wallet:** balance is added to the affiliate's wallet.
  - **Bank:** change payout method to Bank before marking paid; record the transfer manually.
  - **Discount Coupon:** a unique coupon code is auto-generated and shared with the affiliate.

Affiliate Portal Dashboard
--------------------------

Affiliates access their dashboard at ``/affiliate/dashboard`` or via
**My Account → Affiliate Dashboard**. The dashboard shows:

- Referral link with one-click copy button
- Stats cards: Pending / Approved / Paid / Wallet Balance
- Commission history table (latest 50)
- My Direct Referrals — list of recruited members

Backend Menu Structure
----------------------

::

    MLM Affiliate
    ├── Commissions
    │   ├── All Commissions
    │   └── Pending Approval
    ├── Network
    │   └── Affiliates
    └── Configuration
        └── Commission Rules

Models Reference
----------------

- ``product.commission.rule`` — Commission rate per product per level
- ``mlm.commission`` — Individual commission earned record
- ``res.partner`` (extended) — referral_code, upline, wallet, downline
- ``sale.order`` (extended) — referrer_partner_id, commission_ids

Routes
------

- ``/ref/<code>`` (public) — Sets cookie, redirects to /shop
- ``/affiliate/dashboard`` (portal/internal) — Affiliate stats page

Frequently Asked Questions
--------------------------

**Q: What happens if the same customer clicks two different referral links?**

The most recent click wins — the cookie is overwritten with the latest code.

**Q: Can a customer refer themselves?**

No. The system checks ``partner != order.partner_id`` before attaching the referrer.

**Q: What if there is no commission rule for a level?**

That level is skipped silently. The chain continues upward to the next level.

**Q: What is the maximum MLM depth?**

There is a safety cap of 20 levels to prevent infinite loops. You can increase
this in ``models/sale_order.py`` (``MAX_LEVELS = 20``).

**Q: When are commissions created?**

When the sale order state changes to **Sale Order** (confirmed). Draft and
cancelled orders do not generate commissions.

Technical Notes
---------------

- Tested on **Odoo 18 Community & Enterprise**.
- Does **not** use deprecated ``attrs=`` / ``states=`` syntax (Odoo 17+ compliant).
- Referral cookie: ``mlm_ref``, ``HttpOnly``, ``SameSite=Lax``, 30-day expiry.
- JS tracker (``referral_tracker.js``) handles ``?ref=`` in any URL without a server round-trip.

{
    'name': 'MLM Affiliate',
    'version': '18.0.2.18.0',
    'category': 'Sales/Affiliate',
    'summary': 'Multi-level affiliate commissions with wallet, accounting, campaigns, milestones and fraud protection.',
    'description': """
MLM Affiliate Module — Odoo 18
==============================
Features:
- Multi-level commission engine with pricelist-based rules
- Commission auto-approval on invoice payment
- Refund clawback: commissions cancelled on validated credit notes
- Commission hold period (configurable return/refund window)
- Self-referral prevention and affiliate application approval flow
- Affiliate wallet: balance usable to pay online orders at checkout
- Payout request workflow (portal submission + admin approve/pay)
- Accounting integration: approved commissions create expense journal entries
  (Debit: MLM Commission Expense / Credit: MLM Commissions Payable)
- Campaign/promo codes with boosted commission multipliers per affiliate
- Milestone bonuses: automatic one-time rewards on earnings/referral thresholds
- Affiliate tiers auto-assigned by earnings + referral count
- Monthly earnings trend chart on affiliate portal
- Leaderboard (top 10 affiliates)
- Downline tree view
- Referral link click tracking + QR code
- Monthly summary emails (toggleable)
    """,
    'website': 'https://www.khan-store.com/mlm',
    'author': 'Custom',
    'depends': [
        'sale_management',
        'account',
        'website_sale',
        'portal',
        'auth_signup',
        'mail',
        'base_setup',
    ],
    'data': [
        # Security
        'security/mlm_security.xml',
        'security/ir.model.access.csv',
        'security/mlm_record_rules.xml',
        # Data
        'data/sequence_data.xml',
        'data/wallet_discount_product.xml',
        'data/mlm_level_rate_data.xml',
        'data/mlm_accounting_data.xml',
        'data/cron_data.xml',
        'data/mail_templates.xml',
        # Backend views
        'views/mlm_commission_views.xml',
        'views/mlm_payout_request_views.xml',
        'views/mlm_campaign_milestone_views.xml',
        'views/mlm_affiliate_tier_views.xml',
        'views/mlm_level_rate_views.xml',
        'views/mlm_leaderboard_views.xml',
        'views/res_partner_views.xml',
        'views/mlm_settings_views.xml',
        'views/product_commission_rule_views.xml',
        'views/product_template_views.xml',
        'views/product_category_views.xml',
        'views/sale_order_views.xml',
        # Website / portal
        'views/website_sale_wallet.xml',
        'views/portal_affiliate_views.xml',
        'views/og_redirect_template.xml',
        'views/website_templates.xml',
        # Menus (must be last — references all actions)
        'views/menus.xml',
    ],
    'pre_init_hook': 'pre_init_hook',
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
    'images': ['static/description/icon.png'],
}

{
    'name': 'MLM Affiliate Referral',
    'version': '18.0.1.0.0',
    'category': 'Website/eCommerce',
    'summary': 'Multi-level affiliate referral commissions for Odoo 18 eCommerce',
    'author': 'Custom Development',
    'depends': [
        'website_sale',
        'sale_management',
        'portal',
        'mail',
        'auth_signup',   # required: hook into signup to auto-link downline
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/sequence_data.xml',
        'views/product_commission_rule_views.xml',
        'views/res_partner_views.xml',
        'views/mlm_commission_views.xml',
        'views/product_template_views.xml',
        'views/portal_affiliate_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'mlm_affiliate/static/src/js/referral_tracker.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}

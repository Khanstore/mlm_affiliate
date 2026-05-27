# FIX-1: replaced partner.mlm_code (non-existent) with partner.referral_code
# FIX-2: replaced request.httprequest.base_url with ir.config_parameter
#         so this helper is safe outside HTTP context (crons, server actions).
from urllib.parse import urlencode
from odoo import api, models


class MLMLinkBuilder(models.AbstractModel):
    _name = "mlm.link.builder"
    _description = "MLM Link Builder"

    @api.model
    def product_tracking_url(self, product, partner):
        base_url = (
            self.env['ir.config_parameter']
            .sudo()
            .get_param('web.base.url', '')
            .rstrip('/')
        )
        product_url = f"{base_url}/odoo/products/{product.id}"
        return "%s?%s" % (product_url, urlencode({"ref": partner.referral_code}))

    @api.model
    def facebook_share_url(self, url):
        return "https://www.facebook.com/sharer/sharer.php?%s" % urlencode({"u": url})

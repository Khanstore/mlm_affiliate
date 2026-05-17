from urllib.parse import urlencode

from odoo import api, models
from odoo.http import request


class MLMLinkBuilder(models.AbstractModel):
    _name = "mlm.link.builder"
    _description = "MLM Link Builder"

    @api.model
    def product_tracking_url(self, product, partner):
        base_url = request.httprequest.base_url
        return "%s?%s" % (base_url, urlencode({"mlm_ref": partner.mlm_code}))

    @api.model
    def facebook_share_url(self, url):
        return "https://www.facebook.com/sharer/sharer.php?%s" % urlencode({"u": url})

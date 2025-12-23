# -*- coding: utf-8 -*-

from odoo import models, fields, api, _


class Website(models.Model):
    """
    Extend website for ResellerClub multi-website support.

    Allows configuring which websites use ResellerClub integration
    and website-specific settings for domain search and checkout.
    """
    _inherit = 'website'

    # ResellerClub Integration Settings
    rc_enabled = fields.Boolean(
        string='Enable ResellerClub',
        default=False,
        help="Enable ResellerClub integration for this website"
    )
    rc_show_domain_search = fields.Boolean(
        string='Show Domain Search',
        default=True,
        help="Show domain search widget on the website"
    )
    rc_show_hosting_products = fields.Boolean(
        string='Show Hosting Products',
        default=True,
        help="Display hosting products in the shop"
    )
    rc_show_ssl_products = fields.Boolean(
        string='Show SSL Products',
        default=True,
        help="Display SSL certificate products in the shop"
    )

    # Domain Search Settings
    rc_default_tlds = fields.Char(
        string='Default TLDs',
        default='com,net,org,info,co',
        help="Comma-separated list of default TLDs to search (e.g., com,net,org)"
    )
    rc_featured_tlds = fields.Char(
        string='Featured TLDs',
        default='com,net,org',
        help="Comma-separated list of featured TLDs shown prominently"
    )
    rc_search_results_limit = fields.Integer(
        string='Search Results Limit',
        default=20,
        help="Maximum number of domain suggestions to show"
    )

    # Display Settings
    rc_show_domain_prices = fields.Boolean(
        string='Show Domain Prices',
        default=True,
        help="Display domain prices in search results"
    )
    rc_show_whois_privacy = fields.Boolean(
        string='Offer WHOIS Privacy',
        default=True,
        help="Offer WHOIS privacy protection during checkout"
    )
    rc_show_auto_renew = fields.Boolean(
        string='Show Auto-Renew Option',
        default=True,
        help="Show auto-renewal option during checkout"
    )

    # Checkout Settings
    rc_require_customer_info = fields.Boolean(
        string='Require Customer Info',
        default=True,
        help="Require complete customer information for domain registration"
    )
    rc_default_registration_years = fields.Integer(
        string='Default Registration Years',
        default=1,
        help="Default registration period in years"
    )
    rc_max_registration_years = fields.Integer(
        string='Max Registration Years',
        default=10,
        help="Maximum registration period in years"
    )

    # Product Categories for this website
    rc_domain_category_id = fields.Many2one(
        'product.public.category',
        string='Domain Category',
        help="Website category for domain products"
    )
    rc_hosting_category_id = fields.Many2one(
        'product.public.category',
        string='Hosting Category',
        help="Website category for hosting products"
    )
    rc_ssl_category_id = fields.Many2one(
        'product.public.category',
        string='SSL Category',
        help="Website category for SSL products"
    )

    def _get_default_tlds_list(self):
        """Return list of default TLDs for domain search."""
        self.ensure_one()
        if self.rc_default_tlds:
            return [t.strip().lower() for t in self.rc_default_tlds.split(',') if t.strip()]
        return ['com', 'net', 'org', 'info', 'biz', 'co']

    def _get_featured_tlds_list(self):
        """Return list of featured TLDs."""
        self.ensure_one()
        if self.rc_featured_tlds:
            return [t.strip().lower() for t in self.rc_featured_tlds.split(',') if t.strip()]
        return ['com', 'net', 'org']

    def get_rc_domain_products(self):
        """Get domain products available on this website."""
        self.ensure_one()
        domain = [
            ('is_resellerclub_product', '=', True),
            ('rc_product_type', '=', 'domain'),
            ('is_published', '=', True),
            ('website_id', 'in', [False, self.id]),
        ]
        return self.env['product.template'].search(domain)

    def get_rc_hosting_products(self):
        """Get hosting products available on this website."""
        self.ensure_one()
        domain = [
            ('is_resellerclub_product', '=', True),
            ('rc_product_type', 'in', ['hosting_single', 'hosting_multi', 'hosting_reseller']),
            ('is_published', '=', True),
            ('website_id', 'in', [False, self.id]),
        ]
        return self.env['product.template'].search(domain)

    def get_rc_ssl_products(self):
        """Get SSL products available on this website."""
        self.ensure_one()
        domain = [
            ('is_resellerclub_product', '=', True),
            ('rc_product_type', '=', 'ssl'),
            ('is_published', '=', True),
            ('website_id', 'in', [False, self.id]),
        ]
        return self.env['product.template'].search(domain)

    def get_tld_pricing(self):
        """Get TLD pricing for display on the website."""
        self.ensure_one()
        products = self.get_rc_domain_products()
        pricing = []
        for product in products:
            if product.rc_tld:
                pricing.append({
                    'tld': product.rc_tld,
                    'name': product.name,
                    'price': product.list_price,
                    'product_id': product.id,
                    'is_featured': product.rc_tld in self._get_featured_tlds_list(),
                })
        # Sort: featured first, then by TLD name
        pricing.sort(key=lambda x: (not x['is_featured'], x['tld']))
        return pricing

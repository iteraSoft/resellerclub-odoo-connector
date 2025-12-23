# -*- coding: utf-8 -*-

import json
import logging
from odoo import http, fields, _
from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale

_logger = logging.getLogger(__name__)


class ResellerClubWebsite(http.Controller):
    """
    Website controller for ResellerClub integration.

    Provides domain search, availability check, and custom checkout
    functionality for domain, hosting, and SSL products.
    """

    # ==========================================
    # DOMAIN SEARCH PAGE
    # ==========================================

    @http.route(['/domains', '/domain-search'], type='http', auth='public', website=True)
    def domain_search_page(self, **kwargs):
        """Display the domain search page."""
        website = request.website

        if not website.rc_enabled:
            return request.redirect('/shop')

        values = self._prepare_domain_search_values(kwargs)
        return request.render('resellerclub_integration.domain_search_page', values)

    def _prepare_domain_search_values(self, kwargs):
        """Prepare values for domain search template."""
        website = request.website
        return {
            'search_query': kwargs.get('domain', ''),
            'default_tlds': website._get_default_tlds_list(),
            'featured_tlds': website._get_featured_tlds_list(),
            'tld_pricing': website.get_tld_pricing(),
            'show_prices': website.rc_show_domain_prices,
            'max_years': website.rc_max_registration_years,
            'default_years': website.rc_default_registration_years,
        }

    # ==========================================
    # DOMAIN AVAILABILITY API (PUBLIC)
    # ==========================================

    @http.route('/domains/check', type='json', auth='public', website=True, methods=['POST'])
    def check_domain_availability_public(self, domain_name, tlds=None, **kwargs):
        """
        Public endpoint for domain availability check.

        :param domain_name: Domain name without TLD (e.g., 'example')
        :param tlds: List of TLDs to check
        :return: Availability results with pricing
        """
        website = request.website

        if not website.rc_enabled:
            return {'success': False, 'error': 'Domain search not enabled'}

        if not domain_name or len(domain_name) < 2:
            return {'success': False, 'error': 'Please enter a valid domain name'}

        # Clean the domain name
        domain_name = self._clean_domain_name(domain_name)

        # Get TLDs to check
        if not tlds:
            tlds = website._get_default_tlds_list()
        elif isinstance(tlds, str):
            tlds = [t.strip() for t in tlds.split(',') if t.strip()]

        try:
            api = request.env['resellerclub.api'].sudo()
            results = api.domain_check_availability(domain_name, tlds)

            # Enrich results with pricing from our products
            enriched_results = self._enrich_availability_results(results, tlds)

            return {
                'success': True,
                'domain_name': domain_name,
                'results': enriched_results,
            }

        except Exception as e:
            _logger.error("Domain availability check failed: %s", str(e))
            return {'success': False, 'error': _('Unable to check domain availability')}

    @http.route('/domains/suggest', type='json', auth='public', website=True, methods=['POST'])
    def suggest_domains_public(self, keyword, **kwargs):
        """
        Public endpoint for domain name suggestions.

        :param keyword: Keyword for suggestions
        :return: List of suggested domain names
        """
        website = request.website

        if not website.rc_enabled:
            return {'success': False, 'error': 'Domain search not enabled'}

        if not keyword or len(keyword) < 2:
            return {'success': False, 'error': 'Please enter a valid keyword'}

        try:
            api = request.env['resellerclub.api'].sudo()
            tlds = website._get_default_tlds_list()
            suggestions = api.domain_suggest_names(keyword, tlds[:5])

            # Limit results
            limit = website.rc_search_results_limit or 20
            suggestions = suggestions[:limit] if suggestions else []

            return {
                'success': True,
                'keyword': keyword,
                'suggestions': suggestions,
            }

        except Exception as e:
            _logger.error("Domain suggestion failed: %s", str(e))
            return {'success': False, 'error': _('Unable to get domain suggestions')}

    @http.route('/domains/pricing', type='json', auth='public', website=True, methods=['POST'])
    def get_tld_pricing_public(self, tlds=None, **kwargs):
        """
        Get pricing for TLDs.

        :param tlds: Optional list of TLDs to get pricing for
        :return: Pricing information
        """
        website = request.website

        if not website.rc_enabled:
            return {'success': False, 'error': 'Domain search not enabled'}

        pricing = website.get_tld_pricing()

        if tlds:
            tlds_list = [t.strip().lower() for t in tlds.split(',')] if isinstance(tlds, str) else tlds
            pricing = [p for p in pricing if p['tld'] in tlds_list]

        return {
            'success': True,
            'pricing': pricing,
            'currency': request.env.company.currency_id.name,
            'currency_symbol': request.env.company.currency_id.symbol,
        }

    # ==========================================
    # ADD TO CART FUNCTIONALITY
    # ==========================================

    @http.route('/domains/add-to-cart', type='json', auth='public', website=True, methods=['POST'])
    def add_domain_to_cart(self, domain_name, tld, years=1, privacy=False, auto_renew=True, **kwargs):
        """
        Add a domain to the shopping cart.

        :param domain_name: The domain name without TLD
        :param tld: The TLD (com, net, etc.)
        :param years: Registration period in years
        :param privacy: Enable WHOIS privacy protection
        :param auto_renew: Enable auto-renewal
        :return: Cart update result
        """
        website = request.website

        if not website.rc_enabled:
            return {'success': False, 'error': 'Domain registration not enabled'}

        full_domain = f"{domain_name}.{tld}"

        # Find the product for this TLD
        product = request.env['product.product'].sudo().search([
            ('is_resellerclub_product', '=', True),
            ('rc_product_type', '=', 'domain'),
            ('rc_tld', '=', tld.lower()),
        ], limit=1)

        if not product:
            return {'success': False, 'error': _('Product not found for .%s domains') % tld}

        try:
            # Get or create sale order
            sale_order = request.website.sale_get_order(force_create=True)

            # Prepare order line values
            order_line_values = {
                'order_id': sale_order.id,
                'product_id': product.id,
                'product_uom_qty': years,
                'rc_service_domain': full_domain,
                'rc_service_type': 'domain_new',
                'name': _('Domain Registration: %s (%d year(s))') % (full_domain, years),
            }

            # Create the order line
            order_line = request.env['sale.order.line'].sudo().create(order_line_values)

            # Store additional domain options in the session for checkout
            if 'rc_domain_options' not in request.session:
                request.session['rc_domain_options'] = {}

            request.session['rc_domain_options'][str(order_line.id)] = {
                'domain': full_domain,
                'years': years,
                'privacy': privacy,
                'auto_renew': auto_renew,
            }

            return {
                'success': True,
                'message': _('Domain %s added to cart') % full_domain,
                'cart_quantity': sale_order.cart_quantity,
                'line_id': order_line.id,
            }

        except Exception as e:
            _logger.error("Failed to add domain to cart: %s", str(e))
            return {'success': False, 'error': str(e)}

    @http.route('/domains/configure', type='http', auth='public', website=True)
    def domain_configure_page(self, domain=None, tld=None, **kwargs):
        """
        Domain configuration page before adding to cart.

        Allows users to select registration years, privacy, nameservers, etc.
        """
        website = request.website

        if not website.rc_enabled or not domain or not tld:
            return request.redirect('/domains')

        full_domain = f"{domain}.{tld}"

        # Get the product for pricing
        product = request.env['product.product'].sudo().search([
            ('is_resellerclub_product', '=', True),
            ('rc_product_type', '=', 'domain'),
            ('rc_tld', '=', tld.lower()),
        ], limit=1)

        if not product:
            return request.redirect('/domains')

        # Get company default nameservers
        company = request.env.company
        default_nameservers = [
            company.resellerclub_default_ns1,
            company.resellerclub_default_ns2,
            company.resellerclub_default_ns3,
            company.resellerclub_default_ns4,
        ]
        default_nameservers = [ns for ns in default_nameservers if ns]

        values = {
            'domain_name': domain,
            'tld': tld,
            'full_domain': full_domain,
            'product': product,
            'price_per_year': product.list_price,
            'max_years': website.rc_max_registration_years,
            'default_years': website.rc_default_registration_years,
            'show_privacy': website.rc_show_whois_privacy,
            'show_auto_renew': website.rc_show_auto_renew,
            'default_nameservers': default_nameservers,
            'privacy_price': self._get_privacy_price(tld),
        }

        return request.render('resellerclub_integration.domain_configure_page', values)

    # ==========================================
    # HOSTING PRODUCTS PAGE
    # ==========================================

    @http.route('/hosting', type='http', auth='public', website=True)
    def hosting_products_page(self, **kwargs):
        """Display hosting products page."""
        website = request.website

        if not website.rc_enabled or not website.rc_show_hosting_products:
            return request.redirect('/shop')

        hosting_products = website.get_rc_hosting_products()

        # Group by hosting type
        products_by_type = {}
        for product in hosting_products:
            hosting_type = product.rc_product_type or 'other'
            if hosting_type not in products_by_type:
                products_by_type[hosting_type] = []
            products_by_type[hosting_type].append(product)

        values = {
            'products_by_type': products_by_type,
            'hosting_types': {
                'hosting_single': _('Single Domain Hosting'),
                'hosting_multi': _('Multi Domain Hosting'),
                'hosting_reseller': _('Reseller Hosting'),
                'email': _('Email Hosting'),
                'vps': _('VPS Servers'),
                'dedicated': _('Dedicated Servers'),
            },
        }

        return request.render('resellerclub_integration.hosting_products_page', values)

    # ==========================================
    # SSL PRODUCTS PAGE
    # ==========================================

    @http.route('/ssl-certificates', type='http', auth='public', website=True)
    def ssl_products_page(self, **kwargs):
        """Display SSL certificate products page."""
        website = request.website

        if not website.rc_enabled or not website.rc_show_ssl_products:
            return request.redirect('/shop')

        ssl_products = website.get_rc_ssl_products()

        # Group by SSL type
        products_by_type = {}
        for product in ssl_products:
            ssl_type = getattr(product, 'rc_ssl_type', 'standard') or 'standard'
            if ssl_type not in products_by_type:
                products_by_type[ssl_type] = []
            products_by_type[ssl_type].append(product)

        values = {
            'products_by_type': products_by_type,
            'ssl_types': {
                'dv': _('Domain Validation (DV)'),
                'ov': _('Organization Validation (OV)'),
                'ev': _('Extended Validation (EV)'),
                'wildcard': _('Wildcard SSL'),
                'multi': _('Multi-Domain SSL'),
            },
        }

        return request.render('resellerclub_integration.ssl_products_page', values)

    # ==========================================
    # HELPER METHODS
    # ==========================================

    def _clean_domain_name(self, domain_name):
        """Clean and normalize domain name input."""
        # Remove protocol if present
        if '://' in domain_name:
            domain_name = domain_name.split('://')[1]

        # Remove www. prefix
        if domain_name.startswith('www.'):
            domain_name = domain_name[4:]

        # Remove TLD if present (get just the name part)
        if '.' in domain_name:
            domain_name = domain_name.split('.')[0]

        # Remove invalid characters
        domain_name = ''.join(c for c in domain_name.lower() if c.isalnum() or c == '-')

        # Remove leading/trailing hyphens
        domain_name = domain_name.strip('-')

        return domain_name

    def _enrich_availability_results(self, api_results, tlds):
        """
        Enrich availability results with pricing from our products.

        :param api_results: Results from ResellerClub API
        :param tlds: List of TLDs checked
        :return: Enriched results with pricing
        """
        enriched = []
        website = request.website
        tld_pricing = {p['tld']: p for p in website.get_tld_pricing()}

        # Handle different API response formats
        if isinstance(api_results, dict):
            for key, value in api_results.items():
                # Parse domain.tld format
                if '.' in key:
                    parts = key.rsplit('.', 1)
                    domain = parts[0]
                    tld = parts[1].lower()
                else:
                    continue

                # Determine availability
                available = False
                status = 'unknown'
                if isinstance(value, dict):
                    status = value.get('status', 'unknown')
                    available = status.lower() in ('available', 'regthroughus')
                elif isinstance(value, str):
                    available = value.lower() in ('available', 'regthroughus')
                    status = value.lower()

                # Get pricing
                price_info = tld_pricing.get(tld, {})

                enriched.append({
                    'domain': f"{domain}.{tld}",
                    'tld': tld,
                    'available': available,
                    'status': status,
                    'price': price_info.get('price', 0),
                    'product_id': price_info.get('product_id'),
                    'is_featured': tld in website._get_featured_tlds_list(),
                })

        # Sort: available first, then featured, then by TLD
        enriched.sort(key=lambda x: (not x['available'], not x['is_featured'], x['tld']))

        return enriched

    def _get_privacy_price(self, tld):
        """Get WHOIS privacy protection price for a TLD."""
        # Try to find a privacy protection product
        privacy_product = request.env['product.product'].sudo().search([
            ('is_resellerclub_product', '=', True),
            ('rc_product_type', '=', 'privacy_protection'),
        ], limit=1)

        if privacy_product:
            return privacy_product.list_price
        return 0.0


class ResellerClubWebsiteSale(WebsiteSale):
    """
    Extend WebsiteSale for ResellerClub checkout integration.

    Handles domain configuration, customer info collection, and
    special checkout requirements for domain registration.
    """

    def _get_mandatory_fields_billing(self, country_id=False):
        """Add mandatory fields required for domain registration."""
        mandatory_fields = super()._get_mandatory_fields_billing(country_id)

        # Check if cart contains domain products
        sale_order = request.website.sale_get_order()
        if sale_order and self._cart_has_domain_products(sale_order):
            # Add additional required fields for domain registration
            additional_fields = ['phone', 'city', 'zip', 'country_id']
            for field in additional_fields:
                if field not in mandatory_fields:
                    mandatory_fields.append(field)

        return mandatory_fields

    def _cart_has_domain_products(self, sale_order):
        """Check if cart contains domain products."""
        for line in sale_order.order_line:
            if line.product_id.rc_product_type == 'domain':
                return True
        return False

    @http.route(['/shop/cart/update_rc_options'], type='json', auth='public', website=True)
    def update_rc_options(self, line_id, options):
        """
        Update ResellerClub options for a cart line.

        :param line_id: Order line ID
        :param options: Dictionary of options (years, privacy, auto_renew, etc.)
        """
        if 'rc_domain_options' not in request.session:
            request.session['rc_domain_options'] = {}

        request.session['rc_domain_options'][str(line_id)] = options

        return {'success': True}

    @http.route(['/shop/checkout/rc_info'], type='http', auth='public', website=True)
    def checkout_rc_info(self, **kwargs):
        """
        Additional checkout step for ResellerClub products.

        Collects domain-specific information like nameservers,
        registrant contact details, etc.
        """
        sale_order = request.website.sale_get_order()
        if not sale_order:
            return request.redirect('/shop/cart')

        # Check if we have RC products
        has_domains = self._cart_has_domain_products(sale_order)

        if not has_domains:
            return request.redirect('/shop/checkout')

        # Get company default nameservers
        company = request.env.company
        default_ns = [
            company.resellerclub_default_ns1,
            company.resellerclub_default_ns2,
            company.resellerclub_default_ns3,
            company.resellerclub_default_ns4,
        ]

        # Get domain lines
        domain_lines = []
        for line in sale_order.order_line:
            if line.product_id.rc_product_type == 'domain':
                options = request.session.get('rc_domain_options', {}).get(str(line.id), {})
                domain_lines.append({
                    'line': line,
                    'domain': line.rc_service_domain or options.get('domain', ''),
                    'options': options,
                })

        values = {
            'order': sale_order,
            'domain_lines': domain_lines,
            'default_nameservers': [ns for ns in default_ns if ns],
            'partner': sale_order.partner_id,
        }

        return request.render('resellerclub_integration.checkout_rc_info', values)

    @http.route(['/shop/checkout/rc_info/submit'], type='http', auth='public', website=True, methods=['POST'])
    def checkout_rc_info_submit(self, **kwargs):
        """Process the RC info form submission."""
        sale_order = request.website.sale_get_order()
        if not sale_order:
            return request.redirect('/shop/cart')

        # Process each domain line
        for line in sale_order.order_line:
            if line.product_id.rc_product_type == 'domain':
                line_id = str(line.id)

                # Get submitted values
                ns1 = kwargs.get(f'ns1_{line_id}', '')
                ns2 = kwargs.get(f'ns2_{line_id}', '')
                ns3 = kwargs.get(f'ns3_{line_id}', '')
                ns4 = kwargs.get(f'ns4_{line_id}', '')

                # Update session options
                if 'rc_domain_options' not in request.session:
                    request.session['rc_domain_options'] = {}

                current_options = request.session['rc_domain_options'].get(line_id, {})
                current_options.update({
                    'ns1': ns1,
                    'ns2': ns2,
                    'ns3': ns3,
                    'ns4': ns4,
                })
                request.session['rc_domain_options'][line_id] = current_options

        return request.redirect('/shop/checkout')

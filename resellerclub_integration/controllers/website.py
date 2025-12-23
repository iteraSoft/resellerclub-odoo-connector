# -*- coding: utf-8 -*-

import json
import logging
from odoo import http, fields, _
from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale

_logger = logging.getLogger(__name__)

# TLDs that require additional validation/information
TLD_REQUIREMENTS = {
    # UK domains require registrant type
    'uk': {'fields': ['registrant_type'], 'registrant_types': [
        ('IND', 'Individual'),
        ('LTD', 'UK Limited Company'),
        ('PLC', 'UK Public Limited Company'),
        ('PTNR', 'UK Partnership'),
        ('LLP', 'UK Limited Liability Partnership'),
        ('STRA', 'UK Sole Trader'),
        ('RCHAR', 'UK Registered Charity'),
        ('OTHER', 'Other UK Entity'),
    ]},
    'co.uk': {'fields': ['registrant_type'], 'registrant_types': [
        ('IND', 'Individual'),
        ('LTD', 'UK Limited Company'),
        ('PLC', 'UK Public Limited Company'),
        ('PTNR', 'UK Partnership'),
        ('LLP', 'UK Limited Liability Partnership'),
        ('STRA', 'UK Sole Trader'),
        ('RCHAR', 'UK Registered Charity'),
        ('OTHER', 'Other UK Entity'),
    ]},
    # US domains require nexus category
    'us': {'fields': ['nexus_category', 'nexus_app_purpose'], 'nexus_categories': [
        ('C11', 'US Citizen'),
        ('C12', 'Permanent Resident'),
        ('C21', 'US Organization'),
        ('C31', 'Foreign organization with US presence'),
        ('C32', 'Foreign organization with bona fide presence'),
    ], 'nexus_purposes': [
        ('P1', 'Business use for profit'),
        ('P2', 'Non-profit business'),
        ('P3', 'Personal use'),
        ('P4', 'Educational purposes'),
        ('P5', 'Government purposes'),
    ]},
    # EU domains require EU residency
    'eu': {'fields': ['eu_country'], 'requires_eu_residency': True},
    # CA domains require CIRA agreement
    'ca': {'fields': ['cira_agreement', 'legal_type'], 'legal_types': [
        ('CCO', 'Corporation'),
        ('CCT', 'Canadian Citizen'),
        ('RES', 'Permanent Resident'),
        ('GOV', 'Government'),
        ('EDU', 'Educational'),
        ('ASS', 'Association'),
        ('HOP', 'Hospital'),
        ('PRT', 'Partnership'),
        ('TDM', 'Trademark Owner'),
        ('TRD', 'Trade Union'),
        ('PLT', 'Political Party'),
        ('LAM', 'Library/Archive/Museum'),
        ('TRS', 'Trust'),
        ('ABO', 'Aboriginal'),
        ('INB', 'Indian Band'),
        ('LGR', 'Legal Representative'),
        ('OMK', 'Official Mark'),
        ('MAJ', 'Her Majesty'),
    ]},
    # ES domains
    'es': {'fields': ['es_identification'], 'id_types': [
        ('1', 'Spanish ID (DNI/NIF)'),
        ('3', 'Spanish Company (NIF)'),
        ('0', 'Passport/Other'),
    ]},
    # DE domains
    'de': {'fields': ['admin_contact_required'], 'requires_local_admin': True},
}


class ResellerClubWebsite(http.Controller):
    """
    Website controller for ResellerClub integration.

    Provides domain search, availability check, and custom checkout
    functionality for domain, hosting, SSL, and email products.
    """

    # ==========================================
    # DOMAIN SEARCH & REGISTRATION
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

    @http.route('/domains/check', type='json', auth='public', website=True, methods=['POST'])
    def check_domain_availability_public(self, domain_name, tlds=None, **kwargs):
        """Public endpoint for domain availability check."""
        website = request.website
        if not website.rc_enabled:
            return {'success': False, 'error': 'Domain search not enabled'}
        if not domain_name or len(domain_name) < 2:
            return {'success': False, 'error': 'Please enter a valid domain name'}

        domain_name = self._clean_domain_name(domain_name)
        if not tlds:
            tlds = website._get_default_tlds_list()
        elif isinstance(tlds, str):
            tlds = [t.strip() for t in tlds.split(',') if t.strip()]

        try:
            api = request.env['resellerclub.api'].sudo()
            results = api.domain_check_availability(domain_name, tlds)
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
        """Get domain name suggestions."""
        website = request.website
        if not website.rc_enabled:
            return {'success': False, 'error': 'Domain search not enabled'}
        if not keyword or len(keyword) < 2:
            return {'success': False, 'error': 'Please enter a valid keyword'}

        try:
            api = request.env['resellerclub.api'].sudo()
            tlds = website._get_default_tlds_list()
            suggestions = api.domain_suggest_names(keyword, tlds[:5])
            limit = website.rc_search_results_limit or 20
            suggestions = suggestions[:limit] if suggestions else []
            return {'success': True, 'keyword': keyword, 'suggestions': suggestions}
        except Exception as e:
            _logger.error("Domain suggestion failed: %s", str(e))
            return {'success': False, 'error': _('Unable to get domain suggestions')}

    @http.route('/domains/configure', type='http', auth='public', website=True)
    def domain_configure_page(self, domain=None, tld=None, action='register', **kwargs):
        """Domain configuration page for registration or transfer."""
        website = request.website
        if not website.rc_enabled or not domain or not tld:
            return request.redirect('/domains')

        full_domain = f"{domain}.{tld}"
        product = request.env['product.product'].sudo().search([
            ('is_resellerclub_product', '=', True),
            ('rc_product_type', '=', 'domain'),
            ('rc_tld', '=', tld.lower()),
        ], limit=1)

        if not product:
            return request.redirect('/domains')

        company = request.env.company
        default_nameservers = [ns for ns in [
            company.resellerclub_default_ns1,
            company.resellerclub_default_ns2,
            company.resellerclub_default_ns3,
            company.resellerclub_default_ns4,
        ] if ns]

        # Get TLD-specific requirements
        tld_lower = tld.lower()
        tld_requirements = TLD_REQUIREMENTS.get(tld_lower, {})

        values = {
            'domain_name': domain,
            'tld': tld,
            'full_domain': full_domain,
            'action': action,  # 'register' or 'transfer'
            'product': product,
            'price_per_year': product.list_price,
            'max_years': website.rc_max_registration_years,
            'default_years': website.rc_default_registration_years,
            'show_privacy': website.rc_show_whois_privacy,
            'show_auto_renew': website.rc_show_auto_renew,
            'default_nameservers': default_nameservers,
            'privacy_price': self._get_privacy_price(tld),
            'tld_requirements': tld_requirements,
            'is_transfer': action == 'transfer',
        }

        return request.render('resellerclub_integration.domain_configure_page', values)

    # ==========================================
    # DOMAIN TRANSFER
    # ==========================================

    @http.route('/domains/transfer', type='http', auth='public', website=True)
    def domain_transfer_page(self, **kwargs):
        """Display domain transfer page."""
        website = request.website
        if not website.rc_enabled:
            return request.redirect('/shop')

        values = {
            'tld_pricing': website.get_tld_pricing(),
        }
        return request.render('resellerclub_integration.domain_transfer_page', values)

    @http.route('/domains/transfer/check', type='json', auth='public', website=True, methods=['POST'])
    def check_domain_transfer(self, domain_name, **kwargs):
        """Check if domain can be transferred."""
        website = request.website
        if not website.rc_enabled:
            return {'success': False, 'error': 'Transfer not enabled'}

        # Parse domain and TLD
        if '.' not in domain_name:
            return {'success': False, 'error': 'Invalid domain format'}

        parts = domain_name.rsplit('.', 1)
        name = parts[0]
        tld = parts[1].lower()

        try:
            api = request.env['resellerclub.api'].sudo()
            # Check if domain is registered (not available = can transfer)
            results = api.domain_check_availability(name, [tld])

            full_domain = f"{name}.{tld}"
            is_registered = False
            if isinstance(results, dict):
                status = results.get(full_domain, '')
                if isinstance(status, dict):
                    status = status.get('status', '')
                is_registered = str(status).lower() not in ('available', 'regthroughus')

            if not is_registered:
                return {
                    'success': False,
                    'error': _('Domain %s is not registered. Would you like to register it instead?') % full_domain,
                    'can_register': True,
                }

            # Get transfer pricing
            product = request.env['product.product'].sudo().search([
                ('is_resellerclub_product', '=', True),
                ('rc_product_type', '=', 'domain'),
                ('rc_tld', '=', tld),
            ], limit=1)

            return {
                'success': True,
                'domain': full_domain,
                'tld': tld,
                'can_transfer': True,
                'price': product.list_price if product else 0,
                'product_id': product.id if product else None,
            }

        except Exception as e:
            _logger.error("Transfer check failed: %s", str(e))
            return {'success': False, 'error': str(e)}

    @http.route('/domains/transfer/add-to-cart', type='json', auth='public', website=True, methods=['POST'])
    def add_transfer_to_cart(self, domain_name, auth_code, years=1, privacy=False, **kwargs):
        """Add domain transfer to cart."""
        website = request.website
        if not website.rc_enabled:
            return {'success': False, 'error': 'Transfer not enabled'}

        if not auth_code:
            return {'success': False, 'error': _('Authorization code is required for transfer')}

        # Parse domain
        parts = domain_name.rsplit('.', 1)
        if len(parts) != 2:
            return {'success': False, 'error': 'Invalid domain'}

        name, tld = parts

        product = request.env['product.product'].sudo().search([
            ('is_resellerclub_product', '=', True),
            ('rc_product_type', '=', 'domain'),
            ('rc_tld', '=', tld.lower()),
        ], limit=1)

        if not product:
            return {'success': False, 'error': _('Product not found for .%s domains') % tld}

        try:
            sale_order = request.website.sale_get_order(force_create=True)
            order_line = request.env['sale.order.line'].sudo().create({
                'order_id': sale_order.id,
                'product_id': product.id,
                'product_uom_qty': years,
                'rc_service_domain': domain_name,
                'rc_service_type': 'domain_transfer',
                'name': _('Domain Transfer: %s (%d year(s))') % (domain_name, years),
            })

            # Store transfer options in session
            if 'rc_domain_options' not in request.session:
                request.session['rc_domain_options'] = {}
            request.session['rc_domain_options'][str(order_line.id)] = {
                'domain': domain_name,
                'years': years,
                'auth_code': auth_code,
                'privacy': privacy,
                'is_transfer': True,
            }

            return {
                'success': True,
                'message': _('Domain transfer for %s added to cart') % domain_name,
                'cart_quantity': sale_order.cart_quantity,
            }
        except Exception as e:
            _logger.error("Failed to add transfer to cart: %s", str(e))
            return {'success': False, 'error': str(e)}

    # ==========================================
    # ADD DOMAIN TO CART
    # ==========================================

    @http.route('/domains/add-to-cart', type='json', auth='public', website=True, methods=['POST'])
    def add_domain_to_cart(self, domain_name, tld, years=1, privacy=False, auto_renew=True, **kwargs):
        """Add a domain registration to cart."""
        website = request.website
        if not website.rc_enabled:
            return {'success': False, 'error': 'Domain registration not enabled'}

        full_domain = f"{domain_name}.{tld}"

        product = request.env['product.product'].sudo().search([
            ('is_resellerclub_product', '=', True),
            ('rc_product_type', '=', 'domain'),
            ('rc_tld', '=', tld.lower()),
        ], limit=1)

        if not product:
            return {'success': False, 'error': _('Product not found for .%s domains') % tld}

        try:
            sale_order = request.website.sale_get_order(force_create=True)
            order_line = request.env['sale.order.line'].sudo().create({
                'order_id': sale_order.id,
                'product_id': product.id,
                'product_uom_qty': years,
                'rc_service_domain': full_domain,
                'rc_service_type': 'domain_new',
                'name': _('Domain Registration: %s (%d year(s))') % (full_domain, years),
            })

            # Store domain options
            if 'rc_domain_options' not in request.session:
                request.session['rc_domain_options'] = {}
            request.session['rc_domain_options'][str(order_line.id)] = {
                'domain': full_domain,
                'years': years,
                'privacy': privacy,
                'auto_renew': auto_renew,
                'tld_extra': kwargs.get('tld_extra', {}),  # TLD-specific fields
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

    # ==========================================
    # HOSTING CHECKOUT
    # ==========================================

    @http.route('/hosting', type='http', auth='public', website=True)
    def hosting_products_page(self, **kwargs):
        """Display hosting products page."""
        website = request.website
        if not website.rc_enabled or not website.rc_show_hosting_products:
            return request.redirect('/shop')

        hosting_products = website.get_rc_hosting_products()
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

    @http.route('/hosting/configure/<int:product_id>', type='http', auth='public', website=True)
    def hosting_configure_page(self, product_id, domain=None, **kwargs):
        """Hosting configuration page before checkout."""
        website = request.website
        if not website.rc_enabled:
            return request.redirect('/shop')

        product = request.env['product.product'].sudo().browse(product_id)
        if not product.exists() or not product.is_resellerclub_product:
            return request.redirect('/hosting')

        # Get billing periods
        billing_periods = [
            ('1', _('Monthly')),
            ('3', _('Quarterly')),
            ('6', _('Semi-Annual')),
            ('12', _('Annual')),
            ('24', _('Biennial')),
            ('36', _('Triennial')),
        ]

        values = {
            'product': product,
            'domain': domain or '',
            'billing_periods': billing_periods,
            'hosting_type': product.rc_product_type,
        }
        return request.render('resellerclub_integration.hosting_configure_page', values)

    @http.route('/hosting/add-to-cart', type='json', auth='public', website=True, methods=['POST'])
    def add_hosting_to_cart(self, product_id, domain, billing_period=12, **kwargs):
        """Add hosting to cart."""
        website = request.website
        if not website.rc_enabled:
            return {'success': False, 'error': 'Hosting not enabled'}

        if not domain:
            return {'success': False, 'error': _('Domain name is required')}

        product = request.env['product.product'].sudo().browse(product_id)
        if not product.exists():
            return {'success': False, 'error': _('Product not found')}

        try:
            sale_order = request.website.sale_get_order(force_create=True)
            order_line = request.env['sale.order.line'].sudo().create({
                'order_id': sale_order.id,
                'product_id': product.id,
                'product_uom_qty': int(billing_period),
                'rc_service_domain': domain,
                'rc_service_type': product.rc_product_type or 'hosting',
                'name': _('%s: %s (%d months)') % (product.name, domain, int(billing_period)),
            })

            # Store hosting options
            if 'rc_hosting_options' not in request.session:
                request.session['rc_hosting_options'] = {}
            request.session['rc_hosting_options'][str(order_line.id)] = {
                'domain': domain,
                'billing_period': billing_period,
                'extra': kwargs,
            }

            return {
                'success': True,
                'message': _('Hosting added to cart'),
                'cart_quantity': sale_order.cart_quantity,
            }
        except Exception as e:
            _logger.error("Failed to add hosting to cart: %s", str(e))
            return {'success': False, 'error': str(e)}

    # ==========================================
    # SSL CHECKOUT
    # ==========================================

    @http.route('/ssl-certificates', type='http', auth='public', website=True)
    def ssl_products_page(self, **kwargs):
        """Display SSL certificate products page."""
        website = request.website
        if not website.rc_enabled or not website.rc_show_ssl_products:
            return request.redirect('/shop')

        ssl_products = website.get_rc_ssl_products()
        products_by_type = {}
        for product in ssl_products:
            ssl_type = getattr(product, 'rc_ssl_type', 'dv') or 'dv'
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

    @http.route('/ssl/configure/<int:product_id>', type='http', auth='public', website=True)
    def ssl_configure_page(self, product_id, domain=None, **kwargs):
        """SSL configuration page."""
        website = request.website
        if not website.rc_enabled:
            return request.redirect('/shop')

        product = request.env['product.product'].sudo().browse(product_id)
        if not product.exists() or not product.is_resellerclub_product:
            return request.redirect('/ssl-certificates')

        ssl_type = getattr(product, 'rc_ssl_type', 'dv')
        requires_org_info = ssl_type in ('ov', 'ev')

        # Validation methods
        validation_methods = [
            ('email', _('Email Validation')),
            ('http', _('HTTP File Validation')),
            ('dns', _('DNS Record Validation')),
        ]

        values = {
            'product': product,
            'domain': domain or '',
            'ssl_type': ssl_type,
            'requires_org_info': requires_org_info,
            'validation_methods': validation_methods,
            'years': [1, 2],
        }
        return request.render('resellerclub_integration.ssl_configure_page', values)

    @http.route('/ssl/add-to-cart', type='json', auth='public', website=True, methods=['POST'])
    def add_ssl_to_cart(self, product_id, domain, years=1, validation_method='email', csr=None, **kwargs):
        """Add SSL certificate to cart."""
        website = request.website
        if not website.rc_enabled:
            return {'success': False, 'error': 'SSL not enabled'}

        if not domain:
            return {'success': False, 'error': _('Domain name is required')}

        product = request.env['product.product'].sudo().browse(product_id)
        if not product.exists():
            return {'success': False, 'error': _('Product not found')}

        try:
            sale_order = request.website.sale_get_order(force_create=True)
            order_line = request.env['sale.order.line'].sudo().create({
                'order_id': sale_order.id,
                'product_id': product.id,
                'product_uom_qty': int(years),
                'rc_service_domain': domain,
                'rc_service_type': 'ssl',
                'name': _('%s for %s (%d year(s))') % (product.name, domain, int(years)),
            })

            # Store SSL options
            if 'rc_ssl_options' not in request.session:
                request.session['rc_ssl_options'] = {}
            request.session['rc_ssl_options'][str(order_line.id)] = {
                'domain': domain,
                'years': years,
                'validation_method': validation_method,
                'csr': csr,
                'org_info': kwargs.get('org_info', {}),
            }

            return {
                'success': True,
                'message': _('SSL certificate added to cart'),
                'cart_quantity': sale_order.cart_quantity,
            }
        except Exception as e:
            _logger.error("Failed to add SSL to cart: %s", str(e))
            return {'success': False, 'error': str(e)}

    # ==========================================
    # EMAIL HOSTING CHECKOUT
    # ==========================================

    @http.route('/email-hosting', type='http', auth='public', website=True)
    def email_products_page(self, **kwargs):
        """Display email hosting products."""
        website = request.website
        if not website.rc_enabled:
            return request.redirect('/shop')

        email_products = request.env['product.template'].sudo().search([
            ('is_resellerclub_product', '=', True),
            ('rc_product_type', '=', 'email'),
            ('is_published', '=', True),
        ])

        values = {'products': email_products}
        return request.render('resellerclub_integration.email_products_page', values)

    @http.route('/email/configure/<int:product_id>', type='http', auth='public', website=True)
    def email_configure_page(self, product_id, domain=None, **kwargs):
        """Email hosting configuration page."""
        website = request.website
        if not website.rc_enabled:
            return request.redirect('/shop')

        product = request.env['product.product'].sudo().browse(product_id)
        if not product.exists():
            return request.redirect('/email-hosting')

        values = {
            'product': product,
            'domain': domain or '',
            'account_counts': [5, 10, 25, 50, 100, 250],
        }
        return request.render('resellerclub_integration.email_configure_page', values)

    @http.route('/email/add-to-cart', type='json', auth='public', website=True, methods=['POST'])
    def add_email_to_cart(self, product_id, domain, accounts=5, billing_period=12, **kwargs):
        """Add email hosting to cart."""
        website = request.website
        if not website.rc_enabled:
            return {'success': False, 'error': 'Email hosting not enabled'}

        if not domain:
            return {'success': False, 'error': _('Domain name is required')}

        product = request.env['product.product'].sudo().browse(product_id)
        if not product.exists():
            return {'success': False, 'error': _('Product not found')}

        try:
            sale_order = request.website.sale_get_order(force_create=True)
            order_line = request.env['sale.order.line'].sudo().create({
                'order_id': sale_order.id,
                'product_id': product.id,
                'product_uom_qty': int(billing_period),
                'rc_service_domain': domain,
                'rc_service_type': 'email',
                'name': _('Email Hosting: %s (%d accounts)') % (domain, int(accounts)),
            })

            # Store email options
            if 'rc_email_options' not in request.session:
                request.session['rc_email_options'] = {}
            request.session['rc_email_options'][str(order_line.id)] = {
                'domain': domain,
                'accounts': accounts,
                'billing_period': billing_period,
            }

            return {
                'success': True,
                'message': _('Email hosting added to cart'),
                'cart_quantity': sale_order.cart_quantity,
            }
        except Exception as e:
            _logger.error("Failed to add email to cart: %s", str(e))
            return {'success': False, 'error': str(e)}

    # ==========================================
    # HELPER METHODS
    # ==========================================

    def _clean_domain_name(self, domain_name):
        """Clean and normalize domain name input."""
        if '://' in domain_name:
            domain_name = domain_name.split('://')[1]
        if domain_name.startswith('www.'):
            domain_name = domain_name[4:]
        if '.' in domain_name:
            domain_name = domain_name.split('.')[0]
        domain_name = ''.join(c for c in domain_name.lower() if c.isalnum() or c == '-')
        domain_name = domain_name.strip('-')
        return domain_name

    def _enrich_availability_results(self, api_results, tlds):
        """Enrich availability results with pricing."""
        enriched = []
        website = request.website
        tld_pricing = {p['tld']: p for p in website.get_tld_pricing()}

        if isinstance(api_results, dict):
            for key, value in api_results.items():
                if '.' in key:
                    parts = key.rsplit('.', 1)
                    domain = parts[0]
                    tld = parts[1].lower()
                else:
                    continue

                available = False
                status = 'unknown'
                if isinstance(value, dict):
                    status = value.get('status', 'unknown')
                    available = status.lower() in ('available', 'regthroughus')
                elif isinstance(value, str):
                    available = value.lower() in ('available', 'regthroughus')
                    status = value.lower()

                price_info = tld_pricing.get(tld, {})
                enriched.append({
                    'domain': f"{domain}.{tld}",
                    'tld': tld,
                    'available': available,
                    'status': status,
                    'price': price_info.get('price', 0),
                    'product_id': price_info.get('product_id'),
                    'is_featured': tld in website._get_featured_tlds_list(),
                    'has_requirements': tld in TLD_REQUIREMENTS,
                })

        enriched.sort(key=lambda x: (not x['available'], not x['is_featured'], x['tld']))
        return enriched

    def _get_privacy_price(self, tld):
        """Get WHOIS privacy protection price."""
        privacy_product = request.env['product.product'].sudo().search([
            ('is_resellerclub_product', '=', True),
            ('rc_product_type', '=', 'privacy_protection'),
        ], limit=1)
        return privacy_product.list_price if privacy_product else 0.0


class ResellerClubWebsiteSale(WebsiteSale):
    """Extend WebsiteSale for ResellerClub checkout integration."""

    def _get_mandatory_fields_billing(self, country_id=False):
        """Add mandatory fields for domain registration."""
        mandatory_fields = super()._get_mandatory_fields_billing(country_id)
        sale_order = request.website.sale_get_order()
        if sale_order and self._cart_has_rc_products(sale_order):
            for field in ['phone', 'city', 'zip', 'country_id']:
                if field not in mandatory_fields:
                    mandatory_fields.append(field)
        return mandatory_fields

    def _cart_has_rc_products(self, sale_order):
        """Check if cart contains ResellerClub products."""
        for line in sale_order.order_line:
            if line.product_id.is_resellerclub_product:
                return True
        return False

    @http.route(['/shop/checkout/rc_info'], type='http', auth='public', website=True)
    def checkout_rc_info(self, **kwargs):
        """Additional checkout step for service configuration."""
        sale_order = request.website.sale_get_order()
        if not sale_order:
            return request.redirect('/shop/cart')

        company = request.env.company
        default_ns = [ns for ns in [
            company.resellerclub_default_ns1,
            company.resellerclub_default_ns2,
            company.resellerclub_default_ns3,
            company.resellerclub_default_ns4,
        ] if ns]

        # Collect all service lines
        domain_lines = []
        hosting_lines = []
        ssl_lines = []
        email_lines = []

        for line in sale_order.order_line:
            if not line.product_id.is_resellerclub_product:
                continue

            service_type = line.rc_service_type or line.product_id.rc_product_type

            if service_type in ('domain_new', 'domain_transfer', 'domain'):
                options = request.session.get('rc_domain_options', {}).get(str(line.id), {})
                domain_lines.append({
                    'line': line,
                    'domain': line.rc_service_domain or options.get('domain', ''),
                    'options': options,
                    'is_transfer': options.get('is_transfer', False),
                })
            elif 'hosting' in (service_type or ''):
                options = request.session.get('rc_hosting_options', {}).get(str(line.id), {})
                hosting_lines.append({'line': line, 'options': options})
            elif service_type == 'ssl':
                options = request.session.get('rc_ssl_options', {}).get(str(line.id), {})
                ssl_lines.append({'line': line, 'options': options})
            elif service_type == 'email':
                options = request.session.get('rc_email_options', {}).get(str(line.id), {})
                email_lines.append({'line': line, 'options': options})

        if not any([domain_lines, hosting_lines, ssl_lines, email_lines]):
            return request.redirect('/shop/checkout')

        values = {
            'order': sale_order,
            'domain_lines': domain_lines,
            'hosting_lines': hosting_lines,
            'ssl_lines': ssl_lines,
            'email_lines': email_lines,
            'default_nameservers': default_ns,
            'partner': sale_order.partner_id,
            'tld_requirements': TLD_REQUIREMENTS,
        }

        return request.render('resellerclub_integration.checkout_rc_info', values)

    @http.route(['/shop/checkout/rc_info/submit'], type='http', auth='public', website=True, methods=['POST'])
    def checkout_rc_info_submit(self, **kwargs):
        """Process service configuration form."""
        sale_order = request.website.sale_get_order()
        if not sale_order:
            return request.redirect('/shop/cart')

        for line in sale_order.order_line:
            if not line.product_id.is_resellerclub_product:
                continue

            line_id = str(line.id)
            service_type = line.rc_service_type or line.product_id.rc_product_type

            if service_type in ('domain_new', 'domain_transfer', 'domain'):
                # Update domain options
                session_key = 'rc_domain_options'
                if session_key not in request.session:
                    request.session[session_key] = {}

                current = request.session[session_key].get(line_id, {})
                current.update({
                    'ns1': kwargs.get(f'ns1_{line_id}', ''),
                    'ns2': kwargs.get(f'ns2_{line_id}', ''),
                    'ns3': kwargs.get(f'ns3_{line_id}', ''),
                    'ns4': kwargs.get(f'ns4_{line_id}', ''),
                    'auth_code': kwargs.get(f'auth_code_{line_id}', current.get('auth_code', '')),
                })
                # TLD-specific fields
                for field in ['registrant_type', 'nexus_category', 'nexus_app_purpose', 'legal_type', 'cira_agreement']:
                    if f'{field}_{line_id}' in kwargs:
                        current[field] = kwargs.get(f'{field}_{line_id}')

                request.session[session_key][line_id] = current

            elif service_type == 'ssl':
                session_key = 'rc_ssl_options'
                if session_key not in request.session:
                    request.session[session_key] = {}

                current = request.session[session_key].get(line_id, {})
                current.update({
                    'csr': kwargs.get(f'csr_{line_id}', current.get('csr', '')),
                    'validation_method': kwargs.get(f'validation_{line_id}', 'email'),
                    'admin_email': kwargs.get(f'admin_email_{line_id}', ''),
                })
                request.session[session_key][line_id] = current

        return request.redirect('/shop/checkout')

    @http.route(['/shop/cart/update_rc_options'], type='json', auth='public', website=True)
    def update_rc_options(self, line_id, options, option_type='domain'):
        """Update service options for a cart line."""
        session_key = f'rc_{option_type}_options'
        if session_key not in request.session:
            request.session[session_key] = {}
        request.session[session_key][str(line_id)] = options
        return {'success': True}

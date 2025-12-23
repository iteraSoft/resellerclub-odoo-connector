# -*- coding: utf-8 -*-

import logging
from collections import OrderedDict
from odoo import http, fields, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.osv.expression import AND
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)


class ResellerClubPortal(CustomerPortal):
    """Portal controller for ResellerClub services management."""

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        partner = request.env.user.partner_id

        if 'domain_count' in counters:
            values['domain_count'] = request.env['resellerclub.domain'].search_count([
                ('partner_id', '=', partner.id),
            ])

        if 'hosting_count' in counters:
            values['hosting_count'] = request.env['resellerclub.hosting'].search_count([
                ('partner_id', '=', partner.id),
            ])

        if 'ssl_count' in counters:
            values['ssl_count'] = request.env['resellerclub.ssl'].search_count([
                ('partner_id', '=', partner.id),
            ])

        return values

    # =============================================
    # SERVICES DASHBOARD
    # =============================================

    @http.route('/my/services', type='http', auth='user', website=True)
    def portal_services_dashboard(self, **kw):
        """Display services dashboard with overview of all services."""
        partner = request.env.user.partner_id

        # Get service counts and summaries
        domains = request.env['resellerclub.domain'].search([
            ('partner_id', '=', partner.id)
        ], order='expiration_date asc')

        hostings = request.env['resellerclub.hosting'].search([
            ('partner_id', '=', partner.id)
        ], order='expiration_date asc')

        ssls = request.env['resellerclub.ssl'].search([
            ('partner_id', '=', partner.id)
        ], order='expiration_date asc')

        # Calculate expiring services (within 30 days)
        expiring_domains = domains.filtered(lambda d: d.days_until_expiry and 0 < d.days_until_expiry <= 30)
        expiring_hostings = hostings.filtered(lambda h: h.days_until_expiry and 0 < h.days_until_expiry <= 30)
        expiring_ssls = ssls.filtered(lambda s: s.days_until_expiry and 0 < s.days_until_expiry <= 30)

        values = {
            'page_name': 'services_dashboard',
            'domains': domains[:5],  # Show latest 5
            'hostings': hostings[:5],
            'ssls': ssls[:5],
            'domain_count': len(domains),
            'hosting_count': len(hostings),
            'ssl_count': len(ssls),
            'expiring_domains': expiring_domains,
            'expiring_hostings': expiring_hostings,
            'expiring_ssls': expiring_ssls,
            'total_expiring': len(expiring_domains) + len(expiring_hostings) + len(expiring_ssls),
        }

        return request.render('resellerclub_integration.portal_services_dashboard', values)

    # =============================================
    # DOMAINS PORTAL
    # =============================================

    @http.route(['/my/domains', '/my/domains/page/<int:page>'], type='http', auth='user', website=True)
    def portal_my_domains(self, page=1, sortby=None, filterby=None, search=None, **kw):
        """Display customer's domains."""
        partner = request.env.user.partner_id
        Domain = request.env['resellerclub.domain']

        searchbar_sortings = {
            'date': {'label': _('Expiration Date'), 'order': 'expiration_date asc'},
            'name': {'label': _('Domain Name'), 'order': 'domain_name asc'},
            'status': {'label': _('Status'), 'order': 'status asc'},
        }

        searchbar_filters = {
            'all': {'label': _('All'), 'domain': []},
            'active': {'label': _('Active'), 'domain': [('status', '=', 'active')]},
            'expiring': {'label': _('Expiring Soon'), 'domain': [('days_until_expiry', '<=', 30), ('days_until_expiry', '>', 0)]},
            'expired': {'label': _('Expired'), 'domain': [('status', '=', 'expired')]},
        }

        if not sortby:
            sortby = 'date'
        if not filterby:
            filterby = 'all'

        order = searchbar_sortings[sortby]['order']
        domain = AND([
            [('partner_id', '=', partner.id)],
            searchbar_filters[filterby]['domain']
        ])

        if search:
            domain = AND([domain, [('domain_name', 'ilike', search)]])

        domain_count = Domain.search_count(domain)

        pager = portal_pager(
            url='/my/domains',
            url_args={'sortby': sortby, 'filterby': filterby, 'search': search},
            total=domain_count,
            page=page,
            step=20
        )

        domains = Domain.search(domain, order=order, limit=20, offset=pager['offset'])

        values = {
            'domains': domains,
            'page_name': 'domains',
            'pager': pager,
            'default_url': '/my/domains',
            'searchbar_sortings': searchbar_sortings,
            'sortby': sortby,
            'searchbar_filters': searchbar_filters,
            'filterby': filterby,
            'search': search,
        }

        return request.render('resellerclub_integration.portal_my_domains', values)

    @http.route(['/my/domains/<int:domain_id>'], type='http', auth='user', website=True)
    def portal_my_domain_detail(self, domain_id, **kw):
        """Display domain details with management options."""
        partner = request.env.user.partner_id
        domain = request.env['resellerclub.domain'].search([
            ('id', '=', domain_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not domain:
            return request.redirect('/my/domains')

        # Get DNS records
        dns_records = request.env['resellerclub.dns.record'].search([
            ('domain_id', '=', domain.id)
        ])

        values = {
            'domain': domain,
            'dns_records': dns_records,
            'page_name': 'domain_detail',
        }

        return request.render('resellerclub_integration.portal_domain_detail', values)

    # Domain Management Actions
    @http.route('/my/domains/<int:domain_id>/toggle-autorenew', type='json', auth='user', website=True)
    def portal_domain_toggle_autorenew(self, domain_id, **kw):
        """Toggle domain auto-renewal."""
        partner = request.env.user.partner_id
        domain = request.env['resellerclub.domain'].search([
            ('id', '=', domain_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not domain:
            return {'success': False, 'error': _('Domain not found')}

        try:
            new_state = not domain.auto_renew
            domain.write({'auto_renew': new_state})
            # Optionally sync with ResellerClub API
            # domain.action_toggle_auto_renew()
            return {
                'success': True,
                'auto_renew': new_state,
                'message': _('Auto-renewal %s') % (_('enabled') if new_state else _('disabled'))
            }
        except Exception as e:
            _logger.error("Failed to toggle auto-renew: %s", str(e))
            return {'success': False, 'error': str(e)}

    @http.route('/my/domains/<int:domain_id>/toggle-lock', type='json', auth='user', website=True)
    def portal_domain_toggle_lock(self, domain_id, **kw):
        """Toggle domain theft protection lock."""
        partner = request.env.user.partner_id
        domain = request.env['resellerclub.domain'].search([
            ('id', '=', domain_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not domain:
            return {'success': False, 'error': _('Domain not found')}

        try:
            new_state = not domain.is_locked
            domain.write({'is_locked': new_state})
            return {
                'success': True,
                'is_locked': new_state,
                'message': _('Domain lock %s') % (_('enabled') if new_state else _('disabled'))
            }
        except Exception as e:
            _logger.error("Failed to toggle lock: %s", str(e))
            return {'success': False, 'error': str(e)}

    @http.route('/my/domains/<int:domain_id>/update-nameservers', type='json', auth='user', website=True)
    def portal_domain_update_nameservers(self, domain_id, ns1='', ns2='', ns3='', ns4='', **kw):
        """Update domain nameservers."""
        partner = request.env.user.partner_id
        domain = request.env['resellerclub.domain'].search([
            ('id', '=', domain_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not domain:
            return {'success': False, 'error': _('Domain not found')}

        if not ns1 or not ns2:
            return {'success': False, 'error': _('At least 2 nameservers are required')}

        try:
            domain.write({
                'ns1': ns1,
                'ns2': ns2,
                'ns3': ns3 or False,
                'ns4': ns4 or False,
            })
            # Sync with ResellerClub
            # domain.action_update_nameservers()
            return {
                'success': True,
                'message': _('Nameservers updated successfully')
            }
        except Exception as e:
            _logger.error("Failed to update nameservers: %s", str(e))
            return {'success': False, 'error': str(e)}

    @http.route('/my/domains/<int:domain_id>/renew', type='http', auth='user', website=True)
    def portal_domain_renew(self, domain_id, **kw):
        """Show domain renewal page."""
        partner = request.env.user.partner_id
        domain = request.env['resellerclub.domain'].search([
            ('id', '=', domain_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not domain:
            return request.redirect('/my/domains')

        # Get the domain product for pricing
        product = request.env['product.product'].sudo().search([
            ('is_resellerclub_product', '=', True),
            ('rc_product_type', '=', 'domain'),
            ('rc_tld', '=', domain.tld),
        ], limit=1)

        values = {
            'domain': domain,
            'product': product,
            'page_name': 'domain_renew',
            'max_years': 10,
        }

        return request.render('resellerclub_integration.portal_domain_renew', values)

    @http.route('/my/domains/<int:domain_id>/renew/submit', type='http', auth='user', website=True, methods=['POST'])
    def portal_domain_renew_submit(self, domain_id, years=1, **kw):
        """Process domain renewal."""
        partner = request.env.user.partner_id
        domain = request.env['resellerclub.domain'].search([
            ('id', '=', domain_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not domain:
            return request.redirect('/my/domains')

        # Find or create a sale order for renewal
        product = request.env['product.product'].sudo().search([
            ('is_resellerclub_product', '=', True),
            ('rc_product_type', '=', 'domain'),
            ('rc_tld', '=', domain.tld),
        ], limit=1)

        if not product:
            return request.redirect(f'/my/domains/{domain_id}?error=product_not_found')

        try:
            sale_order = request.website.sale_get_order(force_create=True)
            request.env['sale.order.line'].sudo().create({
                'order_id': sale_order.id,
                'product_id': product.id,
                'product_uom_qty': int(years),
                'rc_service_domain': domain.domain_name,
                'rc_service_type': 'domain_renewal',
                'name': _('Domain Renewal: %s (%d year(s))') % (domain.domain_name, int(years)),
            })
            return request.redirect('/shop/cart')
        except Exception as e:
            _logger.error("Failed to create renewal order: %s", str(e))
            return request.redirect(f'/my/domains/{domain_id}?error=renewal_failed')

    # DNS Management
    @http.route('/my/domains/<int:domain_id>/dns', type='http', auth='user', website=True)
    def portal_domain_dns(self, domain_id, **kw):
        """Display DNS management page."""
        partner = request.env.user.partner_id
        domain = request.env['resellerclub.domain'].search([
            ('id', '=', domain_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not domain:
            return request.redirect('/my/domains')

        dns_records = request.env['resellerclub.dns.record'].search([
            ('domain_id', '=', domain.id)
        ])

        values = {
            'domain': domain,
            'dns_records': dns_records,
            'page_name': 'domain_dns',
            'record_types': [
                ('A', 'A Record'),
                ('AAAA', 'AAAA Record'),
                ('CNAME', 'CNAME Record'),
                ('MX', 'MX Record'),
                ('TXT', 'TXT Record'),
                ('NS', 'NS Record'),
                ('SRV', 'SRV Record'),
            ],
        }

        return request.render('resellerclub_integration.portal_domain_dns', values)

    @http.route('/my/domains/<int:domain_id>/dns/add', type='json', auth='user', website=True)
    def portal_domain_dns_add(self, domain_id, record_type, host, value, ttl=14400, priority=None, **kw):
        """Add a DNS record."""
        partner = request.env.user.partner_id
        domain = request.env['resellerclub.domain'].search([
            ('id', '=', domain_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not domain:
            return {'success': False, 'error': _('Domain not found')}

        try:
            record = request.env['resellerclub.dns.record'].create({
                'domain_id': domain.id,
                'record_type': record_type,
                'host': host,
                'value': value,
                'ttl': int(ttl),
                'priority': int(priority) if priority else None,
            })
            return {
                'success': True,
                'record_id': record.id,
                'message': _('DNS record added successfully')
            }
        except Exception as e:
            _logger.error("Failed to add DNS record: %s", str(e))
            return {'success': False, 'error': str(e)}

    @http.route('/my/domains/<int:domain_id>/dns/delete/<int:record_id>', type='json', auth='user', website=True)
    def portal_domain_dns_delete(self, domain_id, record_id, **kw):
        """Delete a DNS record."""
        partner = request.env.user.partner_id
        domain = request.env['resellerclub.domain'].search([
            ('id', '=', domain_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not domain:
            return {'success': False, 'error': _('Domain not found')}

        record = request.env['resellerclub.dns.record'].search([
            ('id', '=', record_id),
            ('domain_id', '=', domain.id),
        ], limit=1)

        if not record:
            return {'success': False, 'error': _('Record not found')}

        try:
            record.unlink()
            return {'success': True, 'message': _('DNS record deleted')}
        except Exception as e:
            _logger.error("Failed to delete DNS record: %s", str(e))
            return {'success': False, 'error': str(e)}

    # =============================================
    # HOSTING PORTAL
    # =============================================

    @http.route(['/my/hosting', '/my/hosting/page/<int:page>'], type='http', auth='user', website=True)
    def portal_my_hosting(self, page=1, sortby=None, filterby=None, **kw):
        """Display customer's hosting services."""
        partner = request.env.user.partner_id
        Hosting = request.env['resellerclub.hosting']

        searchbar_sortings = {
            'date': {'label': _('Expiration Date'), 'order': 'expiration_date asc'},
            'name': {'label': _('Domain'), 'order': 'domain_name asc'},
            'type': {'label': _('Type'), 'order': 'hosting_type asc'},
        }

        searchbar_filters = {
            'all': {'label': _('All'), 'domain': []},
            'active': {'label': _('Active'), 'domain': [('status', '=', 'active')]},
            'expiring': {'label': _('Expiring Soon'), 'domain': [('days_until_expiry', '<=', 30), ('days_until_expiry', '>', 0)]},
        }

        if not sortby:
            sortby = 'date'
        if not filterby:
            filterby = 'all'

        order = searchbar_sortings[sortby]['order']
        domain = AND([
            [('partner_id', '=', partner.id)],
            searchbar_filters[filterby]['domain']
        ])

        hosting_count = Hosting.search_count(domain)

        pager = portal_pager(
            url='/my/hosting',
            url_args={'sortby': sortby, 'filterby': filterby},
            total=hosting_count,
            page=page,
            step=20
        )

        hostings = Hosting.search(domain, order=order, limit=20, offset=pager['offset'])

        values = {
            'hostings': hostings,
            'page_name': 'hosting',
            'pager': pager,
            'default_url': '/my/hosting',
            'searchbar_sortings': searchbar_sortings,
            'sortby': sortby,
            'searchbar_filters': searchbar_filters,
            'filterby': filterby,
        }

        return request.render('resellerclub_integration.portal_my_hosting', values)

    @http.route(['/my/hosting/<int:hosting_id>'], type='http', auth='user', website=True)
    def portal_my_hosting_detail(self, hosting_id, **kw):
        """Display hosting details with management options."""
        partner = request.env.user.partner_id
        hosting = request.env['resellerclub.hosting'].search([
            ('id', '=', hosting_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not hosting:
            return request.redirect('/my/hosting')

        values = {
            'hosting': hosting,
            'page_name': 'hosting_detail',
        }

        return request.render('resellerclub_integration.portal_hosting_detail', values)

    @http.route('/my/hosting/<int:hosting_id>/toggle-autorenew', type='json', auth='user', website=True)
    def portal_hosting_toggle_autorenew(self, hosting_id, **kw):
        """Toggle hosting auto-renewal."""
        partner = request.env.user.partner_id
        hosting = request.env['resellerclub.hosting'].search([
            ('id', '=', hosting_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not hosting:
            return {'success': False, 'error': _('Hosting not found')}

        try:
            new_state = not hosting.auto_renew
            hosting.write({'auto_renew': new_state})
            return {
                'success': True,
                'auto_renew': new_state,
                'message': _('Auto-renewal %s') % (_('enabled') if new_state else _('disabled'))
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @http.route('/my/hosting/<int:hosting_id>/renew', type='http', auth='user', website=True)
    def portal_hosting_renew(self, hosting_id, **kw):
        """Show hosting renewal page."""
        partner = request.env.user.partner_id
        hosting = request.env['resellerclub.hosting'].search([
            ('id', '=', hosting_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not hosting:
            return request.redirect('/my/hosting')

        values = {
            'hosting': hosting,
            'page_name': 'hosting_renew',
            'billing_periods': [
                (1, _('1 Month')),
                (3, _('3 Months')),
                (6, _('6 Months')),
                (12, _('1 Year')),
                (24, _('2 Years')),
                (36, _('3 Years')),
            ],
        }

        return request.render('resellerclub_integration.portal_hosting_renew', values)

    # =============================================
    # SSL PORTAL
    # =============================================

    @http.route(['/my/ssl', '/my/ssl/page/<int:page>'], type='http', auth='user', website=True)
    def portal_my_ssl(self, page=1, sortby=None, filterby=None, **kw):
        """Display customer's SSL certificates."""
        partner = request.env.user.partner_id
        SSL = request.env['resellerclub.ssl']

        searchbar_sortings = {
            'date': {'label': _('Expiration Date'), 'order': 'expiration_date asc'},
            'name': {'label': _('Domain'), 'order': 'domain_name asc'},
            'type': {'label': _('Type'), 'order': 'ssl_type asc'},
        }

        searchbar_filters = {
            'all': {'label': _('All'), 'domain': []},
            'active': {'label': _('Active'), 'domain': [('status', '=', 'active')]},
            'pending': {'label': _('Pending'), 'domain': [('status', '=', 'pending_issuance')]},
            'expiring': {'label': _('Expiring Soon'), 'domain': [('days_until_expiry', '<=', 30), ('days_until_expiry', '>', 0)]},
        }

        if not sortby:
            sortby = 'date'
        if not filterby:
            filterby = 'all'

        order = searchbar_sortings[sortby]['order']
        domain = AND([
            [('partner_id', '=', partner.id)],
            searchbar_filters[filterby]['domain']
        ])

        ssl_count = SSL.search_count(domain)

        pager = portal_pager(
            url='/my/ssl',
            url_args={'sortby': sortby, 'filterby': filterby},
            total=ssl_count,
            page=page,
            step=20
        )

        ssls = SSL.search(domain, order=order, limit=20, offset=pager['offset'])

        values = {
            'ssls': ssls,
            'page_name': 'ssl',
            'pager': pager,
            'default_url': '/my/ssl',
            'searchbar_sortings': searchbar_sortings,
            'sortby': sortby,
            'searchbar_filters': searchbar_filters,
            'filterby': filterby,
        }

        return request.render('resellerclub_integration.portal_my_ssl', values)

    @http.route(['/my/ssl/<int:ssl_id>'], type='http', auth='user', website=True)
    def portal_my_ssl_detail(self, ssl_id, **kw):
        """Display SSL certificate details."""
        partner = request.env.user.partner_id
        ssl = request.env['resellerclub.ssl'].search([
            ('id', '=', ssl_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not ssl:
            return request.redirect('/my/ssl')

        values = {
            'ssl': ssl,
            'page_name': 'ssl_detail',
        }

        return request.render('resellerclub_integration.portal_ssl_detail', values)

    @http.route('/my/ssl/<int:ssl_id>/download', type='http', auth='user', website=True)
    def portal_ssl_download(self, ssl_id, **kw):
        """Download SSL certificate."""
        partner = request.env.user.partner_id
        ssl = request.env['resellerclub.ssl'].search([
            ('id', '=', ssl_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not ssl or not ssl.certificate:
            return request.redirect('/my/ssl')

        # Return certificate as file download
        return request.make_response(
            ssl.certificate,
            headers=[
                ('Content-Type', 'application/x-pem-file'),
                ('Content-Disposition', f'attachment; filename="{ssl.domain_name}.crt"'),
            ]
        )

    @http.route('/my/ssl/<int:ssl_id>/renew', type='http', auth='user', website=True)
    def portal_ssl_renew(self, ssl_id, **kw):
        """Show SSL renewal page."""
        partner = request.env.user.partner_id
        ssl = request.env['resellerclub.ssl'].search([
            ('id', '=', ssl_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not ssl:
            return request.redirect('/my/ssl')

        values = {
            'ssl': ssl,
            'page_name': 'ssl_renew',
            'years': [1, 2],
        }

        return request.render('resellerclub_integration.portal_ssl_renew', values)

    # =============================================
    # QUICK ACTIONS (AJAX)
    # =============================================

    @http.route('/my/services/sync/<string:service_type>/<int:service_id>', type='json', auth='user', website=True)
    def portal_sync_service(self, service_type, service_id, **kw):
        """Sync a service with ResellerClub."""
        partner = request.env.user.partner_id

        model_map = {
            'domain': 'resellerclub.domain',
            'hosting': 'resellerclub.hosting',
            'ssl': 'resellerclub.ssl',
        }

        if service_type not in model_map:
            return {'success': False, 'error': _('Invalid service type')}

        service = request.env[model_map[service_type]].search([
            ('id', '=', service_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not service:
            return {'success': False, 'error': _('Service not found')}

        try:
            if hasattr(service, 'action_sync_from_resellerclub'):
                service.action_sync_from_resellerclub()
            return {'success': True, 'message': _('Service synchronized')}
        except Exception as e:
            _logger.error("Failed to sync service: %s", str(e))
            return {'success': False, 'error': str(e)}

    # =============================================
    # CONTROL PANEL SSO (Single Sign-On)
    # =============================================

    @http.route('/my/hosting/<int:hosting_id>/cpanel', type='http', auth='user', website=True)
    def portal_hosting_cpanel_sso(self, hosting_id, **kw):
        """Redirect to cPanel via SSO."""
        partner = request.env.user.partner_id
        hosting = request.env['resellerclub.hosting'].search([
            ('id', '=', hosting_id),
            ('partner_id', '=', partner.id),
            ('status', '=', 'active'),
        ], limit=1)

        if not hosting:
            return request.redirect('/my/hosting?error=not_found')

        try:
            api = request.env['resellerclub.api']
            result = api.hosting_get_cpanel_url(hosting.rc_order_id)
            if result and isinstance(result, dict) and result.get('url'):
                return request.redirect(result['url'])
            elif isinstance(result, str):
                return request.redirect(result)
            else:
                return request.redirect(f'/my/hosting/{hosting_id}?error=sso_failed')
        except Exception as e:
            _logger.error("Failed to get cPanel SSO URL: %s", str(e))
            return request.redirect(f'/my/hosting/{hosting_id}?error=sso_failed')

    @http.route('/my/hosting/<int:hosting_id>/webmail', type='http', auth='user', website=True)
    def portal_hosting_webmail_sso(self, hosting_id, **kw):
        """Redirect to webmail via SSO."""
        partner = request.env.user.partner_id
        hosting = request.env['resellerclub.hosting'].search([
            ('id', '=', hosting_id),
            ('partner_id', '=', partner.id),
            ('status', '=', 'active'),
        ], limit=1)

        if not hosting:
            return request.redirect('/my/hosting?error=not_found')

        try:
            api = request.env['resellerclub.api']
            result = api.hosting_get_webmail_url(hosting.rc_order_id)
            if result and isinstance(result, dict) and result.get('url'):
                return request.redirect(result['url'])
            elif isinstance(result, str):
                return request.redirect(result)
            else:
                return request.redirect(f'/my/hosting/{hosting_id}?error=sso_failed')
        except Exception as e:
            _logger.error("Failed to get webmail SSO URL: %s", str(e))
            return request.redirect(f'/my/hosting/{hosting_id}?error=sso_failed')

    # =============================================
    # DOMAIN FORWARDING
    # =============================================

    @http.route('/my/domains/<int:domain_id>/forwarding', type='http', auth='user', website=True)
    def portal_domain_forwarding(self, domain_id, **kw):
        """Display domain forwarding configuration."""
        partner = request.env.user.partner_id
        domain = request.env['resellerclub.domain'].search([
            ('id', '=', domain_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not domain:
            return request.redirect('/my/domains')

        # Get current forwarding settings
        forwarding = None
        try:
            api = request.env['resellerclub.api']
            forwarding = api.domain_forwarding_get(domain.rc_order_id)
        except Exception as e:
            _logger.warning("Could not get forwarding settings: %s", str(e))

        values = {
            'domain': domain,
            'forwarding': forwarding,
            'page_name': 'domain_forwarding',
        }

        return request.render('resellerclub_integration.portal_domain_forwarding', values)

    @http.route('/my/domains/<int:domain_id>/forwarding/save', type='json', auth='user', website=True)
    def portal_domain_forwarding_save(self, domain_id, destination_url='', url_masking=False, **kw):
        """Save domain forwarding settings."""
        partner = request.env.user.partner_id
        domain = request.env['resellerclub.domain'].search([
            ('id', '=', domain_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not domain:
            return {'success': False, 'error': _('Domain not found')}

        if not destination_url:
            return {'success': False, 'error': _('Destination URL is required')}

        # Validate URL format
        if not destination_url.startswith(('http://', 'https://')):
            destination_url = 'http://' + destination_url

        try:
            api = request.env['resellerclub.api']
            api.domain_forwarding_setup(
                domain.rc_order_id,
                destination_url,
                url_masking=url_masking
            )
            return {'success': True, 'message': _('Domain forwarding configured successfully')}
        except Exception as e:
            _logger.error("Failed to setup forwarding: %s", str(e))
            return {'success': False, 'error': str(e)}

    @http.route('/my/domains/<int:domain_id>/forwarding/delete', type='json', auth='user', website=True)
    def portal_domain_forwarding_delete(self, domain_id, **kw):
        """Delete domain forwarding."""
        partner = request.env.user.partner_id
        domain = request.env['resellerclub.domain'].search([
            ('id', '=', domain_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not domain:
            return {'success': False, 'error': _('Domain not found')}

        try:
            api = request.env['resellerclub.api']
            api.domain_forwarding_delete(domain.rc_order_id)
            return {'success': True, 'message': _('Domain forwarding removed')}
        except Exception as e:
            _logger.error("Failed to delete forwarding: %s", str(e))
            return {'success': False, 'error': str(e)}

    # =============================================
    # WHOIS / CONTACT MANAGEMENT
    # =============================================

    @http.route('/my/domains/<int:domain_id>/contacts', type='http', auth='user', website=True)
    def portal_domain_contacts(self, domain_id, **kw):
        """Display domain contact (WHOIS) information."""
        partner = request.env.user.partner_id
        domain = request.env['resellerclub.domain'].search([
            ('id', '=', domain_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not domain:
            return request.redirect('/my/domains')

        # Get contacts from ResellerClub customer record
        customer = request.env['resellerclub.customer'].search([
            ('partner_id', '=', partner.id)
        ], limit=1)

        contacts = []
        if customer:
            try:
                api = request.env['resellerclub.api']
                contacts = api.contact_search(customer.rc_customer_id)
            except Exception as e:
                _logger.warning("Could not get contacts: %s", str(e))

        values = {
            'domain': domain,
            'contacts': contacts,
            'page_name': 'domain_contacts',
        }

        return request.render('resellerclub_integration.portal_domain_contacts', values)

    @http.route('/my/domains/<int:domain_id>/contacts/update', type='json', auth='user', website=True)
    def portal_domain_contacts_update(self, domain_id, contact_type='registrant', **contact_data):
        """Update domain contact information."""
        partner = request.env.user.partner_id
        domain = request.env['resellerclub.domain'].search([
            ('id', '=', domain_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not domain:
            return {'success': False, 'error': _('Domain not found')}

        # Get customer
        customer = request.env['resellerclub.customer'].search([
            ('partner_id', '=', partner.id)
        ], limit=1)

        if not customer:
            return {'success': False, 'error': _('Customer record not found')}

        try:
            api = request.env['resellerclub.api']

            # Create or update contact
            contact_id = contact_data.pop('contact_id', None)

            if contact_id:
                # Update existing contact
                api.contact_modify(contact_id, **contact_data)
            else:
                # Create new contact
                contact_id = api.contact_create(
                    customer.rc_customer_id,
                    contact_data.get('email', partner.email),
                    contact_data.get('name', partner.name),
                    contact_data.get('company', partner.commercial_company_name or ''),
                    contact_data.get('address', partner.street or ''),
                    contact_data.get('city', partner.city or ''),
                    contact_data.get('state', partner.state_id.name if partner.state_id else ''),
                    contact_data.get('country_code', partner.country_id.code if partner.country_id else 'US'),
                    contact_data.get('zipcode', partner.zip or ''),
                    contact_data.get('phone_cc', '1'),
                    contact_data.get('phone', partner.phone or ''),
                )

            # Update domain with the new contact
            contact_params = {}
            if contact_type == 'registrant':
                contact_params['reg_contact_id'] = contact_id
            elif contact_type == 'admin':
                contact_params['admin_contact_id'] = contact_id
            elif contact_type == 'tech':
                contact_params['tech_contact_id'] = contact_id
            elif contact_type == 'billing':
                contact_params['billing_contact_id'] = contact_id

            if contact_params:
                api.domain_modify_contacts(domain.rc_order_id, **contact_params)

            return {'success': True, 'message': _('Contact updated successfully')}
        except Exception as e:
            _logger.error("Failed to update contact: %s", str(e))
            return {'success': False, 'error': str(e)}

    @http.route('/my/domains/<int:domain_id>/resend-verification', type='json', auth='user', website=True)
    def portal_domain_resend_verification(self, domain_id, **kw):
        """Resend domain registrant verification email."""
        partner = request.env.user.partner_id
        domain = request.env['resellerclub.domain'].search([
            ('id', '=', domain_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not domain:
            return {'success': False, 'error': _('Domain not found')}

        try:
            api = request.env['resellerclub.api']
            api.domain_resend_verification(domain.rc_order_id)
            return {'success': True, 'message': _('Verification email sent')}
        except Exception as e:
            _logger.error("Failed to resend verification: %s", str(e))
            return {'success': False, 'error': str(e)}

    # =============================================
    # CHILD NAMESERVERS (GLUE RECORDS)
    # =============================================

    @http.route('/my/domains/<int:domain_id>/childns', type='http', auth='user', website=True)
    def portal_domain_childns(self, domain_id, **kw):
        """Display child nameserver management page."""
        partner = request.env.user.partner_id
        domain = request.env['resellerclub.domain'].search([
            ('id', '=', domain_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not domain:
            return request.redirect('/my/domains')

        # Get current child nameservers
        childns = []
        try:
            api = request.env['resellerclub.api']
            childns = api.childns_get(domain.rc_order_id)
        except Exception as e:
            _logger.warning("Could not get child nameservers: %s", str(e))

        values = {
            'domain': domain,
            'childns': childns if isinstance(childns, list) else [],
            'page_name': 'domain_childns',
        }

        return request.render('resellerclub_integration.portal_domain_childns', values)

    @http.route('/my/domains/<int:domain_id>/childns/add', type='json', auth='user', website=True)
    def portal_domain_childns_add(self, domain_id, hostname='', ip_address='', **kw):
        """Add a child nameserver."""
        partner = request.env.user.partner_id
        domain = request.env['resellerclub.domain'].search([
            ('id', '=', domain_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not domain:
            return {'success': False, 'error': _('Domain not found')}

        if not hostname or not ip_address:
            return {'success': False, 'error': _('Hostname and IP address are required')}

        try:
            api = request.env['resellerclub.api']
            api.childns_add(domain.rc_order_id, hostname, [ip_address])
            return {'success': True, 'message': _('Child nameserver added')}
        except Exception as e:
            _logger.error("Failed to add child nameserver: %s", str(e))
            return {'success': False, 'error': str(e)}

    @http.route('/my/domains/<int:domain_id>/childns/delete', type='json', auth='user', website=True)
    def portal_domain_childns_delete(self, domain_id, hostname='', ip_address='', **kw):
        """Delete a child nameserver IP."""
        partner = request.env.user.partner_id
        domain = request.env['resellerclub.domain'].search([
            ('id', '=', domain_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not domain:
            return {'success': False, 'error': _('Domain not found')}

        if not hostname or not ip_address:
            return {'success': False, 'error': _('Hostname and IP address are required')}

        try:
            api = request.env['resellerclub.api']
            api.childns_delete(domain.rc_order_id, hostname, ip_address)
            return {'success': True, 'message': _('Child nameserver removed')}
        except Exception as e:
            _logger.error("Failed to delete child nameserver: %s", str(e))
            return {'success': False, 'error': str(e)}

    # =============================================
    # GET AUTH CODE (for transfer out)
    # =============================================

    @http.route('/my/domains/<int:domain_id>/auth-code', type='json', auth='user', website=True)
    def portal_domain_get_auth_code(self, domain_id, **kw):
        """Get domain authorization/EPP code for transfer."""
        partner = request.env.user.partner_id
        domain = request.env['resellerclub.domain'].search([
            ('id', '=', domain_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not domain:
            return {'success': False, 'error': _('Domain not found')}

        # Domain must be unlocked to get auth code
        if domain.is_locked:
            return {'success': False, 'error': _('Please unlock the domain first to get the authorization code')}

        try:
            api = request.env['resellerclub.api']
            result = api.domain_get_auth_code(domain.rc_order_id)
            auth_code = result if isinstance(result, str) else result.get('authcode', result.get('auth-code', ''))
            return {'success': True, 'auth_code': auth_code}
        except Exception as e:
            _logger.error("Failed to get auth code: %s", str(e))
            return {'success': False, 'error': str(e)}

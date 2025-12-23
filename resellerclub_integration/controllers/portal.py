# -*- coding: utf-8 -*-

from collections import OrderedDict
from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.osv.expression import AND


class ResellerClubPortal(CustomerPortal):
    """Portal controller for ResellerClub services."""

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        partner = request.env.user.partner_id

        if 'domain_count' in counters:
            domain_count = request.env['resellerclub.domain'].search_count([
                ('partner_id', '=', partner.id),
            ])
            values['domain_count'] = domain_count

        if 'hosting_count' in counters:
            hosting_count = request.env['resellerclub.hosting'].search_count([
                ('partner_id', '=', partner.id),
            ])
            values['hosting_count'] = hosting_count

        if 'ssl_count' in counters:
            ssl_count = request.env['resellerclub.ssl'].search_count([
                ('partner_id', '=', partner.id),
            ])
            values['ssl_count'] = ssl_count

        return values

    # =====================
    # Domains Portal
    # =====================

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
        """Display domain details."""
        partner = request.env.user.partner_id
        domain = request.env['resellerclub.domain'].search([
            ('id', '=', domain_id),
            ('partner_id', '=', partner.id),
        ], limit=1)

        if not domain:
            return request.redirect('/my/domains')

        values = {
            'domain': domain,
            'page_name': 'domain_detail',
        }

        return request.render('resellerclub_integration.portal_domain_detail', values)

    # =====================
    # Hosting Portal
    # =====================

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
        """Display hosting details."""
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

    # =====================
    # SSL Portal
    # =====================

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

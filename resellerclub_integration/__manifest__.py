# -*- coding: utf-8 -*-
{
    'name': 'ResellerClub Integration',
    'version': '19.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Complete integration with ResellerClub API for domain, hosting, SSL and more',
    'description': """
ResellerClub Integration for Odoo
=================================

This module provides complete integration with ResellerClub HTTP API allowing you to:

**Domain Management**
- Register new domains
- Transfer domains from other registrars
- Renew domains
- Manage DNS records
- WHOIS privacy protection
- Domain lock/unlock

**Hosting Services**
- Single Domain Hosting
- Multi Domain Hosting
- Reseller Hosting
- Email Hosting

**Server Management**
- VPS Servers
- Dedicated Servers
- Managed Servers

**Security Products**
- SSL Certificates (Thawte, Comodo, etc.)
- SiteLock
- CodeGuard Backup

**Additional Features**
- Customer synchronization with ResellerClub
- Automated order processing
- Service status monitoring
- Renewal reminders and automation
- Customer portal for service management
- Integrated billing and invoicing
- Multi-currency support
- Sandbox/Test mode support

**Technical Features**
- Asynchronous API calls
- Webhook support for status updates
- Comprehensive logging
- Error handling and retry mechanisms
    """,
    'author': 'iteraSoft',
    'website': 'https://www.iterasoft.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'sale_management',
        'account',
        'contacts',
        'product',
        'mail',
        'portal',
        'website_sale',
    ],
    'data': [
        # Security
        'security/resellerclub_security.xml',
        'security/ir.model.access.csv',
        # Data
        'data/product_category_data.xml',
        'data/cron_data.xml',
        'data/mail_template_data.xml',
        # Views
        'views/res_config_settings_views.xml',
        'views/resellerclub_customer_views.xml',
        'views/resellerclub_domain_views.xml',
        'views/resellerclub_hosting_views.xml',
        'views/resellerclub_ssl_views.xml',
        'views/resellerclub_dns_views.xml',
        'views/resellerclub_order_views.xml',
        'views/product_views.xml',
        'views/sale_order_views.xml',
        'views/res_partner_views.xml',
        'views/menu_views.xml',
        # Wizards
        'wizards/domain_register_wizard_views.xml',
        'wizards/domain_transfer_wizard_views.xml',
        'wizards/domain_renew_wizard_views.xml',
        'wizards/hosting_order_wizard_views.xml',
        # Portal
        'views/portal_templates.xml',
        # Reports
        'reports/service_report_templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'resellerclub_integration/static/src/css/resellerclub.css',
            'resellerclub_integration/static/src/js/domain_availability.js',
        ],
        'web.assets_frontend': [
            'resellerclub_integration/static/src/css/portal.css',
        ],
    },
    'demo': [
        'demo/demo_data.xml',
    ],
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': True,
    'auto_install': False,
    'sequence': 10,
    'external_dependencies': {
        'python': ['requests'],
    },
}

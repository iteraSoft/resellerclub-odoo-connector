# -*- coding: utf-8 -*-
{
    'name': 'ResellerClub Integration',
    'version': '19.0.1.1.0',
    'category': 'Sales/Subscriptions',
    'summary': 'Complete ResellerClub integration with Odoo Subscriptions for domains, hosting & SSL',
    'description': """
ResellerClub Integration for Odoo
=================================

Complete integration with ResellerClub HTTP API, fully integrated with Odoo's
Subscription module for automated recurring billing and service management.

**Domain Management**
- Register, transfer, and renew domains
- DNS record management (A, AAAA, CNAME, MX, TXT, NS, SRV)
- WHOIS privacy protection
- Domain lock/unlock (theft protection)
- Automatic renewal via subscriptions

**Hosting Services**
- Single Domain, Multi Domain, and Reseller Hosting
- Email Hosting with account management
- VPS and Dedicated Servers
- Automatic provisioning and renewal

**SSL Certificates**
- DV, OV, and EV certificates
- Wildcard and Multi-domain (SAN)
- CSR generation and enrollment
- Automatic renewal notifications

**Subscription Integration**
- Recurring billing via Odoo Subscriptions
- Automatic invoice generation
- Customer self-service portal
- Subscription upsell/cross-sell
- Renewal automation with payment tokenization

**Standard Odoo Features**
- Full activity/chatter integration
- Automated scheduled actions
- Email templates for notifications
- Multi-company support
- Customer portal access
- PDF reports
    """,
    'author': 'iteraSoft',
    'website': 'https://www.iterasoft.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'sale_management',
        'sale_subscription',  # Subscription management
        'account',
        'contacts',
        'product',
        'mail',
        'portal',
        'website',  # Multi-website support
        'website_sale',  # E-commerce integration
        'utm',  # Campaign tracking
        'rating',  # Customer satisfaction
    ],
    'data': [
        # Security
        'security/resellerclub_security.xml',
        'security/ir.model.access.csv',
        # Data
        'data/product_category_data.xml',
        'data/subscription_plan_data.xml',
        'data/cron_data.xml',
        'data/mail_template_data.xml',
        'data/activity_type_data.xml',
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
        # Website Templates
        'views/website_templates.xml',
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

# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class ResCompany(models.Model):
    _inherit = 'res.company'

    # ResellerClub API Credentials
    resellerclub_auth_userid = fields.Char(
        string='Reseller ID',
        help="Your ResellerClub Reseller ID (auth-userid)"
    )
    resellerclub_api_key = fields.Char(
        string='API Key',
        help="Your ResellerClub API Key"
    )
    resellerclub_test_mode = fields.Boolean(
        string='Test Mode (Sandbox)',
        default=True,
        help="Enable to use the ResellerClub sandbox/test environment"
    )

    # Default Settings
    resellerclub_default_ns1 = fields.Char(
        string='Default Nameserver 1',
        default='ns1.onlyfordemo.net',
        help="Default primary nameserver for domain registrations"
    )
    resellerclub_default_ns2 = fields.Char(
        string='Default Nameserver 2',
        default='ns2.onlyfordemo.net',
        help="Default secondary nameserver for domain registrations"
    )
    resellerclub_default_ns3 = fields.Char(
        string='Default Nameserver 3',
        help="Optional third nameserver"
    )
    resellerclub_default_ns4 = fields.Char(
        string='Default Nameserver 4',
        help="Optional fourth nameserver"
    )

    # Automation Settings
    resellerclub_auto_create_customer = fields.Boolean(
        string='Auto Create Customers',
        default=True,
        help="Automatically create customers in ResellerClub when creating partners in Odoo"
    )
    resellerclub_auto_sync_orders = fields.Boolean(
        string='Auto Sync Orders',
        default=True,
        help="Automatically synchronize order status from ResellerClub"
    )
    resellerclub_sync_interval = fields.Integer(
        string='Sync Interval (hours)',
        default=4,
        help="How often to synchronize data with ResellerClub (in hours)"
    )

    # Notification Settings
    resellerclub_renewal_reminder_days = fields.Integer(
        string='Renewal Reminder Days',
        default=30,
        help="Days before expiration to send renewal reminders"
    )
    resellerclub_send_customer_emails = fields.Boolean(
        string='Send Customer Emails',
        default=True,
        help="Send email notifications to customers for domain/hosting events"
    )

    # Pricing Settings
    resellerclub_domain_margin = fields.Float(
        string='Domain Margin (%)',
        default=20.0,
        help="Default markup percentage for domain pricing"
    )
    resellerclub_hosting_margin = fields.Float(
        string='Hosting Margin (%)',
        default=25.0,
        help="Default markup percentage for hosting pricing"
    )
    resellerclub_ssl_margin = fields.Float(
        string='SSL Margin (%)',
        default=30.0,
        help="Default markup percentage for SSL certificate pricing"
    )


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # API Credentials
    resellerclub_auth_userid = fields.Char(
        related='company_id.resellerclub_auth_userid',
        readonly=False,
        string='Reseller ID'
    )
    resellerclub_api_key = fields.Char(
        related='company_id.resellerclub_api_key',
        readonly=False,
        string='API Key'
    )
    resellerclub_test_mode = fields.Boolean(
        related='company_id.resellerclub_test_mode',
        readonly=False,
        string='Test Mode (Sandbox)'
    )

    # Default Nameservers
    resellerclub_default_ns1 = fields.Char(
        related='company_id.resellerclub_default_ns1',
        readonly=False
    )
    resellerclub_default_ns2 = fields.Char(
        related='company_id.resellerclub_default_ns2',
        readonly=False
    )
    resellerclub_default_ns3 = fields.Char(
        related='company_id.resellerclub_default_ns3',
        readonly=False
    )
    resellerclub_default_ns4 = fields.Char(
        related='company_id.resellerclub_default_ns4',
        readonly=False
    )

    # Automation Settings
    resellerclub_auto_create_customer = fields.Boolean(
        related='company_id.resellerclub_auto_create_customer',
        readonly=False
    )
    resellerclub_auto_sync_orders = fields.Boolean(
        related='company_id.resellerclub_auto_sync_orders',
        readonly=False
    )
    resellerclub_sync_interval = fields.Integer(
        related='company_id.resellerclub_sync_interval',
        readonly=False
    )

    # Notification Settings
    resellerclub_renewal_reminder_days = fields.Integer(
        related='company_id.resellerclub_renewal_reminder_days',
        readonly=False
    )
    resellerclub_send_customer_emails = fields.Boolean(
        related='company_id.resellerclub_send_customer_emails',
        readonly=False
    )

    # Pricing Settings
    resellerclub_domain_margin = fields.Float(
        related='company_id.resellerclub_domain_margin',
        readonly=False
    )
    resellerclub_hosting_margin = fields.Float(
        related='company_id.resellerclub_hosting_margin',
        readonly=False
    )
    resellerclub_ssl_margin = fields.Float(
        related='company_id.resellerclub_ssl_margin',
        readonly=False
    )

    # Display Fields (not stored)
    resellerclub_balance = fields.Float(
        string='Account Balance',
        compute='_compute_resellerclub_balance'
    )
    resellerclub_connection_status = fields.Selection([
        ('not_configured', 'Not Configured'),
        ('connected', 'Connected'),
        ('error', 'Connection Error'),
    ], string='Connection Status', compute='_compute_resellerclub_connection_status')

    @api.depends('resellerclub_auth_userid', 'resellerclub_api_key')
    def _compute_resellerclub_balance(self):
        for record in self:
            record.resellerclub_balance = 0.0
            if record.resellerclub_auth_userid and record.resellerclub_api_key:
                try:
                    api = self.env['resellerclub.api']
                    result = api.reseller_get_balance()
                    if isinstance(result, dict):
                        record.resellerclub_balance = float(result.get('sellingcurrencybalance', 0))
                except Exception:
                    pass

    @api.depends('resellerclub_auth_userid', 'resellerclub_api_key')
    def _compute_resellerclub_connection_status(self):
        for record in self:
            if not record.resellerclub_auth_userid or not record.resellerclub_api_key:
                record.resellerclub_connection_status = 'not_configured'
            else:
                try:
                    api = self.env['resellerclub.api']
                    api.reseller_get_balance()
                    record.resellerclub_connection_status = 'connected'
                except Exception:
                    record.resellerclub_connection_status = 'error'

    def action_test_connection(self):
        """Test the connection to ResellerClub API."""
        self.ensure_one()
        if not self.resellerclub_auth_userid or not self.resellerclub_api_key:
            raise UserError(_("Please configure your Reseller ID and API Key first."))

        try:
            api = self.env['resellerclub.api']
            result = api.reseller_get_balance()

            if isinstance(result, dict) and 'sellingcurrencybalance' in result:
                balance = result.get('sellingcurrencybalance', 0)
                currency = result.get('sellingcurrency', 'USD')
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Connection Successful'),
                        'message': _('Connected to ResellerClub. Account Balance: %s %s') % (balance, currency),
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                raise UserError(_("Unexpected response from ResellerClub API."))

        except Exception as e:
            raise UserError(_("Connection failed: %s") % str(e))

    def action_sync_products(self):
        """Synchronize products from ResellerClub."""
        self.ensure_one()
        try:
            # Sync domain TLD pricing
            domain_count = self.env['product.template']._sync_resellerclub_domains()

            # Sync hosting plans
            hosting_count = self.env['product.template']._sync_resellerclub_hosting()

            # Sync SSL plans
            ssl_count = self.env['product.template']._sync_resellerclub_ssl()

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Sync Complete'),
                    'message': _('Synchronized %d domains, %d hosting plans, %d SSL plans') % (
                        domain_count, hosting_count, ssl_count
                    ),
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            raise UserError(_("Sync failed: %s") % str(e))

    def action_view_api_logs(self):
        """View API call logs."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('API Logs'),
            'res_model': 'resellerclub.api.log',
            'view_mode': 'list,form',
            'domain': [('company_id', '=', self.env.company.id)],
            'context': {'default_company_id': self.env.company.id},
        }

    def action_refresh_balance(self):
        """Refresh the account balance display."""
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

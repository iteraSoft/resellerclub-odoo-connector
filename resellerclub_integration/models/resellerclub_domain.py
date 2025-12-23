# -*- coding: utf-8 -*-

import logging
from datetime import datetime, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class ResellerClubDomain(models.Model):
    """
    Model to manage domain registrations from ResellerClub.

    This model stores domain information and provides methods for
    registration, renewal, transfer, and DNS management.
    """
    _name = 'resellerclub.domain'
    _description = 'ResellerClub Domain'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'expiration_date asc'
    _rec_name = 'domain_name'

    domain_name = fields.Char(
        string='Domain Name',
        required=True,
        index=True,
        tracking=True
    )
    tld = fields.Char(
        string='TLD',
        compute='_compute_tld',
        store=True
    )
    sld = fields.Char(
        string='SLD',
        compute='_compute_tld',
        store=True,
        help="Second Level Domain (name without TLD)"
    )

    # ResellerClub IDs
    resellerclub_order_id = fields.Char(
        string='RC Order ID',
        index=True,
        tracking=True
    )
    resellerclub_entity_id = fields.Char(
        string='RC Entity ID'
    )

    # Customer & Partner
    customer_id = fields.Many2one(
        'resellerclub.customer',
        string='RC Customer',
        required=True,
        ondelete='restrict',
        index=True
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        related='customer_id.partner_id',
        store=True
    )

    # Status & Dates
    status = fields.Selection([
        ('pending', 'Pending Registration'),
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('deleted', 'Deleted'),
        ('suspended', 'Suspended'),
        ('pending_transfer', 'Pending Transfer'),
        ('transfer_failed', 'Transfer Failed'),
        ('redemption', 'Redemption Period'),
    ], string='Status', default='pending', tracking=True, index=True)

    registration_date = fields.Date(
        string='Registration Date',
        tracking=True
    )
    expiration_date = fields.Date(
        string='Expiration Date',
        tracking=True,
        index=True
    )
    days_until_expiry = fields.Integer(
        string='Days Until Expiry',
        compute='_compute_days_until_expiry',
        store=True
    )
    expiry_status = fields.Selection([
        ('ok', 'OK'),
        ('warning', 'Expiring Soon'),
        ('critical', 'Critical'),
        ('expired', 'Expired'),
    ], string='Expiry Status', compute='_compute_days_until_expiry', store=True)

    years = fields.Integer(
        string='Registration Years',
        default=1
    )
    auto_renew = fields.Boolean(
        string='Auto Renew',
        default=False,
        tracking=True
    )

    # Domain Settings
    privacy_protection = fields.Boolean(
        string='Privacy Protection',
        default=False,
        tracking=True,
        help="WHOIS Privacy Protection enabled"
    )
    theft_protection = fields.Boolean(
        string='Theft Protection',
        default=True,
        tracking=True,
        help="Domain transfer lock enabled"
    )

    # Nameservers
    ns1 = fields.Char(string='Nameserver 1')
    ns2 = fields.Char(string='Nameserver 2')
    ns3 = fields.Char(string='Nameserver 3')
    ns4 = fields.Char(string='Nameserver 4')
    ns5 = fields.Char(string='Nameserver 5')

    # Contacts
    registrant_contact_id = fields.Char(string='Registrant Contact ID')
    admin_contact_id = fields.Char(string='Admin Contact ID')
    tech_contact_id = fields.Char(string='Tech Contact ID')
    billing_contact_id = fields.Char(string='Billing Contact ID')

    # Transfer fields
    auth_code = fields.Char(
        string='Auth/EPP Code',
        help="Authorization code for domain transfers"
    )
    transfer_status = fields.Char(string='Transfer Status')

    # Related records
    dns_record_ids = fields.One2many(
        'resellerclub.dns.record',
        'domain_id',
        string='DNS Records'
    )
    order_line_ids = fields.One2many(
        'sale.order.line',
        'rc_domain_id',
        string='Order Lines'
    )

    # Sync tracking
    last_sync_date = fields.Datetime(
        string='Last Synchronized',
        readonly=True
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True
    )

    # WHOIS data (cached)
    whois_data = fields.Text(
        string='WHOIS Data',
        readonly=True
    )

    notes = fields.Text(string='Internal Notes')

    _sql_constraints = [
        ('domain_company_uniq', 'unique(domain_name, company_id)',
         'Domain name must be unique per company!'),
    ]

    @api.depends('domain_name')
    def _compute_tld(self):
        for record in self:
            if record.domain_name and '.' in record.domain_name:
                parts = record.domain_name.rsplit('.', 1)
                record.sld = parts[0]
                record.tld = parts[1]
            else:
                record.sld = record.domain_name
                record.tld = ''

    @api.depends('expiration_date')
    def _compute_days_until_expiry(self):
        today = fields.Date.today()
        for record in self:
            if record.expiration_date:
                delta = record.expiration_date - today
                record.days_until_expiry = delta.days

                if delta.days < 0:
                    record.expiry_status = 'expired'
                elif delta.days <= 7:
                    record.expiry_status = 'critical'
                elif delta.days <= 30:
                    record.expiry_status = 'warning'
                else:
                    record.expiry_status = 'ok'
            else:
                record.days_until_expiry = 0
                record.expiry_status = 'ok'

    @api.constrains('domain_name')
    def _check_domain_name(self):
        import re
        domain_pattern = re.compile(
            r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$'
        )
        for record in self:
            if record.domain_name and not domain_pattern.match(record.domain_name):
                raise ValidationError(
                    _("Invalid domain name format: %s") % record.domain_name
                )

    def action_register_domain(self):
        """Register the domain in ResellerClub."""
        self.ensure_one()

        if self.resellerclub_order_id:
            raise UserError(_("Domain already registered with Order ID: %s") % self.resellerclub_order_id)

        if not self.customer_id.resellerclub_customer_id:
            raise UserError(_("Customer must be created in ResellerClub first."))

        api = self.env['resellerclub.api']
        company = self.env.company

        # Prepare nameservers
        nameservers = [ns for ns in [self.ns1, self.ns2, self.ns3, self.ns4, self.ns5] if ns]
        if not nameservers:
            nameservers = [
                company.resellerclub_default_ns1,
                company.resellerclub_default_ns2,
            ]
            if company.resellerclub_default_ns3:
                nameservers.append(company.resellerclub_default_ns3)
            if company.resellerclub_default_ns4:
                nameservers.append(company.resellerclub_default_ns4)

        # Get contact IDs
        contact_id = self.customer_id.default_contact_id
        if not contact_id:
            raise UserError(_("Customer has no default contact. Please create one first."))

        contact_ids = {
            'registrant': self.registrant_contact_id or contact_id,
            'admin': self.admin_contact_id or contact_id,
            'tech': self.tech_contact_id or contact_id,
            'billing': self.billing_contact_id or contact_id,
        }

        try:
            result = api.domain_register(
                domain_name=self.domain_name,
                years=self.years,
                customer_id=self.customer_id.resellerclub_customer_id,
                contact_ids=contact_ids,
                nameservers=nameservers,
                privacy_protection=self.privacy_protection,
                purchase_privacy=self.privacy_protection,
            )

            # Parse response
            order_id = None
            if isinstance(result, dict):
                order_id = result.get('orderid') or result.get('entityid')
            elif isinstance(result, (int, str)):
                order_id = str(result)

            if order_id:
                self.write({
                    'resellerclub_order_id': str(order_id),
                    'status': 'active',
                    'registration_date': fields.Date.today(),
                    'expiration_date': fields.Date.today() + timedelta(days=365 * self.years),
                    'ns1': nameservers[0] if len(nameservers) > 0 else False,
                    'ns2': nameservers[1] if len(nameservers) > 1 else False,
                    'ns3': nameservers[2] if len(nameservers) > 2 else False,
                    'ns4': nameservers[3] if len(nameservers) > 3 else False,
                    'last_sync_date': fields.Datetime.now(),
                })

                self.message_post(
                    body=_("Domain registered successfully. Order ID: %s") % order_id,
                    message_type='notification'
                )
            else:
                raise UserError(_("Registration failed: No order ID returned"))

        except Exception as e:
            self.message_post(
                body=_("Domain registration failed: %s") % str(e),
                message_type='notification'
            )
            raise

        return True

    def action_renew_domain(self):
        """Open the domain renewal wizard."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Renew Domain'),
            'res_model': 'resellerclub.domain.renew.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_domain_id': self.id,
                'default_years': 1,
            },
        }

    def action_transfer_domain(self):
        """Open the domain transfer wizard."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Transfer Domain'),
            'res_model': 'resellerclub.domain.transfer.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_domain_name': self.domain_name,
                'default_customer_id': self.customer_id.id,
            },
        }

    def action_sync_from_resellerclub(self):
        """Sync domain details from ResellerClub."""
        self.ensure_one()

        if not self.resellerclub_order_id:
            raise UserError(_("No ResellerClub Order ID set."))

        api = self.env['resellerclub.api']

        try:
            result = api.domain_get_details(order_id=self.resellerclub_order_id)

            if isinstance(result, dict):
                # Parse expiration date
                exp_timestamp = result.get('endtime')
                exp_date = None
                if exp_timestamp:
                    exp_date = datetime.fromtimestamp(int(exp_timestamp)).date()

                # Parse registration date
                reg_timestamp = result.get('creationtime')
                reg_date = None
                if reg_timestamp:
                    reg_date = datetime.fromtimestamp(int(reg_timestamp)).date()

                # Map status
                rc_status = result.get('orderstatus', '').lower()
                status_map = {
                    'active': 'active',
                    'inactive': 'expired',
                    'deleted': 'deleted',
                    'suspended': 'suspended',
                    'pendingtransfer': 'pending_transfer',
                    'redemption': 'redemption',
                }
                status = status_map.get(rc_status, 'pending')

                self.write({
                    'status': status,
                    'registration_date': reg_date,
                    'expiration_date': exp_date,
                    'ns1': result.get('ns1'),
                    'ns2': result.get('ns2'),
                    'ns3': result.get('ns3'),
                    'ns4': result.get('ns4'),
                    'privacy_protection': result.get('privacyprotectedalllevels') == 'true',
                    'theft_protection': result.get('orderstatus') != 'unlocked',
                    'registrant_contact_id': result.get('registrantcontactid'),
                    'admin_contact_id': result.get('admincontactid'),
                    'tech_contact_id': result.get('techcontactid'),
                    'billing_contact_id': result.get('billingcontactid'),
                    'last_sync_date': fields.Datetime.now(),
                })

                self.message_post(
                    body=_("Domain synchronized from ResellerClub"),
                    message_type='notification'
                )

        except Exception as e:
            self.message_post(
                body=_("Sync failed: %s") % str(e),
                message_type='notification'
            )
            raise

        return True

    def action_get_auth_code(self):
        """Get the EPP/authorization code for domain transfer."""
        self.ensure_one()

        if not self.resellerclub_order_id:
            raise UserError(_("Domain must be registered first."))

        api = self.env['resellerclub.api']

        try:
            result = api.domain_get_auth_code(order_id=self.resellerclub_order_id)

            if isinstance(result, dict) and 'authcode' in result:
                self.auth_code = result['authcode']
            elif isinstance(result, str):
                self.auth_code = result

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Authorization Code'),
                    'message': _('Auth Code: %s') % self.auth_code,
                    'type': 'success',
                    'sticky': True,
                }
            }

        except Exception as e:
            raise UserError(_("Failed to get auth code: %s") % str(e))

    def action_toggle_theft_protection(self):
        """Toggle domain theft protection (lock/unlock)."""
        self.ensure_one()

        if not self.resellerclub_order_id:
            raise UserError(_("Domain must be registered first."))

        api = self.env['resellerclub.api']

        try:
            if self.theft_protection:
                api.domain_disable_theft_protection(order_id=self.resellerclub_order_id)
                self.theft_protection = False
                msg = _("Theft protection disabled")
            else:
                api.domain_enable_theft_protection(order_id=self.resellerclub_order_id)
                self.theft_protection = True
                msg = _("Theft protection enabled")

            self.message_post(body=msg, message_type='notification')

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Theft Protection'),
                    'message': msg,
                    'type': 'success',
                    'sticky': False,
                }
            }

        except Exception as e:
            raise UserError(_("Failed to toggle theft protection: %s") % str(e))

    def action_modify_nameservers(self):
        """Update nameservers for the domain."""
        self.ensure_one()

        if not self.resellerclub_order_id:
            raise UserError(_("Domain must be registered first."))

        nameservers = [ns for ns in [self.ns1, self.ns2, self.ns3, self.ns4, self.ns5] if ns]
        if len(nameservers) < 2:
            raise UserError(_("At least 2 nameservers are required."))

        api = self.env['resellerclub.api']

        try:
            api.domain_modify_nameservers(
                order_id=self.resellerclub_order_id,
                nameservers=nameservers
            )

            self.message_post(
                body=_("Nameservers updated successfully"),
                message_type='notification'
            )

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Nameservers Updated'),
                    'message': _('Nameservers have been updated successfully.'),
                    'type': 'success',
                    'sticky': False,
                }
            }

        except Exception as e:
            raise UserError(_("Failed to update nameservers: %s") % str(e))

    def action_manage_dns(self):
        """Open DNS management view."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('DNS Records - %s') % self.domain_name,
            'res_model': 'resellerclub.dns.record',
            'view_mode': 'list,form',
            'domain': [('domain_id', '=', self.id)],
            'context': {
                'default_domain_id': self.id,
                'default_domain_name': self.domain_name,
            },
        }

    @api.model
    def check_domain_availability(self, domain_name, tlds=None):
        """
        Check if a domain is available for registration.

        :param domain_name: Domain name without TLD
        :param tlds: List of TLDs to check (default: common TLDs)
        :return: Dictionary with availability results
        """
        if not tlds:
            tlds = ['com', 'net', 'org', 'info', 'biz', 'co']

        api = self.env['resellerclub.api']
        return api.domain_check_availability(domain_name, tlds)

    @api.model
    def cron_sync_domains(self):
        """Cron job to sync all domains with ResellerClub."""
        domains = self.search([
            ('resellerclub_order_id', '!=', False),
            ('status', 'in', ['active', 'pending', 'suspended']),
        ])

        for domain in domains:
            try:
                domain.action_sync_from_resellerclub()
            except Exception as e:
                _logger.warning("Failed to sync domain %s: %s", domain.domain_name, str(e))

        return True

    @api.model
    def cron_expiry_notifications(self):
        """Cron job to send expiry notifications."""
        company = self.env.company
        reminder_days = company.resellerclub_renewal_reminder_days or 30

        expiring_domains = self.search([
            ('status', '=', 'active'),
            ('days_until_expiry', '<=', reminder_days),
            ('days_until_expiry', '>', 0),
        ])

        for domain in expiring_domains:
            # Check if we already sent a reminder recently
            recent_activities = self.env['mail.activity'].search([
                ('res_model', '=', 'resellerclub.domain'),
                ('res_id', '=', domain.id),
                ('activity_type_id.name', '=', 'To Do'),
                ('create_date', '>=', fields.Date.today() - timedelta(days=7)),
            ])

            if not recent_activities:
                # Create activity for renewal reminder
                domain.activity_schedule(
                    'mail.mail_activity_data_todo',
                    date_deadline=domain.expiration_date - timedelta(days=7),
                    summary=_('Domain Expiring Soon'),
                    note=_('Domain %s expires on %s. Consider renewing.') % (
                        domain.domain_name,
                        domain.expiration_date
                    ),
                )

                # Send email if configured
                if company.resellerclub_send_customer_emails and domain.partner_id.email:
                    template = self.env.ref(
                        'resellerclub_integration.mail_template_domain_expiry',
                        raise_if_not_found=False
                    )
                    if template:
                        template.send_mail(domain.id, force_send=True)

        return True

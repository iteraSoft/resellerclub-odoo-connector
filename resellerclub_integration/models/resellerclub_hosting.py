# -*- coding: utf-8 -*-

import logging
from datetime import datetime, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResellerClubHosting(models.Model):
    """
    Model to manage hosting services from ResellerClub.

    Supports various hosting types including:
    - Single Domain Hosting
    - Multi Domain Hosting
    - Reseller Hosting
    - Email Hosting
    - VPS and Dedicated Servers
    """
    _name = 'resellerclub.hosting'
    _description = 'ResellerClub Hosting'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'expiration_date asc'
    _rec_name = 'display_name'

    display_name = fields.Char(
        string='Name',
        compute='_compute_display_name',
        store=True
    )

    # Basic Info
    domain_name = fields.Char(
        string='Domain Name',
        required=True,
        index=True,
        tracking=True
    )
    hosting_type = fields.Selection([
        ('single', 'Single Domain Hosting'),
        ('multi', 'Multi Domain Hosting'),
        ('reseller', 'Reseller Hosting'),
        ('email', 'Email Hosting'),
        ('vps', 'VPS Server'),
        ('dedicated', 'Dedicated Server'),
        ('managed', 'Managed Server'),
        ('sitebuilder', 'Website Builder'),
    ], string='Hosting Type', required=True, default='single', tracking=True)

    plan_id = fields.Char(string='Plan ID')
    plan_name = fields.Char(string='Plan Name', tracking=True)

    # ResellerClub IDs
    resellerclub_order_id = fields.Char(
        string='RC Order ID',
        index=True,
        tracking=True
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
        ('pending', 'Pending Setup'),
        ('active', 'Active'),
        ('suspended', 'Suspended'),
        ('expired', 'Expired'),
        ('deleted', 'Deleted'),
    ], string='Status', default='pending', tracking=True, index=True)

    creation_date = fields.Date(string='Creation Date')
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

    months = fields.Integer(
        string='Billing Period (Months)',
        default=12
    )
    auto_renew = fields.Boolean(
        string='Auto Renew',
        default=False,
        tracking=True
    )

    # Resource Limits
    disk_space = fields.Char(string='Disk Space')
    bandwidth = fields.Char(string='Bandwidth')
    email_accounts = fields.Integer(string='Email Accounts')
    databases = fields.Integer(string='Databases')
    ftp_accounts = fields.Integer(string='FTP Accounts')
    addon_domains = fields.Integer(string='Addon Domains')
    subdomains = fields.Integer(string='Subdomains')

    # Server Info (for VPS/Dedicated)
    ip_address = fields.Char(string='IP Address')
    root_password = fields.Char(string='Root Password')
    os_name = fields.Char(string='Operating System')
    ram = fields.Char(string='RAM')
    cpu = fields.Char(string='CPU')

    # Control Panel
    cpanel_username = fields.Char(string='cPanel Username')
    cpanel_password = fields.Char(string='cPanel Password')
    control_panel_url = fields.Char(string='Control Panel URL')

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

    notes = fields.Text(string='Internal Notes')

    _sql_constraints = [
        ('order_id_company_uniq', 'unique(resellerclub_order_id, company_id)',
         'Order ID must be unique per company!'),
    ]

    @api.depends('domain_name', 'hosting_type')
    def _compute_display_name(self):
        type_names = dict(self._fields['hosting_type'].selection)
        for record in self:
            type_name = type_names.get(record.hosting_type, 'Hosting')
            record.display_name = f"{record.domain_name} ({type_name})"

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

    def action_order_hosting(self):
        """Order hosting from ResellerClub."""
        self.ensure_one()

        if self.resellerclub_order_id:
            raise UserError(_("Hosting already ordered with ID: %s") % self.resellerclub_order_id)

        if not self.customer_id.resellerclub_customer_id:
            raise UserError(_("Customer must be created in ResellerClub first."))

        if not self.plan_id:
            raise UserError(_("Please select a hosting plan."))

        api = self.env['resellerclub.api']

        try:
            if self.hosting_type == 'email':
                result = api.email_order(
                    domain_name=self.domain_name,
                    customer_id=self.customer_id.resellerclub_customer_id,
                    plan_id=self.plan_id,
                    months=self.months,
                    num_accounts=self.email_accounts or 5,
                )
            else:
                result = api.hosting_order(
                    domain_name=self.domain_name,
                    customer_id=self.customer_id.resellerclub_customer_id,
                    plan_id=self.plan_id,
                    months=self.months,
                    autorenew=self.auto_renew,
                )

            order_id = None
            if isinstance(result, dict):
                order_id = result.get('orderid') or result.get('entityid')
            elif isinstance(result, (int, str)):
                order_id = str(result)

            if order_id:
                self.write({
                    'resellerclub_order_id': str(order_id),
                    'status': 'active',
                    'creation_date': fields.Date.today(),
                    'expiration_date': fields.Date.today() + timedelta(days=30 * self.months),
                    'last_sync_date': fields.Datetime.now(),
                })

                self.message_post(
                    body=_("Hosting ordered successfully. Order ID: %s") % order_id,
                    message_type='notification'
                )
            else:
                raise UserError(_("Order failed: No order ID returned"))

        except Exception as e:
            self.message_post(
                body=_("Hosting order failed: %s") % str(e),
                message_type='notification'
            )
            raise

        return True

    def action_renew_hosting(self):
        """Renew hosting subscription."""
        self.ensure_one()

        if not self.resellerclub_order_id:
            raise UserError(_("Hosting must be ordered first."))

        api = self.env['resellerclub.api']

        try:
            exp_timestamp = int(datetime.combine(
                self.expiration_date,
                datetime.min.time()
            ).timestamp()) if self.expiration_date else 0

            if self.hosting_type == 'email':
                result = api.email_renew(
                    order_id=self.resellerclub_order_id,
                    months=self.months,
                    exp_date=exp_timestamp,
                    num_accounts=self.email_accounts or 5,
                )
            else:
                result = api.hosting_renew(
                    order_id=self.resellerclub_order_id,
                    months=self.months,
                    exp_date=exp_timestamp,
                )

            # Update expiration date
            if self.expiration_date:
                new_exp = self.expiration_date + timedelta(days=30 * self.months)
            else:
                new_exp = fields.Date.today() + timedelta(days=30 * self.months)

            self.write({
                'expiration_date': new_exp,
                'last_sync_date': fields.Datetime.now(),
            })

            self.message_post(
                body=_("Hosting renewed for %d months. New expiration: %s") % (
                    self.months, new_exp
                ),
                message_type='notification'
            )

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Hosting Renewed'),
                    'message': _('Hosting renewed successfully until %s') % new_exp,
                    'type': 'success',
                    'sticky': False,
                }
            }

        except Exception as e:
            raise UserError(_("Renewal failed: %s") % str(e))

    def action_sync_from_resellerclub(self):
        """Sync hosting details from ResellerClub."""
        self.ensure_one()

        if not self.resellerclub_order_id:
            raise UserError(_("No ResellerClub Order ID set."))

        api = self.env['resellerclub.api']

        try:
            if self.hosting_type == 'email':
                result = api.email_get_details(order_id=self.resellerclub_order_id)
            else:
                result = api.hosting_get_details(order_id=self.resellerclub_order_id)

            if isinstance(result, dict):
                # Parse dates
                exp_timestamp = result.get('endtime')
                exp_date = None
                if exp_timestamp:
                    exp_date = datetime.fromtimestamp(int(exp_timestamp)).date()

                creation_timestamp = result.get('creationtime')
                creation_date = None
                if creation_timestamp:
                    creation_date = datetime.fromtimestamp(int(creation_timestamp)).date()

                # Map status
                rc_status = result.get('orderstatus', '').lower()
                status_map = {
                    'active': 'active',
                    'inactive': 'expired',
                    'deleted': 'deleted',
                    'suspended': 'suspended',
                }
                status = status_map.get(rc_status, 'pending')

                update_vals = {
                    'status': status,
                    'creation_date': creation_date,
                    'expiration_date': exp_date,
                    'plan_name': result.get('planname'),
                    'last_sync_date': fields.Datetime.now(),
                }

                # Hosting specific fields
                if result.get('diskspace'):
                    update_vals['disk_space'] = result.get('diskspace')
                if result.get('bandwidth'):
                    update_vals['bandwidth'] = result.get('bandwidth')

                self.write(update_vals)

                self.message_post(
                    body=_("Hosting synchronized from ResellerClub"),
                    message_type='notification'
                )

        except Exception as e:
            self.message_post(
                body=_("Sync failed: %s") % str(e),
                message_type='notification'
            )
            raise

        return True

    def action_upgrade_plan(self):
        """Open upgrade plan wizard."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Upgrade Hosting Plan'),
            'res_model': 'resellerclub.hosting.upgrade.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_hosting_id': self.id,
            },
        }

    def action_open_control_panel(self):
        """Open the hosting control panel."""
        self.ensure_one()
        if self.control_panel_url:
            return {
                'type': 'ir.actions.act_url',
                'url': self.control_panel_url,
                'target': 'new',
            }
        raise UserError(_("Control panel URL not available."))

    def action_suspend(self):
        """Suspend the hosting account."""
        self.ensure_one()
        if not self.resellerclub_order_id:
            raise UserError(_("Hosting must be ordered first."))

        api = self.env['resellerclub.api']
        try:
            api.order_suspend(
                order_id=self.resellerclub_order_id,
                reason="Suspended from Odoo"
            )
            self.status = 'suspended'
            self.message_post(
                body=_("Hosting suspended"),
                message_type='notification'
            )
        except Exception as e:
            raise UserError(_("Failed to suspend: %s") % str(e))

        return True

    def action_unsuspend(self):
        """Unsuspend the hosting account."""
        self.ensure_one()
        if not self.resellerclub_order_id:
            raise UserError(_("Hosting must be ordered first."))

        api = self.env['resellerclub.api']
        try:
            api.order_unsuspend(order_id=self.resellerclub_order_id)
            self.status = 'active'
            self.message_post(
                body=_("Hosting unsuspended"),
                message_type='notification'
            )
        except Exception as e:
            raise UserError(_("Failed to unsuspend: %s") % str(e))

        return True

    @api.model
    def cron_sync_hosting(self):
        """Cron job to sync all hosting services."""
        hostings = self.search([
            ('resellerclub_order_id', '!=', False),
            ('status', 'in', ['active', 'pending', 'suspended']),
        ])

        for hosting in hostings:
            try:
                hosting.action_sync_from_resellerclub()
            except Exception as e:
                _logger.warning("Failed to sync hosting %s: %s", hosting.id, str(e))

        return True

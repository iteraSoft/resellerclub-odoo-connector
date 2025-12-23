# -*- coding: utf-8 -*-

import logging
from datetime import datetime, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResellerClubService(models.Model):
    """
    Abstract base model for all ResellerClub services.

    This model provides common functionality for services that can be
    managed as subscriptions, including:
    - Link to sale.order subscriptions
    - Automatic renewal handling
    - Expiry notification scheduling
    - Standard Odoo mixins integration
    """
    _name = 'resellerclub.service.mixin'
    _description = 'ResellerClub Service Mixin'

    # Subscription Integration
    subscription_id = fields.Many2one(
        'sale.order',
        string='Subscription',
        domain="[('is_subscription', '=', True)]",
        help="Related subscription order for recurring billing"
    )
    subscription_state = fields.Selection(
        related='subscription_id.subscription_state',
        string='Subscription Status',
        store=True
    )

    # Common service fields
    is_auto_renew = fields.Boolean(
        string='Auto Renew',
        default=True,
        help="Automatically renew this service through the subscription"
    )
    renewal_reminder_sent = fields.Boolean(
        string='Renewal Reminder Sent',
        default=False
    )
    last_renewal_date = fields.Date(
        string='Last Renewal Date'
    )
    next_renewal_date = fields.Date(
        string='Next Renewal Date',
        compute='_compute_next_renewal_date',
        store=True
    )

    def _compute_next_renewal_date(self):
        """Compute next renewal date based on subscription."""
        for record in self:
            if record.subscription_id and record.subscription_id.next_invoice_date:
                record.next_renewal_date = record.subscription_id.next_invoice_date
            elif hasattr(record, 'expiration_date') and record.expiration_date:
                record.next_renewal_date = record.expiration_date
            else:
                record.next_renewal_date = False

    def _prepare_subscription_values(self, partner, plan, product):
        """
        Prepare values for creating a subscription order.

        :param partner: res.partner record
        :param plan: sale.subscription.plan record
        :param product: product.product record
        :return: dict of values for sale.order creation
        """
        return {
            'partner_id': partner.id,
            'is_subscription': True,
            'plan_id': plan.id,
            'order_line': [(0, 0, {
                'product_id': product.id,
                'product_uom_qty': 1,
            })],
        }

    def action_create_subscription(self):
        """Create a subscription order for this service."""
        self.ensure_one()
        raise NotImplementedError(
            "Subclasses must implement action_create_subscription"
        )

    def action_link_to_subscription(self):
        """Open wizard to link this service to an existing subscription."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Link to Subscription'),
            'res_model': 'resellerclub.link.subscription.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_service_model': self._name,
                'default_service_id': self.id,
                'default_partner_id': getattr(self, 'partner_id', False) and self.partner_id.id,
            },
        }

    def _schedule_renewal_activity(self, days_before=30):
        """
        Schedule an activity reminder for service renewal.

        :param days_before: Days before expiration to schedule the activity
        """
        self.ensure_one()

        if not hasattr(self, 'expiration_date') or not self.expiration_date:
            return

        # Check if activity already exists
        existing = self.env['mail.activity'].search([
            ('res_model', '=', self._name),
            ('res_id', '=', self.id),
            ('activity_type_id.category', '=', 'reminder'),
            ('date_deadline', '>=', fields.Date.today()),
        ], limit=1)

        if existing:
            return

        # Determine activity type based on model
        activity_type_map = {
            'resellerclub.domain': 'resellerclub_integration.activity_type_domain_expiry',
            'resellerclub.hosting': 'resellerclub_integration.activity_type_hosting_expiry',
            'resellerclub.ssl': 'resellerclub_integration.activity_type_ssl_expiry',
        }

        activity_type_ref = activity_type_map.get(self._name)
        if activity_type_ref:
            activity_type = self.env.ref(activity_type_ref, raise_if_not_found=False)
        else:
            activity_type = self.env.ref('mail.mail_activity_data_todo')

        deadline = self.expiration_date - timedelta(days=days_before)
        if deadline < fields.Date.today():
            deadline = fields.Date.today()

        self.activity_schedule(
            activity_type_id=activity_type.id if activity_type else False,
            date_deadline=deadline,
            summary=_('Service Renewal Required'),
            note=_('This service expires on %s. Please ensure timely renewal.') % self.expiration_date,
        )

    @api.model
    def _cron_schedule_renewal_activities(self):
        """Cron job to schedule renewal activities for expiring services."""
        reminder_days = self.env.company.resellerclub_renewal_reminder_days or 30

        # Find services expiring within reminder period
        expiring_date = fields.Date.today() + timedelta(days=reminder_days)

        services = self.search([
            ('expiration_date', '<=', expiring_date),
            ('expiration_date', '>', fields.Date.today()),
            ('renewal_reminder_sent', '=', False),
        ])

        for service in services:
            try:
                service._schedule_renewal_activity(days_before=reminder_days)
                service.renewal_reminder_sent = True
            except Exception as e:
                _logger.warning(
                    "Failed to schedule renewal activity for %s %s: %s",
                    self._name, service.id, str(e)
                )


class SaleOrder(models.Model):
    """
    Extend sale.order for ResellerClub subscription integration.
    """
    _inherit = 'sale.order'

    # ResellerClub service links
    rc_domain_ids = fields.One2many(
        'resellerclub.domain',
        'subscription_id',
        string='RC Domains'
    )
    rc_hosting_ids = fields.One2many(
        'resellerclub.hosting',
        'subscription_id',
        string='RC Hosting'
    )
    rc_ssl_ids = fields.One2many(
        'resellerclub.ssl',
        'subscription_id',
        string='RC SSL Certificates'
    )

    rc_services_count = fields.Integer(
        string='RC Services',
        compute='_compute_rc_services_count'
    )

    @api.depends('rc_domain_ids', 'rc_hosting_ids', 'rc_ssl_ids')
    def _compute_rc_services_count(self):
        for order in self:
            order.rc_services_count = (
                len(order.rc_domain_ids) +
                len(order.rc_hosting_ids) +
                len(order.rc_ssl_ids)
            )

    def _create_recurring_invoice(self):
        """
        Override to process ResellerClub renewals when subscription invoices are created.
        """
        invoices = super()._create_recurring_invoice()

        for order in self:
            if not order.is_subscription:
                continue

            # Process domain renewals
            for domain in order.rc_domain_ids.filtered(lambda d: d.status == 'active' and d.is_auto_renew):
                try:
                    domain._process_subscription_renewal()
                except Exception as e:
                    _logger.error("Failed to renew domain %s: %s", domain.domain_name, str(e))

            # Process hosting renewals
            for hosting in order.rc_hosting_ids.filtered(lambda h: h.status == 'active' and h.auto_renew):
                try:
                    hosting._process_subscription_renewal()
                except Exception as e:
                    _logger.error("Failed to renew hosting %s: %s", hosting.domain_name, str(e))

            # Process SSL renewals
            for ssl in order.rc_ssl_ids.filtered(lambda s: s.status == 'active'):
                try:
                    ssl._process_subscription_renewal()
                except Exception as e:
                    _logger.error("Failed to renew SSL %s: %s", ssl.domain_name, str(e))

        return invoices

    def action_view_rc_services(self):
        """View all ResellerClub services linked to this subscription."""
        self.ensure_one()

        domain_ids = self.rc_domain_ids.ids
        hosting_ids = self.rc_hosting_ids.ids
        ssl_ids = self.rc_ssl_ids.ids

        return {
            'type': 'ir.actions.act_window',
            'name': _('ResellerClub Services'),
            'res_model': 'resellerclub.customer',
            'view_mode': 'form',
            'domain': [('partner_id', '=', self.partner_id.id)],
            'context': {
                'default_partner_id': self.partner_id.id,
            },
        }


class SaleOrderLine(models.Model):
    """
    Extend sale.order.line for ResellerClub product configuration.
    """
    _inherit = 'sale.order.line'

    # Service configuration fields for subscription lines
    rc_service_domain = fields.Char(
        string='Domain Name',
        help="Domain name for this service"
    )
    rc_service_type = fields.Selection([
        ('domain_new', 'New Domain Registration'),
        ('domain_transfer', 'Domain Transfer'),
        ('domain_renewal', 'Domain Renewal'),
        ('hosting', 'Web Hosting'),
        ('email', 'Email Hosting'),
        ('ssl', 'SSL Certificate'),
        ('vps', 'VPS Server'),
        ('dedicated', 'Dedicated Server'),
    ], string='Service Type')

    @api.onchange('product_id')
    def _onchange_product_rc_subscription(self):
        """Set RC service type based on product."""
        if self.product_id and self.product_id.is_resellerclub_product:
            product_type_map = {
                'domain': 'domain_new',
                'domain_transfer': 'domain_transfer',
                'domain_renewal': 'domain_renewal',
                'hosting_single': 'hosting',
                'hosting_multi': 'hosting',
                'hosting_reseller': 'hosting',
                'email': 'email',
                'ssl': 'ssl',
                'vps': 'vps',
                'dedicated': 'dedicated',
            }
            self.rc_service_type = product_type_map.get(
                self.product_id.rc_product_type, False
            )


class LinkSubscriptionWizard(models.TransientModel):
    """Wizard to link a ResellerClub service to an existing subscription."""
    _name = 'resellerclub.link.subscription.wizard'
    _description = 'Link Service to Subscription'

    service_model = fields.Char(string='Service Model', required=True)
    service_id = fields.Integer(string='Service ID', required=True)
    partner_id = fields.Many2one('res.partner', string='Customer')

    subscription_id = fields.Many2one(
        'sale.order',
        string='Subscription',
        domain="[('is_subscription', '=', True), ('partner_id', '=', partner_id)]",
        required=True
    )

    def action_link(self):
        """Link the service to the selected subscription."""
        self.ensure_one()

        service = self.env[self.service_model].browse(self.service_id)
        if service.exists():
            service.subscription_id = self.subscription_id.id

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Service Linked'),
                    'message': _('Service has been linked to subscription %s') % self.subscription_id.name,
                    'type': 'success',
                    'sticky': False,
                }
            }

        raise UserError(_("Service not found."))

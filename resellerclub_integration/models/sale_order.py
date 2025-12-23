# -*- coding: utf-8 -*-

import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # ResellerClub specific fields
    has_resellerclub_products = fields.Boolean(
        string='Has RC Products',
        compute='_compute_has_resellerclub_products',
        store=True
    )

    rc_customer_id = fields.Many2one(
        'resellerclub.customer',
        string='RC Customer',
        help="ResellerClub customer for this order"
    )

    rc_order_ids = fields.One2many(
        'resellerclub.order',
        'sale_order_id',
        string='RC Orders'
    )

    rc_orders_count = fields.Integer(
        string='RC Orders',
        compute='_compute_rc_orders_count'
    )

    rc_provision_status = fields.Selection([
        ('not_applicable', 'Not Applicable'),
        ('pending', 'Pending Provisioning'),
        ('partial', 'Partially Provisioned'),
        ('completed', 'Fully Provisioned'),
        ('failed', 'Provisioning Failed'),
    ], string='RC Provision Status', default='not_applicable', tracking=True)

    @api.depends('order_line.product_id.is_resellerclub_product')
    def _compute_has_resellerclub_products(self):
        for order in self:
            order.has_resellerclub_products = any(
                line.product_id.is_resellerclub_product
                for line in order.order_line
                if line.product_id
            )

    @api.depends('rc_order_ids')
    def _compute_rc_orders_count(self):
        for order in self:
            order.rc_orders_count = len(order.rc_order_ids)

    def action_confirm(self):
        """Override to handle ResellerClub product provisioning."""
        result = super().action_confirm()

        for order in self:
            if order.has_resellerclub_products:
                order._prepare_rc_provisioning()

        return result

    def _prepare_rc_provisioning(self):
        """Prepare ResellerClub provisioning for this order."""
        self.ensure_one()

        # Ensure customer exists in ResellerClub
        if not self.rc_customer_id:
            rc_customer = self.env['resellerclub.customer'].search([
                ('partner_id', '=', self.partner_id.id),
            ], limit=1)

            if not rc_customer:
                # Create RC customer
                rc_customer = self.env['resellerclub.customer'].create({
                    'partner_id': self.partner_id.id,
                })
                try:
                    rc_customer.action_create_in_resellerclub()
                except Exception as e:
                    _logger.warning("Failed to create RC customer: %s", str(e))

            self.rc_customer_id = rc_customer

        # Mark as pending provisioning
        self.rc_provision_status = 'pending'

        # Create activities for manual provisioning
        for line in self.order_line.filtered(lambda l: l.product_id.is_resellerclub_product):
            line._schedule_provisioning_activity()

    def action_provision_rc_products(self):
        """Provision all ResellerClub products in this order."""
        self.ensure_one()

        if not self.rc_customer_id or not self.rc_customer_id.resellerclub_customer_id:
            raise UserError(_(
                "Customer must be registered in ResellerClub first. "
                "Please sync the customer and try again."
            ))

        success_count = 0
        fail_count = 0

        for line in self.order_line.filtered(lambda l: l.product_id.is_resellerclub_product):
            if line.rc_provisioned:
                continue

            try:
                line.action_provision()
                success_count += 1
            except Exception as e:
                fail_count += 1
                _logger.error("Failed to provision line %s: %s", line.id, str(e))

        # Update provision status
        if fail_count == 0 and success_count > 0:
            self.rc_provision_status = 'completed'
        elif success_count > 0:
            self.rc_provision_status = 'partial'
        elif fail_count > 0:
            self.rc_provision_status = 'failed'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Provisioning Complete'),
                'message': _('Provisioned %d products. %d failed.') % (success_count, fail_count),
                'type': 'success' if fail_count == 0 else 'warning',
                'sticky': fail_count > 0,
            }
        }

    def action_view_rc_orders(self):
        """View ResellerClub orders for this sale order."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('ResellerClub Orders'),
            'res_model': 'resellerclub.order',
            'view_mode': 'list,form',
            'domain': [('sale_order_id', '=', self.id)],
            'context': {'default_sale_order_id': self.id},
        }


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    # ResellerClub specific fields
    is_rc_product = fields.Boolean(
        string='Is RC Product',
        related='product_id.is_resellerclub_product',
        store=True
    )

    rc_product_type = fields.Selection(
        related='product_id.rc_product_type',
        store=True
    )

    # Domain fields
    rc_domain_name = fields.Char(
        string='Domain Name',
        help="Domain name for domain/hosting products"
    )
    rc_years = fields.Integer(
        string='Years',
        default=1,
        help="Registration/subscription period in years"
    )
    rc_privacy_protection = fields.Boolean(
        string='Privacy Protection',
        default=False
    )

    # Provisioning
    rc_provisioned = fields.Boolean(
        string='Provisioned',
        default=False
    )
    rc_provision_date = fields.Datetime(
        string='Provision Date'
    )
    rc_provision_error = fields.Text(
        string='Provision Error'
    )

    # Linked records
    rc_domain_id = fields.Many2one(
        'resellerclub.domain',
        string='Domain Record'
    )
    rc_hosting_id = fields.Many2one(
        'resellerclub.hosting',
        string='Hosting Record'
    )
    rc_ssl_id = fields.Many2one(
        'resellerclub.ssl',
        string='SSL Record'
    )
    rc_order_id = fields.Many2one(
        'resellerclub.order',
        string='RC Order'
    )

    @api.onchange('product_id')
    def _onchange_product_rc(self):
        """Set default RC values when product changes."""
        if self.product_id and self.product_id.is_resellerclub_product:
            self.rc_years = self.product_id.rc_min_years or 1
            if self.product_id.rc_supports_privacy:
                self.rc_privacy_protection = False

    def _schedule_provisioning_activity(self):
        """Schedule an activity for manual provisioning."""
        self.ensure_one()

        if not self.is_rc_product:
            return

        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if activity_type:
            self.order_id.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_('Provision ResellerClub Product'),
                note=_('Product: %s\nDomain: %s\nYears: %d') % (
                    self.product_id.name,
                    self.rc_domain_name or 'N/A',
                    self.rc_years
                ),
                user_id=self.order_id.user_id.id or self.env.user.id,
            )

    def action_provision(self):
        """Provision this line's product in ResellerClub."""
        self.ensure_one()

        if not self.is_rc_product:
            raise UserError(_("This is not a ResellerClub product."))

        if self.rc_provisioned:
            raise UserError(_("This product has already been provisioned."))

        rc_customer = self.order_id.rc_customer_id
        if not rc_customer or not rc_customer.resellerclub_customer_id:
            raise UserError(_("Customer must be registered in ResellerClub first."))

        try:
            if self.rc_product_type == 'domain':
                self._provision_domain()
            elif self.rc_product_type in ['hosting_single', 'hosting_multi', 'hosting_reseller']:
                self._provision_hosting()
            elif self.rc_product_type == 'ssl':
                self._provision_ssl()
            elif self.rc_product_type == 'email':
                self._provision_email()
            else:
                raise UserError(_("Unsupported product type: %s") % self.rc_product_type)

            self.write({
                'rc_provisioned': True,
                'rc_provision_date': fields.Datetime.now(),
                'rc_provision_error': False,
            })

        except Exception as e:
            self.rc_provision_error = str(e)
            raise

        return True

    def _provision_domain(self):
        """Provision a domain registration."""
        if not self.rc_domain_name:
            raise UserError(_("Domain name is required for domain registration."))

        # Create domain record
        domain = self.env['resellerclub.domain'].create({
            'domain_name': self.rc_domain_name,
            'customer_id': self.order_id.rc_customer_id.id,
            'years': self.rc_years,
            'privacy_protection': self.rc_privacy_protection,
        })

        # Register in ResellerClub
        domain.action_register_domain()

        self.rc_domain_id = domain
        self._create_rc_order('domain', domain=domain)

    def _provision_hosting(self):
        """Provision a hosting plan."""
        if not self.rc_domain_name:
            raise UserError(_("Domain name is required for hosting."))

        # Determine hosting type
        hosting_type_map = {
            'hosting_single': 'single',
            'hosting_multi': 'multi',
            'hosting_reseller': 'reseller',
        }

        hosting = self.env['resellerclub.hosting'].create({
            'domain_name': self.rc_domain_name,
            'customer_id': self.order_id.rc_customer_id.id,
            'hosting_type': hosting_type_map.get(self.rc_product_type, 'single'),
            'plan_id': self.product_id.rc_plan_id,
            'plan_name': self.product_id.name,
            'months': self.rc_years * 12,
        })

        # Order in ResellerClub
        hosting.action_order_hosting()

        self.rc_hosting_id = hosting
        self._create_rc_order('hosting', hosting=hosting)

    def _provision_ssl(self):
        """Provision an SSL certificate."""
        if not self.rc_domain_name:
            raise UserError(_("Domain name is required for SSL certificate."))

        ssl = self.env['resellerclub.ssl'].create({
            'domain_name': self.rc_domain_name,
            'customer_id': self.order_id.rc_customer_id.id,
            'plan_id': self.product_id.rc_plan_id,
            'plan_name': self.product_id.name,
            'months': self.rc_years * 12,
        })

        # Order in ResellerClub
        ssl.action_order_ssl()

        self.rc_ssl_id = ssl
        self._create_rc_order('ssl', ssl=ssl)

    def _provision_email(self):
        """Provision email hosting."""
        if not self.rc_domain_name:
            raise UserError(_("Domain name is required for email hosting."))

        hosting = self.env['resellerclub.hosting'].create({
            'domain_name': self.rc_domain_name,
            'customer_id': self.order_id.rc_customer_id.id,
            'hosting_type': 'email',
            'plan_id': self.product_id.rc_plan_id,
            'plan_name': self.product_id.name,
            'months': self.rc_years * 12,
            'email_accounts': 5,  # Default
        })

        # Order in ResellerClub
        hosting.action_order_hosting()

        self.rc_hosting_id = hosting
        self._create_rc_order('email', hosting=hosting)

    def _create_rc_order(self, order_type, domain=None, hosting=None, ssl=None):
        """Create a ResellerClub order record."""
        order_id = None
        if domain and domain.resellerclub_order_id:
            order_id = domain.resellerclub_order_id
        elif hosting and hosting.resellerclub_order_id:
            order_id = hosting.resellerclub_order_id
        elif ssl and ssl.resellerclub_order_id:
            order_id = ssl.resellerclub_order_id

        if order_id:
            rc_order = self.env['resellerclub.order'].create({
                'resellerclub_order_id': order_id,
                'order_type': order_type,
                'customer_id': self.order_id.rc_customer_id.id,
                'domain_id': domain.id if domain else False,
                'hosting_id': hosting.id if hosting else False,
                'ssl_id': ssl.id if ssl else False,
                'sale_order_id': self.order_id.id,
                'sale_order_line_id': self.id,
                'status': 'active',
            })
            self.rc_order_id = rc_order

    def action_view_rc_record(self):
        """View the linked ResellerClub record."""
        self.ensure_one()

        if self.rc_domain_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'resellerclub.domain',
                'res_id': self.rc_domain_id.id,
                'view_mode': 'form',
            }
        elif self.rc_hosting_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'resellerclub.hosting',
                'res_id': self.rc_hosting_id.id,
                'view_mode': 'form',
            }
        elif self.rc_ssl_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'resellerclub.ssl',
                'res_id': self.rc_ssl_id.id,
                'view_mode': 'form',
            }
        else:
            raise UserError(_("No linked ResellerClub record found."))

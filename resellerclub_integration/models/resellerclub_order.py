# -*- coding: utf-8 -*-

import logging
from datetime import datetime
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResellerClubOrder(models.Model):
    """
    Model to track all ResellerClub orders and their sync status.

    This provides a unified view of all ResellerClub orders across
    different product types (domains, hosting, SSL, etc.)
    """
    _name = 'resellerclub.order'
    _description = 'ResellerClub Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    _rec_name = 'display_name'

    display_name = fields.Char(
        string='Name',
        compute='_compute_display_name',
        store=True
    )

    resellerclub_order_id = fields.Char(
        string='RC Order ID',
        required=True,
        index=True
    )

    order_type = fields.Selection([
        ('domain', 'Domain Registration'),
        ('domain_transfer', 'Domain Transfer'),
        ('domain_renewal', 'Domain Renewal'),
        ('hosting', 'Hosting'),
        ('email', 'Email Hosting'),
        ('ssl', 'SSL Certificate'),
        ('sitelock', 'SiteLock'),
        ('codeguard', 'CodeGuard'),
        ('vps', 'VPS Server'),
        ('dedicated', 'Dedicated Server'),
        ('other', 'Other'),
    ], string='Order Type', required=True, tracking=True)

    product_key = fields.Char(string='Product Key')
    product_name = fields.Char(string='Product Name')

    # Linked records
    customer_id = fields.Many2one(
        'resellerclub.customer',
        string='RC Customer',
        index=True
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        related='customer_id.partner_id',
        store=True
    )
    domain_id = fields.Many2one(
        'resellerclub.domain',
        string='Domain'
    )
    hosting_id = fields.Many2one(
        'resellerclub.hosting',
        string='Hosting'
    )
    ssl_id = fields.Many2one(
        'resellerclub.ssl',
        string='SSL Certificate'
    )
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sale Order'
    )
    sale_order_line_id = fields.Many2one(
        'sale.order.line',
        string='Sale Order Line'
    )

    # Status
    status = fields.Selection([
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
        ('expired', 'Expired'),
    ], string='Status', default='pending', tracking=True, index=True)

    # Dates
    order_date = fields.Datetime(string='Order Date', default=fields.Datetime.now)
    creation_date = fields.Datetime(string='Creation Date')
    expiration_date = fields.Datetime(string='Expiration Date')

    # Financial
    amount = fields.Float(string='RC Amount')
    currency_code = fields.Char(string='Currency', default='USD')
    invoice_option = fields.Char(string='Invoice Option')
    transaction_id = fields.Char(string='Transaction ID')

    # Sync
    last_sync_date = fields.Datetime(string='Last Synchronized')
    sync_status = fields.Selection([
        ('pending', 'Pending'),
        ('synced', 'Synced'),
        ('error', 'Error'),
    ], string='Sync Status', default='pending')
    sync_error = fields.Text(string='Sync Error')

    # Response data
    raw_response = fields.Text(string='Raw Response')

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True
    )

    _sql_constraints = [
        ('order_id_company_uniq', 'unique(resellerclub_order_id, company_id)',
         'Order ID must be unique per company!'),
    ]

    @api.depends('resellerclub_order_id', 'order_type', 'product_name')
    def _compute_display_name(self):
        type_names = dict(self._fields['order_type'].selection)
        for record in self:
            type_name = type_names.get(record.order_type, 'Order')
            if record.product_name:
                record.display_name = f"{record.resellerclub_order_id} - {record.product_name}"
            else:
                record.display_name = f"{record.resellerclub_order_id} - {type_name}"

    def action_sync_from_resellerclub(self):
        """Sync order details from ResellerClub."""
        self.ensure_one()

        api = self.env['resellerclub.api']

        try:
            result = api.order_get_details(order_id=self.resellerclub_order_id)

            if isinstance(result, dict):
                # Map status
                rc_status = result.get('orderstatus', '').lower()
                status_map = {
                    'active': 'active',
                    'inactive': 'expired',
                    'deleted': 'cancelled',
                    'pending': 'processing',
                    'completed': 'completed',
                }
                status = status_map.get(rc_status, 'pending')

                # Parse dates
                creation_timestamp = result.get('creationtime')
                creation_date = None
                if creation_timestamp:
                    creation_date = datetime.fromtimestamp(int(creation_timestamp))

                exp_timestamp = result.get('endtime')
                exp_date = None
                if exp_timestamp:
                    exp_date = datetime.fromtimestamp(int(exp_timestamp))

                self.write({
                    'status': status,
                    'creation_date': creation_date,
                    'expiration_date': exp_date,
                    'product_key': result.get('productkey'),
                    'product_name': result.get('description'),
                    'last_sync_date': fields.Datetime.now(),
                    'sync_status': 'synced',
                    'sync_error': False,
                    'raw_response': str(result),
                })

        except Exception as e:
            self.write({
                'sync_status': 'error',
                'sync_error': str(e),
            })
            raise

        return True

    def action_view_linked_record(self):
        """Open the linked domain/hosting/ssl record."""
        self.ensure_one()

        if self.domain_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'resellerclub.domain',
                'res_id': self.domain_id.id,
                'view_mode': 'form',
            }
        elif self.hosting_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'resellerclub.hosting',
                'res_id': self.hosting_id.id,
                'view_mode': 'form',
            }
        elif self.ssl_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'resellerclub.ssl',
                'res_id': self.ssl_id.id,
                'view_mode': 'form',
            }
        else:
            raise UserError(_("No linked record found."))

    @api.model
    def create_from_api_response(self, response, order_type, customer=None, **kwargs):
        """
        Create an order record from an API response.

        :param response: API response data
        :param order_type: Type of order (domain, hosting, ssl, etc.)
        :param customer: ResellerClub customer record
        :param kwargs: Additional field values
        :return: Created order record
        """
        order_id = None
        if isinstance(response, dict):
            order_id = response.get('orderid') or response.get('entityid')
        elif isinstance(response, (int, str)):
            order_id = str(response)

        if not order_id:
            raise UserError(_("Cannot create order: No order ID in response"))

        vals = {
            'resellerclub_order_id': str(order_id),
            'order_type': order_type,
            'customer_id': customer.id if customer else None,
            'status': 'active',
            'order_date': fields.Datetime.now(),
            'sync_status': 'synced',
            'last_sync_date': fields.Datetime.now(),
            'raw_response': str(response),
        }
        vals.update(kwargs)

        return self.create(vals)

    @api.model
    def cron_sync_orders(self):
        """Cron job to sync pending orders."""
        orders = self.search([
            ('sync_status', '!=', 'synced'),
            ('status', 'not in', ['cancelled', 'failed']),
        ], limit=100)

        for order in orders:
            try:
                order.action_sync_from_resellerclub()
            except Exception as e:
                _logger.warning("Failed to sync order %s: %s", order.resellerclub_order_id, str(e))

        return True


class ResellerClubTransaction(models.Model):
    """
    Model to track ResellerClub financial transactions.
    """
    _name = 'resellerclub.transaction'
    _description = 'ResellerClub Transaction'
    _order = 'transaction_date desc'

    transaction_id = fields.Char(string='Transaction ID', index=True)
    transaction_date = fields.Datetime(string='Date')
    transaction_type = fields.Selection([
        ('order', 'Order'),
        ('renewal', 'Renewal'),
        ('refund', 'Refund'),
        ('credit', 'Credit'),
        ('debit', 'Debit'),
        ('transfer', 'Transfer'),
    ], string='Type')

    description = fields.Char(string='Description')
    amount = fields.Float(string='Amount')
    balance_after = fields.Float(string='Balance After')
    currency_code = fields.Char(string='Currency', default='USD')

    order_id = fields.Many2one(
        'resellerclub.order',
        string='Order'
    )
    customer_id = fields.Many2one(
        'resellerclub.customer',
        string='Customer'
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True
    )

    @api.model
    def sync_transactions(self, from_date=None, to_date=None):
        """Sync transactions from ResellerClub."""
        api = self.env['resellerclub.api']

        try:
            result = api.reseller_get_transactions(
                from_date=from_date,
                to_date=to_date
            )

            if isinstance(result, dict) and 'transactions' in result:
                for tx_data in result['transactions']:
                    tx_id = tx_data.get('transactionid')

                    existing = self.search([
                        ('transaction_id', '=', tx_id),
                        ('company_id', '=', self.env.company.id),
                    ], limit=1)

                    if not existing:
                        self.create({
                            'transaction_id': tx_id,
                            'transaction_date': datetime.fromtimestamp(
                                int(tx_data.get('transactiondate', 0))
                            ),
                            'description': tx_data.get('description'),
                            'amount': float(tx_data.get('amount', 0)),
                            'balance_after': float(tx_data.get('balance', 0)),
                        })

        except Exception as e:
            _logger.warning("Failed to sync transactions: %s", str(e))
            raise

        return True

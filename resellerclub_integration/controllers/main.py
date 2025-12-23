# -*- coding: utf-8 -*-

import json
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class ResellerClubController(http.Controller):
    """Main controller for ResellerClub integration."""

    @http.route('/resellerclub/domain/check', type='json', auth='user', methods=['POST'])
    def check_domain_availability(self, domain_name, tlds=None):
        """
        Check domain availability via AJAX.

        :param domain_name: Domain name without TLD
        :param tlds: List of TLDs to check (optional)
        :return: Availability results
        """
        if not tlds:
            tlds = ['com', 'net', 'org', 'info', 'biz', 'co']

        try:
            api = request.env['resellerclub.api']
            result = api.domain_check_availability(domain_name, tlds)
            return {'success': True, 'data': result}
        except Exception as e:
            _logger.error("Domain availability check failed: %s", str(e))
            return {'success': False, 'error': str(e)}

    @http.route('/resellerclub/domain/suggest', type='json', auth='user', methods=['POST'])
    def suggest_domain_names(self, keyword, tld=None):
        """
        Get domain name suggestions.

        :param keyword: Keyword for suggestions
        :param tld: Optional TLD filter
        :return: List of suggested domains
        """
        try:
            api = request.env['resellerclub.api']
            result = api.domain_suggest_names(keyword, tld)
            return {'success': True, 'data': result}
        except Exception as e:
            _logger.error("Domain suggestion failed: %s", str(e))
            return {'success': False, 'error': str(e)}

    @http.route('/resellerclub/webhook', type='json', auth='public', methods=['POST'], csrf=False)
    def webhook_handler(self, **kwargs):
        """
        Handle webhooks from ResellerClub.

        This endpoint receives notifications about order status changes,
        domain transfers, and other events.
        """
        _logger.info("ResellerClub webhook received: %s", json.dumps(kwargs))

        # Validate webhook (you may want to add signature verification)
        event_type = kwargs.get('event_type')
        order_id = kwargs.get('order_id')
        status = kwargs.get('status')

        if not event_type or not order_id:
            return {'status': 'error', 'message': 'Missing required fields'}

        try:
            # Find and update the order
            order = request.env['resellerclub.order'].sudo().search([
                ('resellerclub_order_id', '=', str(order_id)),
            ], limit=1)

            if order:
                if status:
                    order.write({'status': status.lower()})

                # Sync the order details
                order.action_sync_from_resellerclub()

                _logger.info("Webhook processed: Order %s updated", order_id)
                return {'status': 'success', 'message': 'Order updated'}
            else:
                _logger.warning("Webhook: Order %s not found", order_id)
                return {'status': 'warning', 'message': 'Order not found'}

        except Exception as e:
            _logger.error("Webhook processing failed: %s", str(e))
            return {'status': 'error', 'message': str(e)}

    @http.route('/resellerclub/balance', type='json', auth='user', methods=['POST'])
    def get_balance(self):
        """Get ResellerClub account balance."""
        try:
            api = request.env['resellerclub.api']
            result = api.reseller_get_balance()
            return {'success': True, 'data': result}
        except Exception as e:
            _logger.error("Balance check failed: %s", str(e))
            return {'success': False, 'error': str(e)}

# -*- coding: utf-8 -*-

import logging
import requests
import json
import time
from datetime import datetime
from functools import wraps

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


def api_error_handler(func):
    """Decorator to handle API errors consistently."""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except requests.exceptions.Timeout:
            raise UserError(_("ResellerClub API timeout. Please try again later."))
        except requests.exceptions.ConnectionError:
            raise UserError(_("Cannot connect to ResellerClub API. Please check your internet connection."))
        except requests.exceptions.RequestException as e:
            raise UserError(_("ResellerClub API error: %s") % str(e))
        except json.JSONDecodeError:
            raise UserError(_("Invalid response from ResellerClub API."))
    return wrapper


class ResellerClubAPI(models.AbstractModel):
    """
    Abstract model providing ResellerClub API client functionality.

    This model handles all communication with the ResellerClub HTTP API including:
    - Authentication
    - Request building and execution
    - Response parsing and error handling
    - Rate limiting
    - Logging
    """
    _name = 'resellerclub.api'
    _description = 'ResellerClub API Client'

    # API Endpoints
    LIVE_API_URL = 'https://httpapi.com/api'
    TEST_API_URL = 'https://test.httpapi.com/api'

    # Response formats
    FORMAT_JSON = 'json'
    FORMAT_XML = 'xml'

    # Rate limiting
    _last_request_time = 0
    _min_request_interval = 0.2  # 200ms between requests

    def _get_api_credentials(self):
        """Get API credentials from company settings."""
        company = self.env.company
        if not company.resellerclub_auth_userid or not company.resellerclub_api_key:
            raise UserError(_(
                "ResellerClub API credentials are not configured. "
                "Please go to Settings > ResellerClub to configure them."
            ))
        return {
            'auth_userid': company.resellerclub_auth_userid,
            'api_key': company.resellerclub_api_key,
            'test_mode': company.resellerclub_test_mode,
        }

    def _get_base_url(self):
        """Get the appropriate API base URL based on test mode setting."""
        credentials = self._get_api_credentials()
        if credentials.get('test_mode'):
            return self.TEST_API_URL
        return self.LIVE_API_URL

    def _build_auth_params(self):
        """Build authentication parameters for API requests."""
        credentials = self._get_api_credentials()
        return {
            'auth-userid': credentials['auth_userid'],
            'api-key': credentials['api_key'],
        }

    def _rate_limit(self):
        """Implement rate limiting to avoid API throttling."""
        current_time = time.time()
        time_since_last = current_time - self._last_request_time
        if time_since_last < self._min_request_interval:
            time.sleep(self._min_request_interval - time_since_last)
        ResellerClubAPI._last_request_time = time.time()

    def _log_api_call(self, method, endpoint, params, response, duration):
        """Log API call for debugging and audit purposes."""
        # Mask sensitive data
        safe_params = params.copy()
        if 'api-key' in safe_params:
            safe_params['api-key'] = '***MASKED***'
        if 'passwd' in safe_params:
            safe_params['passwd'] = '***MASKED***'

        self.env['resellerclub.api.log'].sudo().create({
            'method': method,
            'endpoint': endpoint,
            'request_params': json.dumps(safe_params, indent=2),
            'response_data': json.dumps(response, indent=2) if isinstance(response, dict) else str(response),
            'duration': duration,
            'user_id': self.env.user.id,
            'company_id': self.env.company.id,
        })

    @api_error_handler
    def _api_request(self, method, endpoint, params=None, data=None, format='json'):
        """
        Execute an API request to ResellerClub.

        :param method: HTTP method (GET, POST, etc.)
        :param endpoint: API endpoint path (e.g., '/domains/available')
        :param params: Query parameters
        :param data: POST data
        :param format: Response format (json or xml)
        :return: Parsed response data
        """
        self._rate_limit()

        url = f"{self._get_base_url()}{endpoint}.{format}"

        # Merge authentication params
        request_params = self._build_auth_params()
        if params:
            request_params.update(params)

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
        }

        start_time = time.time()

        _logger.info("ResellerClub API Request: %s %s", method, endpoint)

        if method.upper() == 'GET':
            response = requests.get(url, params=request_params, headers=headers, timeout=30)
        elif method.upper() == 'POST':
            if data:
                request_params.update(data)
            response = requests.post(url, data=request_params, headers=headers, timeout=30)
        else:
            raise UserError(_("Unsupported HTTP method: %s") % method)

        duration = time.time() - start_time

        # Parse response
        if format == 'json':
            result = response.json()
        else:
            result = response.text

        # Log the API call
        try:
            self._log_api_call(method, endpoint, request_params, result, duration)
        except Exception as e:
            _logger.warning("Failed to log API call: %s", str(e))

        # Check for API errors
        if isinstance(result, dict):
            if result.get('status') == 'ERROR':
                error_msg = result.get('message', 'Unknown error')
                raise UserError(_("ResellerClub API Error: %s") % error_msg)
            if 'error' in result:
                raise UserError(_("ResellerClub API Error: %s") % result['error'])

        return result

    # ===================
    # Domain API Methods
    # ===================

    def domain_check_availability(self, domain_names, tlds):
        """
        Check availability of domain names.

        :param domain_names: List of domain names (without TLD)
        :param tlds: List of TLDs to check
        :return: Dictionary with availability status
        """
        params = {
            'domain-name': domain_names if isinstance(domain_names, list) else [domain_names],
            'tlds': tlds if isinstance(tlds, list) else [tlds],
        }
        return self._api_request('GET', '/domains/available', params)

    def domain_suggest_names(self, keyword, tld=None, exact_match=False):
        """
        Get domain name suggestions based on keyword.

        :param keyword: Keyword to base suggestions on
        :param tld: Optional TLD filter
        :param exact_match: Whether to only return exact matches
        :return: List of suggested domains
        """
        params = {
            'keyword': keyword,
            'exact-match': str(exact_match).lower(),
        }
        if tld:
            params['tld-only'] = tld
        return self._api_request('GET', '/domains/v5/suggest-names', params)

    def domain_register(self, domain_name, years, customer_id, contact_ids, nameservers,
                       privacy_protection=False, purchase_privacy=False):
        """
        Register a new domain.

        :param domain_name: Full domain name with TLD
        :param years: Number of years to register
        :param customer_id: ResellerClub customer ID
        :param contact_ids: Dict with registrant, admin, tech, billing contact IDs
        :param nameservers: List of nameserver hostnames
        :param privacy_protection: Enable WHOIS privacy
        :param purchase_privacy: Purchase privacy protection
        :return: Order response
        """
        data = {
            'domain-name': domain_name,
            'years': years,
            'customer-id': customer_id,
            'reg-contact-id': contact_ids.get('registrant'),
            'admin-contact-id': contact_ids.get('admin'),
            'tech-contact-id': contact_ids.get('tech'),
            'billing-contact-id': contact_ids.get('billing'),
            'invoice-option': 'NoInvoice',
            'protect-privacy': str(privacy_protection).lower(),
            'purchase-privacy': str(purchase_privacy).lower(),
        }

        # Add nameservers
        for i, ns in enumerate(nameservers[:5]):  # Max 5 nameservers
            data[f'ns{i+1}'] = ns

        return self._api_request('POST', '/domains/register', data=data)

    def domain_renew(self, order_id, years, exp_date):
        """
        Renew a domain registration.

        :param order_id: ResellerClub order ID
        :param years: Number of years to renew
        :param exp_date: Current expiration date (Unix timestamp)
        :return: Renewal response
        """
        data = {
            'order-id': order_id,
            'years': years,
            'exp-date': exp_date,
            'invoice-option': 'NoInvoice',
        }
        return self._api_request('POST', '/domains/renew', data=data)

    def domain_transfer(self, domain_name, auth_code, customer_id, contact_ids, nameservers=None):
        """
        Transfer a domain from another registrar.

        :param domain_name: Full domain name with TLD
        :param auth_code: EPP/Transfer authorization code
        :param customer_id: ResellerClub customer ID
        :param contact_ids: Dict with registrant, admin, tech, billing contact IDs
        :param nameservers: Optional list of nameserver hostnames
        :return: Transfer order response
        """
        data = {
            'domain-name': domain_name,
            'auth-code': auth_code,
            'customer-id': customer_id,
            'reg-contact-id': contact_ids.get('registrant'),
            'admin-contact-id': contact_ids.get('admin'),
            'tech-contact-id': contact_ids.get('tech'),
            'billing-contact-id': contact_ids.get('billing'),
            'invoice-option': 'NoInvoice',
        }

        if nameservers:
            for i, ns in enumerate(nameservers[:5]):
                data[f'ns{i+1}'] = ns

        return self._api_request('POST', '/domains/transfer', data=data)

    def domain_get_details(self, order_id=None, domain_name=None):
        """
        Get details of a domain.

        :param order_id: ResellerClub order ID
        :param domain_name: Domain name (alternative to order_id)
        :return: Domain details
        """
        params = {}
        if order_id:
            params['order-id'] = order_id
        elif domain_name:
            params['domain-name'] = domain_name
        else:
            raise UserError(_("Either order_id or domain_name must be provided"))

        return self._api_request('GET', '/domains/details', params)

    def domain_get_order_id(self, domain_name):
        """Get order ID for a domain name."""
        params = {'domain-name': domain_name}
        return self._api_request('GET', '/domains/orderid', params)

    def domain_modify_nameservers(self, order_id, nameservers):
        """Modify nameservers for a domain."""
        data = {'order-id': order_id}
        for i, ns in enumerate(nameservers[:5]):
            data[f'ns{i+1}'] = ns
        return self._api_request('POST', '/domains/modify-ns', data=data)

    def domain_get_lock_status(self, order_id):
        """Get the lock status of a domain."""
        params = {'order-id': order_id}
        return self._api_request('GET', '/domains/locks', params)

    def domain_enable_theft_protection(self, order_id):
        """Enable theft protection (registry lock) for a domain."""
        data = {'order-id': order_id}
        return self._api_request('POST', '/domains/enable-theft-protection', data=data)

    def domain_disable_theft_protection(self, order_id):
        """Disable theft protection for a domain."""
        data = {'order-id': order_id}
        return self._api_request('POST', '/domains/disable-theft-protection', data=data)

    def domain_get_auth_code(self, order_id):
        """Get the EPP/authorization code for a domain."""
        params = {'order-id': order_id}
        return self._api_request('GET', '/domains/auth-code', params)

    # ===================
    # DNS API Methods
    # ===================

    def dns_activate(self, order_id):
        """Activate DNS service for a domain."""
        data = {'order-id': order_id}
        return self._api_request('POST', '/dns/activate', data=data)

    def dns_add_record(self, domain_name, record_type, value, host='@', ttl=14400, priority=None):
        """
        Add a DNS record.

        :param domain_name: Domain name
        :param record_type: Record type (A, AAAA, CNAME, MX, TXT, etc.)
        :param value: Record value
        :param host: Hostname (default @)
        :param ttl: Time to live in seconds
        :param priority: Priority for MX records
        :return: Response
        """
        data = {
            'domain-name': domain_name,
            'type': record_type,
            'value': value,
            'host': host,
            'ttl': ttl,
        }
        if priority is not None:
            data['priority'] = priority
        return self._api_request('POST', '/dns/manage/add-record', data=data)

    def dns_modify_record(self, domain_name, record_type, old_value, new_value, host='@', ttl=14400, priority=None):
        """Modify an existing DNS record."""
        data = {
            'domain-name': domain_name,
            'type': record_type,
            'old-value': old_value,
            'new-value': new_value,
            'host': host,
            'ttl': ttl,
        }
        if priority is not None:
            data['priority'] = priority
        return self._api_request('POST', '/dns/manage/modify-record', data=data)

    def dns_delete_record(self, domain_name, record_type, value, host='@'):
        """Delete a DNS record."""
        data = {
            'domain-name': domain_name,
            'type': record_type,
            'value': value,
            'host': host,
        }
        return self._api_request('POST', '/dns/manage/delete-record', data=data)

    def dns_get_records(self, domain_name, record_type=None, host=None):
        """Get DNS records for a domain."""
        params = {'domain-name': domain_name}
        if record_type:
            params['type'] = record_type
        if host:
            params['host'] = host
        return self._api_request('GET', '/dns/manage/search-records', params)

    # ===================
    # Customer API Methods
    # ===================

    def customer_create(self, email, password, name, company, address, city, state,
                       country_code, zipcode, phone_cc, phone, lang_pref='en'):
        """
        Create a new customer in ResellerClub.

        :return: Customer ID
        """
        data = {
            'username': email,
            'passwd': password,
            'name': name,
            'company': company or 'N/A',
            'address-line-1': address,
            'city': city,
            'state': state,
            'country': country_code,
            'zipcode': zipcode,
            'phone-cc': phone_cc,
            'phone': phone,
            'lang-pref': lang_pref,
        }
        return self._api_request('POST', '/customers/signup', data=data)

    def customer_get_details(self, customer_id=None, email=None):
        """Get customer details by ID or email."""
        params = {}
        if customer_id:
            params['customer-id'] = customer_id
        elif email:
            params['username'] = email
        else:
            raise UserError(_("Either customer_id or email must be provided"))

        endpoint = '/customers/details' if customer_id else '/customers/details-by-id'
        return self._api_request('GET', endpoint, params)

    def customer_modify(self, customer_id, **kwargs):
        """Modify customer details."""
        data = {'customer-id': customer_id}
        data.update(kwargs)
        return self._api_request('POST', '/customers/modify', data=data)

    def customer_search(self, **filters):
        """Search for customers with filters."""
        return self._api_request('GET', '/customers/search', filters)

    def customer_generate_password(self, customer_id):
        """Generate a temporary password for a customer."""
        data = {'customer-id': customer_id}
        return self._api_request('POST', '/customers/temp-password', data=data)

    # ===================
    # Contact API Methods
    # ===================

    def contact_create(self, customer_id, email, name, company, address, city, state,
                      country_code, zipcode, phone_cc, phone, contact_type='Contact'):
        """Create a new contact."""
        data = {
            'customer-id': customer_id,
            'email': email,
            'name': name,
            'company': company or 'N/A',
            'address-line-1': address,
            'city': city,
            'state': state,
            'country': country_code,
            'zipcode': zipcode,
            'phone-cc': phone_cc,
            'phone': phone,
            'type': contact_type,
        }
        return self._api_request('POST', '/contacts/add', data=data)

    def contact_get_details(self, contact_id):
        """Get contact details."""
        params = {'contact-id': contact_id}
        return self._api_request('GET', '/contacts/details', params)

    def contact_modify(self, contact_id, **kwargs):
        """Modify contact details."""
        data = {'contact-id': contact_id}
        data.update(kwargs)
        return self._api_request('POST', '/contacts/modify', data=data)

    def contact_delete(self, contact_id):
        """Delete a contact."""
        data = {'contact-id': contact_id}
        return self._api_request('POST', '/contacts/delete', data=data)

    def contact_search(self, customer_id, **filters):
        """Search for contacts."""
        params = {'customer-id': customer_id}
        params.update(filters)
        return self._api_request('GET', '/contacts/search', params)

    # ===================
    # Hosting API Methods
    # ===================

    def hosting_order(self, domain_name, customer_id, plan_id, months, autorenew=True):
        """
        Order a hosting plan.

        :param domain_name: Domain name for hosting
        :param customer_id: ResellerClub customer ID
        :param plan_id: Hosting plan ID
        :param months: Number of months
        :param autorenew: Enable auto-renewal
        :return: Order response
        """
        data = {
            'domain-name': domain_name,
            'customer-id': customer_id,
            'plan-id': plan_id,
            'months': months,
            'autorenew': str(autorenew).lower(),
            'invoice-option': 'NoInvoice',
        }
        return self._api_request('POST', '/hosting/order', data=data)

    def hosting_renew(self, order_id, months, exp_date):
        """Renew a hosting plan."""
        data = {
            'order-id': order_id,
            'months': months,
            'exp-date': exp_date,
            'invoice-option': 'NoInvoice',
        }
        return self._api_request('POST', '/hosting/renew', data=data)

    def hosting_get_details(self, order_id):
        """Get hosting order details."""
        params = {'order-id': order_id}
        return self._api_request('GET', '/hosting/details', params)

    def hosting_get_plans(self):
        """Get available hosting plans."""
        return self._api_request('GET', '/hosting/plans')

    def hosting_upgrade(self, order_id, new_plan_id):
        """Upgrade hosting plan."""
        data = {
            'order-id': order_id,
            'new-plan-id': new_plan_id,
        }
        return self._api_request('POST', '/hosting/upgrade', data=data)

    # ===================
    # Email Hosting API Methods
    # ===================

    def email_order(self, domain_name, customer_id, plan_id, months, num_accounts):
        """Order email hosting."""
        data = {
            'domain-name': domain_name,
            'customer-id': customer_id,
            'plan-id': plan_id,
            'months': months,
            'number-of-accounts': num_accounts,
            'invoice-option': 'NoInvoice',
        }
        return self._api_request('POST', '/mail/add', data=data)

    def email_renew(self, order_id, months, exp_date, num_accounts):
        """Renew email hosting."""
        data = {
            'order-id': order_id,
            'months': months,
            'exp-date': exp_date,
            'number-of-accounts': num_accounts,
            'invoice-option': 'NoInvoice',
        }
        return self._api_request('POST', '/mail/renew', data=data)

    def email_get_details(self, order_id):
        """Get email hosting details."""
        params = {'order-id': order_id}
        return self._api_request('GET', '/mail/details', params)

    # ===================
    # SSL Certificate API Methods
    # ===================

    def ssl_get_plans(self):
        """Get available SSL certificate plans."""
        return self._api_request('GET', '/ssl-certs/plans')

    def ssl_order(self, domain_name, customer_id, plan_id, months, csr=None):
        """
        Order an SSL certificate.

        :param domain_name: Domain name for the certificate
        :param customer_id: ResellerClub customer ID
        :param plan_id: SSL plan ID
        :param months: Certificate validity in months
        :param csr: Certificate Signing Request (optional)
        :return: Order response
        """
        data = {
            'domain-name': domain_name,
            'customer-id': customer_id,
            'plan-id': plan_id,
            'months': months,
            'invoice-option': 'NoInvoice',
        }
        if csr:
            data['csr'] = csr
        return self._api_request('POST', '/ssl-certs/add', data=data)

    def ssl_renew(self, order_id, months, exp_date):
        """Renew an SSL certificate."""
        data = {
            'order-id': order_id,
            'months': months,
            'exp-date': exp_date,
            'invoice-option': 'NoInvoice',
        }
        return self._api_request('POST', '/ssl-certs/renew', data=data)

    def ssl_get_details(self, order_id):
        """Get SSL certificate details."""
        params = {'order-id': order_id}
        return self._api_request('GET', '/ssl-certs/details', params)

    def ssl_generate_csr(self, order_id, **details):
        """Generate CSR for an SSL certificate."""
        data = {'order-id': order_id}
        data.update(details)
        return self._api_request('POST', '/ssl-certs/generate-csr', data=data)

    def ssl_enroll(self, order_id, csr, **details):
        """Enroll/activate an SSL certificate."""
        data = {
            'order-id': order_id,
            'csr': csr,
        }
        data.update(details)
        return self._api_request('POST', '/ssl-certs/enroll', data=data)

    # ===================
    # Order/Product API Methods
    # ===================

    def order_get_details(self, order_id):
        """Get generic order details."""
        params = {'order-id': order_id}
        return self._api_request('GET', '/orders/details', params)

    def order_search(self, customer_id=None, product_key=None, status=None, **filters):
        """Search for orders."""
        params = {}
        if customer_id:
            params['customer-id'] = customer_id
        if product_key:
            params['product-key'] = product_key
        if status:
            params['status'] = status
        params.update(filters)
        return self._api_request('GET', '/orders/search', params)

    def order_cancel(self, order_id):
        """Cancel an order (if cancellable)."""
        data = {'order-id': order_id}
        return self._api_request('POST', '/orders/cancel', data=data)

    def order_suspend(self, order_id, reason):
        """Suspend an order."""
        data = {
            'order-id': order_id,
            'reason': reason,
        }
        return self._api_request('POST', '/orders/suspend', data=data)

    def order_unsuspend(self, order_id):
        """Unsuspend an order."""
        data = {'order-id': order_id}
        return self._api_request('POST', '/orders/unsuspend', data=data)

    # ===================
    # Reseller API Methods
    # ===================

    def reseller_get_balance(self):
        """Get reseller account balance."""
        return self._api_request('GET', '/resellers/balance')

    def reseller_get_pricing(self, product_key=None):
        """Get reseller pricing for products."""
        params = {}
        if product_key:
            params['product-key'] = product_key
        return self._api_request('GET', '/resellers/promo-prices', params)

    def reseller_get_transactions(self, from_date=None, to_date=None, **filters):
        """Get reseller transaction history."""
        params = {}
        if from_date:
            params['transaction-date-start'] = from_date
        if to_date:
            params['transaction-date-end'] = to_date
        params.update(filters)
        return self._api_request('GET', '/resellers/transactions', params)

    # ===================
    # Product Pricing API Methods
    # ===================

    def get_domain_pricing(self, tlds=None):
        """Get domain pricing for all or specific TLDs."""
        params = {}
        if tlds:
            params['tlds'] = tlds if isinstance(tlds, list) else [tlds]
        return self._api_request('GET', '/products/domain/pricing', params)

    def get_product_details(self, product_key):
        """Get product details and pricing."""
        params = {'product-key': product_key}
        return self._api_request('GET', '/products/details', params)

    # ===================
    # VPS Server API Methods
    # ===================

    def vps_get_plans(self):
        """Get available VPS plans."""
        return self._api_request('GET', '/vps/linux/plans')

    def vps_order(self, domain_name, customer_id, plan_id, months, hostname=None,
                  root_password=None, os_template=None):
        """
        Order a VPS server.

        :param domain_name: Domain name for the VPS
        :param customer_id: ResellerClub customer ID
        :param plan_id: VPS plan ID
        :param months: Number of months
        :param hostname: Server hostname
        :param root_password: Root password for the VPS
        :param os_template: Operating system template
        :return: Order response
        """
        data = {
            'domain-name': domain_name,
            'customer-id': customer_id,
            'plan-id': plan_id,
            'months': months,
            'invoice-option': 'NoInvoice',
        }
        if hostname:
            data['hostname'] = hostname
        if root_password:
            data['root-passwd'] = root_password
        if os_template:
            data['os-template'] = os_template
        return self._api_request('POST', '/vps/linux/add', data=data)

    def vps_renew(self, order_id, months, exp_date):
        """Renew a VPS server."""
        data = {
            'order-id': order_id,
            'months': months,
            'exp-date': exp_date,
            'invoice-option': 'NoInvoice',
        }
        return self._api_request('POST', '/vps/linux/renew', data=data)

    def vps_get_details(self, order_id):
        """Get VPS server details."""
        params = {'order-id': order_id}
        return self._api_request('GET', '/vps/linux/details', params)

    def vps_reboot(self, order_id):
        """Reboot a VPS server."""
        data = {'order-id': order_id}
        return self._api_request('POST', '/vps/linux/reboot', data=data)

    def vps_start(self, order_id):
        """Start a VPS server."""
        data = {'order-id': order_id}
        return self._api_request('POST', '/vps/linux/start', data=data)

    def vps_stop(self, order_id):
        """Stop a VPS server."""
        data = {'order-id': order_id}
        return self._api_request('POST', '/vps/linux/shutdown', data=data)

    def vps_get_os_templates(self):
        """Get available OS templates for VPS."""
        return self._api_request('GET', '/vps/linux/os-templates')

    # ===================
    # Dedicated Server API Methods
    # ===================

    def dedicated_get_plans(self):
        """Get available dedicated server plans."""
        return self._api_request('GET', '/dedserver/plans')

    def dedicated_order(self, customer_id, plan_id, months, os_template=None):
        """
        Order a dedicated server.

        :param customer_id: ResellerClub customer ID
        :param plan_id: Dedicated server plan ID
        :param months: Number of months
        :param os_template: Operating system template
        :return: Order response
        """
        data = {
            'customer-id': customer_id,
            'plan-id': plan_id,
            'months': months,
            'invoice-option': 'NoInvoice',
        }
        if os_template:
            data['os-template'] = os_template
        return self._api_request('POST', '/dedserver/add', data=data)

    def dedicated_renew(self, order_id, months, exp_date):
        """Renew a dedicated server."""
        data = {
            'order-id': order_id,
            'months': months,
            'exp-date': exp_date,
            'invoice-option': 'NoInvoice',
        }
        return self._api_request('POST', '/dedserver/renew', data=data)

    def dedicated_get_details(self, order_id):
        """Get dedicated server details."""
        params = {'order-id': order_id}
        return self._api_request('GET', '/dedserver/details', params)

    def dedicated_reboot(self, order_id):
        """Reboot a dedicated server."""
        data = {'order-id': order_id}
        return self._api_request('POST', '/dedserver/reboot', data=data)

    # ===================
    # Google Workspace API Methods
    # ===================

    def gsuite_get_plans(self):
        """Get available Google Workspace plans."""
        return self._api_request('GET', '/gapps/plans')

    def gsuite_order(self, domain_name, customer_id, plan_id, months, num_accounts):
        """
        Order Google Workspace.

        :param domain_name: Domain name for Google Workspace
        :param customer_id: ResellerClub customer ID
        :param plan_id: Google Workspace plan ID
        :param months: Number of months (usually 12)
        :param num_accounts: Number of user accounts
        :return: Order response
        """
        data = {
            'domain-name': domain_name,
            'customer-id': customer_id,
            'plan-id': plan_id,
            'months': months,
            'number-of-accounts': num_accounts,
            'invoice-option': 'NoInvoice',
        }
        return self._api_request('POST', '/gapps/add', data=data)

    def gsuite_renew(self, order_id, months, exp_date, num_accounts):
        """Renew Google Workspace subscription."""
        data = {
            'order-id': order_id,
            'months': months,
            'exp-date': exp_date,
            'number-of-accounts': num_accounts,
            'invoice-option': 'NoInvoice',
        }
        return self._api_request('POST', '/gapps/renew', data=data)

    def gsuite_get_details(self, order_id):
        """Get Google Workspace order details."""
        params = {'order-id': order_id}
        return self._api_request('GET', '/gapps/details', params)

    def gsuite_add_accounts(self, order_id, num_accounts):
        """Add user accounts to Google Workspace."""
        data = {
            'order-id': order_id,
            'number-of-accounts': num_accounts,
            'invoice-option': 'NoInvoice',
        }
        return self._api_request('POST', '/gapps/add-accounts', data=data)

    # ===================
    # SiteLock API Methods
    # ===================

    def sitelock_get_plans(self):
        """Get available SiteLock plans."""
        return self._api_request('GET', '/sitelock/plans')

    def sitelock_order(self, domain_name, customer_id, plan_id, months):
        """
        Order SiteLock security service.

        :param domain_name: Domain name to protect
        :param customer_id: ResellerClub customer ID
        :param plan_id: SiteLock plan ID
        :param months: Number of months
        :return: Order response
        """
        data = {
            'domain-name': domain_name,
            'customer-id': customer_id,
            'plan-id': plan_id,
            'months': months,
            'invoice-option': 'NoInvoice',
        }
        return self._api_request('POST', '/sitelock/add', data=data)

    def sitelock_renew(self, order_id, months, exp_date):
        """Renew SiteLock subscription."""
        data = {
            'order-id': order_id,
            'months': months,
            'exp-date': exp_date,
            'invoice-option': 'NoInvoice',
        }
        return self._api_request('POST', '/sitelock/renew', data=data)

    def sitelock_get_details(self, order_id):
        """Get SiteLock order details."""
        params = {'order-id': order_id}
        return self._api_request('GET', '/sitelock/details', params)

    # ===================
    # CodeGuard API Methods
    # ===================

    def codeguard_get_plans(self):
        """Get available CodeGuard backup plans."""
        return self._api_request('GET', '/codeguard/plans')

    def codeguard_order(self, domain_name, customer_id, plan_id, months):
        """
        Order CodeGuard backup service.

        :param domain_name: Domain/site to backup
        :param customer_id: ResellerClub customer ID
        :param plan_id: CodeGuard plan ID
        :param months: Number of months
        :return: Order response
        """
        data = {
            'domain-name': domain_name,
            'customer-id': customer_id,
            'plan-id': plan_id,
            'months': months,
            'invoice-option': 'NoInvoice',
        }
        return self._api_request('POST', '/codeguard/add', data=data)

    def codeguard_renew(self, order_id, months, exp_date):
        """Renew CodeGuard subscription."""
        data = {
            'order-id': order_id,
            'months': months,
            'exp-date': exp_date,
            'invoice-option': 'NoInvoice',
        }
        return self._api_request('POST', '/codeguard/renew', data=data)

    def codeguard_get_details(self, order_id):
        """Get CodeGuard order details."""
        params = {'order-id': order_id}
        return self._api_request('GET', '/codeguard/details', params)

    # ===================
    # Domain Forwarding API Methods
    # ===================

    def domain_forwarding_setup(self, order_id, destination_url, url_masking=False,
                                 header_tags=None, noframes_content=None):
        """
        Setup domain forwarding (URL redirect).

        :param order_id: Domain order ID
        :param destination_url: URL to forward to
        :param url_masking: Whether to mask the destination URL
        :param header_tags: Optional header tags for masked forwarding
        :param noframes_content: Content for browsers without frames support
        :return: Response
        """
        data = {
            'order-id': order_id,
            'destination-url': destination_url,
            'url-masking': str(url_masking).lower(),
        }
        if header_tags:
            data['header-tags'] = header_tags
        if noframes_content:
            data['noframes-content'] = noframes_content
        return self._api_request('POST', '/domains/forward/add', data=data)

    def domain_forwarding_delete(self, order_id):
        """Delete domain forwarding."""
        data = {'order-id': order_id}
        return self._api_request('POST', '/domains/forward/delete', data=data)

    def domain_forwarding_get(self, order_id):
        """Get domain forwarding details."""
        params = {'order-id': order_id}
        return self._api_request('GET', '/domains/forward/details', params)

    # ===================
    # WHOIS/Contact Modification API
    # ===================

    def domain_modify_contacts(self, order_id, reg_contact_id=None, admin_contact_id=None,
                                tech_contact_id=None, billing_contact_id=None):
        """
        Modify domain contacts.

        :param order_id: Domain order ID
        :param reg_contact_id: New registrant contact ID
        :param admin_contact_id: New admin contact ID
        :param tech_contact_id: New tech contact ID
        :param billing_contact_id: New billing contact ID
        :return: Response
        """
        data = {'order-id': order_id}
        if reg_contact_id:
            data['reg-contact-id'] = reg_contact_id
        if admin_contact_id:
            data['admin-contact-id'] = admin_contact_id
        if tech_contact_id:
            data['tech-contact-id'] = tech_contact_id
        if billing_contact_id:
            data['billing-contact-id'] = billing_contact_id
        return self._api_request('POST', '/domains/modify-contact', data=data)

    def domain_resend_verification(self, order_id):
        """Resend registrant verification email."""
        data = {'order-id': order_id}
        return self._api_request('POST', '/domains/resend-verification', data=data)

    # ===================
    # Child Nameserver API Methods
    # ===================

    def childns_add(self, order_id, hostname, ip_addresses):
        """
        Add a child nameserver (glue record).

        :param order_id: Domain order ID
        :param hostname: Nameserver hostname (e.g., ns1.example.com)
        :param ip_addresses: List of IP addresses
        :return: Response
        """
        data = {
            'order-id': order_id,
            'cns': hostname,
        }
        for i, ip in enumerate(ip_addresses):
            data[f'ip{i+1}'] = ip
        return self._api_request('POST', '/domains/add-cns', data=data)

    def childns_modify(self, order_id, hostname, old_ip, new_ip):
        """Modify a child nameserver IP."""
        data = {
            'order-id': order_id,
            'cns': hostname,
            'old-ip': old_ip,
            'new-ip': new_ip,
        }
        return self._api_request('POST', '/domains/modify-cns-ip', data=data)

    def childns_delete(self, order_id, hostname, ip):
        """Delete a child nameserver IP."""
        data = {
            'order-id': order_id,
            'cns': hostname,
            'ip': ip,
        }
        return self._api_request('POST', '/domains/delete-cns-ip', data=data)

    def childns_get(self, order_id):
        """Get child nameservers for a domain."""
        params = {'order-id': order_id}
        return self._api_request('GET', '/domains/cns', params)

    # ===================
    # Control Panel SSO Methods
    # ===================

    def hosting_get_cpanel_url(self, order_id):
        """
        Get single sign-on URL for hosting cPanel.

        :param order_id: Hosting order ID
        :return: SSO URL for cPanel access
        """
        params = {'order-id': order_id}
        return self._api_request('GET', '/hosting/linux/cpanel-url', params)

    def hosting_get_webmail_url(self, order_id):
        """
        Get single sign-on URL for webmail.

        :param order_id: Hosting order ID
        :return: SSO URL for webmail access
        """
        params = {'order-id': order_id}
        return self._api_request('GET', '/hosting/linux/webmail-url', params)

    def vps_get_panel_url(self, order_id):
        """
        Get single sign-on URL for VPS control panel.

        :param order_id: VPS order ID
        :return: SSO URL for VPS panel access
        """
        params = {'order-id': order_id}
        return self._api_request('GET', '/vps/linux/panel-url', params)

    def email_get_control_panel_url(self, order_id):
        """
        Get single sign-on URL for email control panel.

        :param order_id: Email hosting order ID
        :return: SSO URL for email admin panel
        """
        params = {'order-id': order_id}
        return self._api_request('GET', '/mail/control-panel-url', params)

    # ===================
    # Website Builder API Methods
    # ===================

    def sitebuilder_get_plans(self):
        """Get available website builder plans."""
        return self._api_request('GET', '/sitebuilder/plans')

    def sitebuilder_order(self, domain_name, customer_id, plan_id, months):
        """
        Order website builder.

        :param domain_name: Domain name for the site
        :param customer_id: ResellerClub customer ID
        :param plan_id: Site builder plan ID
        :param months: Number of months
        :return: Order response
        """
        data = {
            'domain-name': domain_name,
            'customer-id': customer_id,
            'plan-id': plan_id,
            'months': months,
            'invoice-option': 'NoInvoice',
        }
        return self._api_request('POST', '/sitebuilder/add', data=data)

    def sitebuilder_renew(self, order_id, months, exp_date):
        """Renew website builder subscription."""
        data = {
            'order-id': order_id,
            'months': months,
            'exp-date': exp_date,
            'invoice-option': 'NoInvoice',
        }
        return self._api_request('POST', '/sitebuilder/renew', data=data)

    def sitebuilder_get_details(self, order_id):
        """Get website builder order details."""
        params = {'order-id': order_id}
        return self._api_request('GET', '/sitebuilder/details', params)


class ResellerClubAPILog(models.Model):
    """Model to store API call logs for debugging and audit."""
    _name = 'resellerclub.api.log'
    _description = 'ResellerClub API Log'
    _order = 'create_date desc'
    _rec_name = 'endpoint'

    method = fields.Char(string='HTTP Method', readonly=True)
    endpoint = fields.Char(string='API Endpoint', readonly=True, index=True)
    request_params = fields.Text(string='Request Parameters', readonly=True)
    response_data = fields.Text(string='Response Data', readonly=True)
    duration = fields.Float(string='Duration (seconds)', readonly=True)
    user_id = fields.Many2one('res.users', string='User', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)

    def action_view_details(self):
        """Open detailed view of the log entry."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('API Log Details'),
            'res_model': 'resellerclub.api.log',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    @api.autovacuum
    def _gc_old_logs(self):
        """Garbage collect old log entries (older than 30 days)."""
        limit_date = fields.Datetime.subtract(fields.Datetime.now(), days=30)
        old_logs = self.search([('create_date', '<', limit_date)])
        old_logs.unlink()
        _logger.info("Cleaned up %d old API log entries", len(old_logs))

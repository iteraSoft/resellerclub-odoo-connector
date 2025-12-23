# -*- coding: utf-8 -*-

import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # ResellerClub specific fields
    is_resellerclub_product = fields.Boolean(
        string='ResellerClub Product',
        default=False,
        help="This product is sourced from ResellerClub"
    )

    rc_product_type = fields.Selection([
        ('domain', 'Domain Registration'),
        ('domain_transfer', 'Domain Transfer'),
        ('domain_renewal', 'Domain Renewal'),
        ('hosting_single', 'Single Domain Hosting'),
        ('hosting_multi', 'Multi Domain Hosting'),
        ('hosting_reseller', 'Reseller Hosting'),
        ('email', 'Email Hosting'),
        ('ssl', 'SSL Certificate'),
        ('vps', 'VPS Server'),
        ('dedicated', 'Dedicated Server'),
        ('sitebuilder', 'Website Builder'),
        ('sitelock', 'SiteLock'),
        ('codeguard', 'CodeGuard'),
    ], string='RC Product Type')

    rc_plan_id = fields.Char(
        string='RC Plan ID',
        help="ResellerClub plan/product ID"
    )

    rc_tld = fields.Char(
        string='TLD',
        help="Domain TLD (for domain products only)"
    )

    rc_cost_price = fields.Float(
        string='RC Cost Price',
        help="Cost price from ResellerClub"
    )

    rc_min_years = fields.Integer(
        string='Min Registration Years',
        default=1
    )

    rc_max_years = fields.Integer(
        string='Max Registration Years',
        default=10
    )

    rc_supports_privacy = fields.Boolean(
        string='Supports Privacy Protection',
        default=False
    )

    rc_supports_transfer = fields.Boolean(
        string='Supports Transfer',
        default=True
    )

    rc_last_sync = fields.Datetime(
        string='Last Price Sync'
    )

    @api.model
    def _sync_resellerclub_domains(self):
        """
        Synchronize domain TLD products from ResellerClub.

        Returns the count of synced products.
        """
        api = self.env['resellerclub.api']
        company = self.env.company

        try:
            pricing_data = api.get_domain_pricing()
        except Exception as e:
            _logger.error("Failed to get domain pricing: %s", str(e))
            return 0

        if not isinstance(pricing_data, dict):
            return 0

        # Get or create domain category
        domain_category = self.env.ref(
            'resellerclub_integration.product_category_domains',
            raise_if_not_found=False
        )
        if not domain_category:
            domain_category = self.env['product.category'].create({
                'name': 'Domains',
            })

        synced_count = 0
        margin = company.resellerclub_domain_margin / 100.0

        for tld, tld_data in pricing_data.items():
            if not isinstance(tld_data, dict):
                continue

            # Get registration price
            reg_price = 0
            if 'addnewdomain' in tld_data:
                prices = tld_data['addnewdomain']
                if isinstance(prices, dict) and '1' in prices:
                    reg_price = float(prices['1'])
                elif isinstance(prices, (int, float)):
                    reg_price = float(prices)

            if reg_price <= 0:
                continue

            # Calculate selling price with margin
            sell_price = reg_price * (1 + margin)

            # Search for existing product
            existing = self.search([
                ('is_resellerclub_product', '=', True),
                ('rc_product_type', '=', 'domain'),
                ('rc_tld', '=', tld),
            ], limit=1)

            vals = {
                'is_resellerclub_product': True,
                'rc_product_type': 'domain',
                'rc_tld': tld,
                'rc_cost_price': reg_price,
                'rc_last_sync': fields.Datetime.now(),
                'list_price': sell_price,
                'standard_price': reg_price,
                'type': 'service',
                'categ_id': domain_category.id,
                'sale_ok': True,
                'purchase_ok': False,
            }

            if existing:
                existing.write(vals)
            else:
                vals['name'] = f'.{tld} Domain Registration'
                self.create(vals)

            synced_count += 1

        _logger.info("Synced %d domain TLDs from ResellerClub", synced_count)
        return synced_count

    @api.model
    def _sync_resellerclub_hosting(self):
        """
        Synchronize hosting plans from ResellerClub.

        Returns the count of synced products.
        """
        api = self.env['resellerclub.api']
        company = self.env.company

        try:
            plans = api.hosting_get_plans()
        except Exception as e:
            _logger.error("Failed to get hosting plans: %s", str(e))
            return 0

        if not isinstance(plans, dict):
            return 0

        # Get or create hosting category
        hosting_category = self.env.ref(
            'resellerclub_integration.product_category_hosting',
            raise_if_not_found=False
        )
        if not hosting_category:
            hosting_category = self.env['product.category'].create({
                'name': 'Web Hosting',
            })

        synced_count = 0
        margin = company.resellerclub_hosting_margin / 100.0

        for plan_id, plan_data in plans.items():
            if not isinstance(plan_data, dict):
                continue

            plan_name = plan_data.get('planname', f'Plan {plan_id}')
            cost_price = float(plan_data.get('price', 0))

            if cost_price <= 0:
                continue

            sell_price = cost_price * (1 + margin)

            existing = self.search([
                ('is_resellerclub_product', '=', True),
                ('rc_product_type', 'in', ['hosting_single', 'hosting_multi', 'hosting_reseller']),
                ('rc_plan_id', '=', plan_id),
            ], limit=1)

            # Determine hosting type
            hosting_type = 'hosting_single'
            if 'reseller' in plan_name.lower():
                hosting_type = 'hosting_reseller'
            elif 'multi' in plan_name.lower() or 'unlimited' in plan_name.lower():
                hosting_type = 'hosting_multi'

            vals = {
                'is_resellerclub_product': True,
                'rc_product_type': hosting_type,
                'rc_plan_id': plan_id,
                'rc_cost_price': cost_price,
                'rc_last_sync': fields.Datetime.now(),
                'list_price': sell_price,
                'standard_price': cost_price,
                'type': 'service',
                'categ_id': hosting_category.id,
                'sale_ok': True,
                'purchase_ok': False,
            }

            if existing:
                existing.write(vals)
            else:
                vals['name'] = plan_name
                self.create(vals)

            synced_count += 1

        _logger.info("Synced %d hosting plans from ResellerClub", synced_count)
        return synced_count

    @api.model
    def _sync_resellerclub_ssl(self):
        """
        Synchronize SSL certificate plans from ResellerClub.

        Returns the count of synced products.
        """
        api = self.env['resellerclub.api']
        company = self.env.company

        try:
            plans = api.ssl_get_plans()
        except Exception as e:
            _logger.error("Failed to get SSL plans: %s", str(e))
            return 0

        if not isinstance(plans, dict):
            return 0

        # Get or create SSL category
        ssl_category = self.env.ref(
            'resellerclub_integration.product_category_ssl',
            raise_if_not_found=False
        )
        if not ssl_category:
            ssl_category = self.env['product.category'].create({
                'name': 'SSL Certificates',
            })

        synced_count = 0
        margin = company.resellerclub_ssl_margin / 100.0

        for plan_id, plan_data in plans.items():
            if not isinstance(plan_data, dict):
                continue

            plan_name = plan_data.get('planname', f'SSL Plan {plan_id}')
            cost_price = float(plan_data.get('price', 0))

            if cost_price <= 0:
                continue

            sell_price = cost_price * (1 + margin)

            existing = self.search([
                ('is_resellerclub_product', '=', True),
                ('rc_product_type', '=', 'ssl'),
                ('rc_plan_id', '=', plan_id),
            ], limit=1)

            vals = {
                'is_resellerclub_product': True,
                'rc_product_type': 'ssl',
                'rc_plan_id': plan_id,
                'rc_cost_price': cost_price,
                'rc_last_sync': fields.Datetime.now(),
                'list_price': sell_price,
                'standard_price': cost_price,
                'type': 'service',
                'categ_id': ssl_category.id,
                'sale_ok': True,
                'purchase_ok': False,
            }

            if existing:
                existing.write(vals)
            else:
                vals['name'] = plan_name
                self.create(vals)

            synced_count += 1

        _logger.info("Synced %d SSL plans from ResellerClub", synced_count)
        return synced_count

    def action_sync_from_resellerclub(self):
        """Sync this product's pricing from ResellerClub."""
        self.ensure_one()

        if not self.is_resellerclub_product:
            raise UserError(_("This is not a ResellerClub product."))

        company = self.env.company
        api = self.env['resellerclub.api']

        if self.rc_product_type == 'domain' and self.rc_tld:
            pricing = api.get_domain_pricing(tlds=[self.rc_tld])
            if isinstance(pricing, dict) and self.rc_tld in pricing:
                tld_data = pricing[self.rc_tld]
                if isinstance(tld_data, dict) and 'addnewdomain' in tld_data:
                    prices = tld_data['addnewdomain']
                    if isinstance(prices, dict) and '1' in prices:
                        cost = float(prices['1'])
                        margin = company.resellerclub_domain_margin / 100.0
                        self.write({
                            'rc_cost_price': cost,
                            'standard_price': cost,
                            'list_price': cost * (1 + margin),
                            'rc_last_sync': fields.Datetime.now(),
                        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Product Synced'),
                'message': _('Product pricing has been synchronized from ResellerClub.'),
                'type': 'success',
                'sticky': False,
            }
        }

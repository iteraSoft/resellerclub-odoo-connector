# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HostingOrderWizard(models.TransientModel):
    """Wizard to order hosting services."""
    _name = 'resellerclub.hosting.order.wizard'
    _description = 'Order Hosting Wizard'

    domain_name = fields.Char(
        string='Domain Name',
        required=True,
        help="Domain name for the hosting account"
    )

    customer_id = fields.Many2one(
        'resellerclub.customer',
        string='Customer',
        required=True,
        domain="[('resellerclub_customer_id', '!=', False)]"
    )

    hosting_type = fields.Selection([
        ('single', 'Single Domain Hosting'),
        ('multi', 'Multi Domain Hosting'),
        ('reseller', 'Reseller Hosting'),
        ('email', 'Email Hosting'),
    ], string='Hosting Type', required=True, default='single')

    product_id = fields.Many2one(
        'product.template',
        string='Hosting Plan',
        required=True,
        domain="[('is_resellerclub_product', '=', True), ('rc_product_type', 'in', ['hosting_single', 'hosting_multi', 'hosting_reseller', 'email'])]"
    )

    months = fields.Selection([
        ('1', '1 Month'),
        ('3', '3 Months'),
        ('6', '6 Months'),
        ('12', '12 Months (1 Year)'),
        ('24', '24 Months (2 Years)'),
        ('36', '36 Months (3 Years)'),
    ], string='Billing Period', default='12', required=True)

    auto_renew = fields.Boolean(
        string='Auto Renew',
        default=False
    )

    # Email hosting specific
    email_accounts = fields.Integer(
        string='Number of Email Accounts',
        default=5
    )

    estimated_cost = fields.Float(
        string='Estimated Cost',
        compute='_compute_estimated_cost'
    )

    @api.depends('product_id', 'months')
    def _compute_estimated_cost(self):
        for wizard in self:
            if wizard.product_id and wizard.months:
                # Price is per month
                monthly_price = wizard.product_id.list_price
                wizard.estimated_cost = monthly_price * int(wizard.months)
            else:
                wizard.estimated_cost = 0.0

    @api.onchange('hosting_type')
    def _onchange_hosting_type(self):
        """Update product domain based on hosting type."""
        type_map = {
            'single': 'hosting_single',
            'multi': 'hosting_multi',
            'reseller': 'hosting_reseller',
            'email': 'email',
        }
        rc_type = type_map.get(self.hosting_type, 'hosting_single')
        self.product_id = False

        return {
            'domain': {
                'product_id': [
                    ('is_resellerclub_product', '=', True),
                    ('rc_product_type', '=', rc_type),
                ]
            }
        }

    def action_order(self):
        """Order the hosting plan."""
        self.ensure_one()

        if not self.customer_id.resellerclub_customer_id:
            raise UserError(_("Customer must be created in ResellerClub first."))

        if not self.product_id.rc_plan_id:
            raise UserError(_("Selected product has no ResellerClub plan ID."))

        # Create hosting record
        hosting = self.env['resellerclub.hosting'].create({
            'domain_name': self.domain_name.lower(),
            'customer_id': self.customer_id.id,
            'hosting_type': self.hosting_type,
            'plan_id': self.product_id.rc_plan_id,
            'plan_name': self.product_id.name,
            'months': int(self.months),
            'auto_renew': self.auto_renew,
            'email_accounts': self.email_accounts if self.hosting_type == 'email' else 0,
        })

        # Order in ResellerClub
        hosting.action_order_hosting()

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'resellerclub.hosting',
            'res_id': hosting.id,
            'view_mode': 'form',
            'target': 'current',
        }

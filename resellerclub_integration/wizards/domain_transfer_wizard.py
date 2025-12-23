# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class DomainTransferWizard(models.TransientModel):
    """Wizard to transfer domains from other registrars."""
    _name = 'resellerclub.domain.transfer.wizard'
    _description = 'Transfer Domain Wizard'

    domain_name = fields.Char(
        string='Domain Name',
        required=True,
        help="Enter the domain name to transfer (e.g., example.com)"
    )

    auth_code = fields.Char(
        string='Authorization Code',
        required=True,
        help="EPP/Transfer authorization code from current registrar"
    )

    customer_id = fields.Many2one(
        'resellerclub.customer',
        string='Customer',
        required=True,
        domain="[('resellerclub_customer_id', '!=', False)]"
    )

    # Nameservers
    keep_existing_ns = fields.Boolean(
        string='Keep Existing Nameservers',
        default=True,
        help="Keep the current nameservers after transfer"
    )
    ns1 = fields.Char(string='Nameserver 1')
    ns2 = fields.Char(string='Nameserver 2')
    ns3 = fields.Char(string='Nameserver 3')
    ns4 = fields.Char(string='Nameserver 4')

    # Pricing
    estimated_cost = fields.Float(
        string='Estimated Transfer Cost',
        compute='_compute_estimated_cost'
    )

    @api.depends('domain_name')
    def _compute_estimated_cost(self):
        for wizard in self:
            wizard.estimated_cost = 0.0

            if wizard.domain_name and '.' in wizard.domain_name:
                tld = wizard.domain_name.rsplit('.', 1)[1]
                product = self.env['product.template'].search([
                    ('is_resellerclub_product', '=', True),
                    ('rc_product_type', '=', 'domain_transfer'),
                    ('rc_tld', '=', tld),
                ], limit=1)

                if not product:
                    # Fall back to domain registration price
                    product = self.env['product.template'].search([
                        ('is_resellerclub_product', '=', True),
                        ('rc_product_type', '=', 'domain'),
                        ('rc_tld', '=', tld),
                    ], limit=1)

                if product:
                    wizard.estimated_cost = product.list_price

    @api.constrains('domain_name')
    def _check_domain_name(self):
        import re
        domain_pattern = re.compile(
            r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$'
        )
        for wizard in self:
            if wizard.domain_name and not domain_pattern.match(wizard.domain_name):
                raise ValidationError(
                    _("Invalid domain name format.")
                )

    @api.onchange('keep_existing_ns')
    def _onchange_keep_existing_ns(self):
        if not self.keep_existing_ns:
            company = self.env.company
            self.ns1 = company.resellerclub_default_ns1
            self.ns2 = company.resellerclub_default_ns2
            self.ns3 = company.resellerclub_default_ns3
            self.ns4 = company.resellerclub_default_ns4

    def action_transfer(self):
        """Initiate domain transfer."""
        self.ensure_one()

        if not self.customer_id.resellerclub_customer_id:
            raise UserError(_("Customer must be created in ResellerClub first."))

        if not self.auth_code:
            raise UserError(_("Authorization code is required for domain transfer."))

        # Check if domain already exists
        existing = self.env['resellerclub.domain'].search([
            ('domain_name', '=', self.domain_name.lower()),
            ('company_id', '=', self.env.company.id),
        ], limit=1)

        if existing:
            raise UserError(
                _("Domain %s already exists in the system.") % self.domain_name
            )

        # Get contact IDs
        contact_id = self.customer_id.default_contact_id
        if not contact_id:
            raise UserError(_("Customer has no default contact."))

        contact_ids = {
            'registrant': contact_id,
            'admin': contact_id,
            'tech': contact_id,
            'billing': contact_id,
        }

        # Prepare nameservers
        nameservers = None
        if not self.keep_existing_ns:
            nameservers = [ns for ns in [self.ns1, self.ns2, self.ns3, self.ns4] if ns]

        api = self.env['resellerclub.api']

        try:
            result = api.domain_transfer(
                domain_name=self.domain_name.lower(),
                auth_code=self.auth_code,
                customer_id=self.customer_id.resellerclub_customer_id,
                contact_ids=contact_ids,
                nameservers=nameservers,
            )

            # Create domain record
            order_id = None
            if isinstance(result, dict):
                order_id = result.get('orderid') or result.get('entityid')
            elif isinstance(result, (int, str)):
                order_id = str(result)

            domain = self.env['resellerclub.domain'].create({
                'domain_name': self.domain_name.lower(),
                'customer_id': self.customer_id.id,
                'resellerclub_order_id': order_id,
                'status': 'pending_transfer',
                'ns1': self.ns1 if not self.keep_existing_ns else False,
                'ns2': self.ns2 if not self.keep_existing_ns else False,
                'ns3': self.ns3 if not self.keep_existing_ns else False,
                'ns4': self.ns4 if not self.keep_existing_ns else False,
            })

            domain.message_post(
                body=_("Transfer initiated. Order ID: %s") % order_id,
                message_type='notification'
            )

            return {
                'type': 'ir.actions.act_window',
                'res_model': 'resellerclub.domain',
                'res_id': domain.id,
                'view_mode': 'form',
                'target': 'current',
            }

        except Exception as e:
            raise UserError(_("Transfer failed: %s") % str(e))

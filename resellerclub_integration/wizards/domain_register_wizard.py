# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class DomainRegisterWizard(models.TransientModel):
    """Wizard to register new domains."""
    _name = 'resellerclub.domain.register.wizard'
    _description = 'Register Domain Wizard'

    domain_name = fields.Char(
        string='Domain Name',
        required=True,
        help="Enter the full domain name (e.g., example.com)"
    )

    customer_id = fields.Many2one(
        'resellerclub.customer',
        string='Customer',
        required=True,
        domain="[('resellerclub_customer_id', '!=', False)]"
    )

    years = fields.Selection([
        ('1', '1 Year'),
        ('2', '2 Years'),
        ('3', '3 Years'),
        ('4', '4 Years'),
        ('5', '5 Years'),
        ('6', '6 Years'),
        ('7', '7 Years'),
        ('8', '8 Years'),
        ('9', '9 Years'),
        ('10', '10 Years'),
    ], string='Registration Period', default='1', required=True)

    privacy_protection = fields.Boolean(
        string='Privacy Protection',
        default=False,
        help="Enable WHOIS privacy protection"
    )

    # Nameservers
    use_default_ns = fields.Boolean(
        string='Use Default Nameservers',
        default=True
    )
    ns1 = fields.Char(string='Nameserver 1')
    ns2 = fields.Char(string='Nameserver 2')
    ns3 = fields.Char(string='Nameserver 3')
    ns4 = fields.Char(string='Nameserver 4')

    # Availability check
    is_available = fields.Boolean(
        string='Is Available',
        compute='_compute_availability',
        store=False
    )
    availability_message = fields.Char(
        string='Availability',
        compute='_compute_availability',
        store=False
    )

    # Pricing
    estimated_cost = fields.Float(
        string='Estimated Cost',
        compute='_compute_estimated_cost'
    )

    @api.depends('domain_name')
    def _compute_availability(self):
        for wizard in self:
            wizard.is_available = False
            wizard.availability_message = ''

            if wizard.domain_name and '.' in wizard.domain_name:
                try:
                    parts = wizard.domain_name.rsplit('.', 1)
                    sld = parts[0]
                    tld = parts[1]

                    api = self.env['resellerclub.api']
                    result = api.domain_check_availability(sld, [tld])

                    if isinstance(result, dict):
                        domain_key = wizard.domain_name.lower()
                        status = result.get(domain_key, {})

                        if isinstance(status, dict):
                            if status.get('status') == 'available':
                                wizard.is_available = True
                                wizard.availability_message = _('Domain is available!')
                            else:
                                wizard.availability_message = _('Domain is not available')
                        elif status == 'available':
                            wizard.is_available = True
                            wizard.availability_message = _('Domain is available!')
                        else:
                            wizard.availability_message = _('Domain is not available')

                except Exception as e:
                    wizard.availability_message = _('Could not check availability')

    @api.depends('domain_name', 'years', 'privacy_protection')
    def _compute_estimated_cost(self):
        for wizard in self:
            wizard.estimated_cost = 0.0

            if wizard.domain_name and '.' in wizard.domain_name:
                tld = wizard.domain_name.rsplit('.', 1)[1]
                product = self.env['product.template'].search([
                    ('is_resellerclub_product', '=', True),
                    ('rc_product_type', '=', 'domain'),
                    ('rc_tld', '=', tld),
                ], limit=1)

                if product:
                    wizard.estimated_cost = product.list_price * int(wizard.years or 1)

    @api.constrains('domain_name')
    def _check_domain_name(self):
        import re
        domain_pattern = re.compile(
            r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$'
        )
        for wizard in self:
            if wizard.domain_name and not domain_pattern.match(wizard.domain_name):
                raise ValidationError(
                    _("Invalid domain name format. Please enter a valid domain (e.g., example.com)")
                )

    @api.onchange('use_default_ns')
    def _onchange_use_default_ns(self):
        if self.use_default_ns:
            company = self.env.company
            self.ns1 = company.resellerclub_default_ns1
            self.ns2 = company.resellerclub_default_ns2
            self.ns3 = company.resellerclub_default_ns3
            self.ns4 = company.resellerclub_default_ns4
        else:
            self.ns1 = ''
            self.ns2 = ''
            self.ns3 = ''
            self.ns4 = ''

    def action_check_availability(self):
        """Check domain availability."""
        self.ensure_one()
        # Trigger recompute
        self._compute_availability()

        if self.is_available:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Domain Available'),
                    'message': _('%s is available for registration!') % self.domain_name,
                    'type': 'success',
                    'sticky': False,
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Domain Not Available'),
                    'message': _('%s is not available.') % self.domain_name,
                    'type': 'warning',
                    'sticky': False,
                }
            }

    def action_register(self):
        """Register the domain."""
        self.ensure_one()

        if not self.is_available:
            raise UserError(_("This domain is not available for registration."))

        if not self.customer_id.resellerclub_customer_id:
            raise UserError(_("Customer must be created in ResellerClub first."))

        # Create domain record
        domain = self.env['resellerclub.domain'].create({
            'domain_name': self.domain_name.lower(),
            'customer_id': self.customer_id.id,
            'years': int(self.years),
            'privacy_protection': self.privacy_protection,
            'ns1': self.ns1,
            'ns2': self.ns2,
            'ns3': self.ns3,
            'ns4': self.ns4,
        })

        # Register in ResellerClub
        domain.action_register_domain()

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'resellerclub.domain',
            'res_id': domain.id,
            'view_mode': 'form',
            'target': 'current',
        }

# -*- coding: utf-8 -*-

import re
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class ResellerClubCustomer(models.Model):
    """
    Model to store ResellerClub customer records linked to Odoo partners.

    This model maintains the link between Odoo contacts and ResellerClub
    customers, storing the ResellerClub customer ID and sync status.
    """
    _name = 'resellerclub.customer'
    _description = 'ResellerClub Customer'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(
        string='Customer Name',
        compute='_compute_name',
        store=True
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Odoo Contact',
        required=True,
        ondelete='cascade',
        index=True
    )
    resellerclub_customer_id = fields.Char(
        string='ResellerClub Customer ID',
        index=True,
        tracking=True
    )
    email = fields.Char(
        string='Email',
        related='partner_id.email',
        readonly=True
    )
    company = fields.Char(
        string='Company',
        related='partner_id.commercial_company_name',
        readonly=True
    )

    # ResellerClub specific fields
    rc_status = fields.Selection([
        ('active', 'Active'),
        ('suspended', 'Suspended'),
        ('inactive', 'Inactive'),
        ('deleted', 'Deleted'),
    ], string='RC Status', default='active', tracking=True)

    rc_total_receipts = fields.Float(
        string='Total Receipts',
        readonly=True
    )
    rc_selling_currency = fields.Char(
        string='Selling Currency',
        readonly=True
    )
    rc_language = fields.Char(
        string='Language Preference',
        default='en'
    )

    # Contact IDs in ResellerClub
    default_contact_id = fields.Char(
        string='Default Contact ID',
        help="Default contact ID in ResellerClub for domain registrations"
    )

    # Sync tracking
    last_sync_date = fields.Datetime(
        string='Last Synchronized',
        readonly=True
    )
    sync_status = fields.Selection([
        ('pending', 'Pending Sync'),
        ('synced', 'Synchronized'),
        ('error', 'Sync Error'),
    ], string='Sync Status', default='pending', tracking=True)
    sync_error_message = fields.Text(
        string='Sync Error Message',
        readonly=True
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True
    )

    # Related records
    domain_ids = fields.One2many(
        'resellerclub.domain',
        'customer_id',
        string='Domains'
    )
    hosting_ids = fields.One2many(
        'resellerclub.hosting',
        'customer_id',
        string='Hosting'
    )
    ssl_ids = fields.One2many(
        'resellerclub.ssl',
        'customer_id',
        string='SSL Certificates'
    )

    domain_count = fields.Integer(
        string='Domains',
        compute='_compute_counts'
    )
    hosting_count = fields.Integer(
        string='Hosting Plans',
        compute='_compute_counts'
    )
    ssl_count = fields.Integer(
        string='SSL Certificates',
        compute='_compute_counts'
    )

    _sql_constraints = [
        ('partner_company_uniq', 'unique(partner_id, company_id)',
         'A partner can only have one ResellerClub customer per company!'),
        ('rc_customer_id_uniq', 'unique(resellerclub_customer_id, company_id)',
         'ResellerClub customer ID must be unique per company!'),
    ]

    @api.depends('partner_id.name')
    def _compute_name(self):
        for record in self:
            record.name = record.partner_id.name or _('New Customer')

    @api.depends('domain_ids', 'hosting_ids', 'ssl_ids')
    def _compute_counts(self):
        for record in self:
            record.domain_count = len(record.domain_ids)
            record.hosting_count = len(record.hosting_ids)
            record.ssl_count = len(record.ssl_ids)

    @api.model_create_multi
    def create(self, vals_list):
        """Create customer and optionally sync to ResellerClub."""
        records = super().create(vals_list)
        for record in records:
            if self.env.company.resellerclub_auto_create_customer and not record.resellerclub_customer_id:
                try:
                    record.action_create_in_resellerclub()
                except Exception as e:
                    _logger.warning("Failed to auto-create customer in ResellerClub: %s", str(e))
        return records

    def _prepare_resellerclub_data(self):
        """Prepare data for ResellerClub API from partner record."""
        self.ensure_one()
        partner = self.partner_id

        if not partner.email:
            raise ValidationError(_("Partner email is required for ResellerClub."))
        if not partner.name:
            raise ValidationError(_("Partner name is required for ResellerClub."))

        # Extract phone country code and number
        phone = partner.phone or partner.mobile or ''
        phone_cc = '1'  # Default to US
        phone_number = phone

        # Try to parse phone with country code
        if phone.startswith('+'):
            match = re.match(r'\+(\d{1,3})[\s\-]?(.+)', phone)
            if match:
                phone_cc = match.group(1)
                phone_number = re.sub(r'[\s\-\(\)]', '', match.group(2))
        else:
            phone_number = re.sub(r'[\s\-\(\)]', '', phone)

        if not phone_number:
            phone_number = '0000000000'  # Default placeholder

        # Get address components
        address = partner.street or 'N/A'
        city = partner.city or 'N/A'
        state = partner.state_id.code if partner.state_id else 'N/A'
        country_code = partner.country_id.code if partner.country_id else 'US'
        zipcode = partner.zip or '00000'

        return {
            'email': partner.email,
            'password': self._generate_temp_password(),
            'name': partner.name,
            'company': partner.commercial_company_name or partner.name,
            'address': address,
            'city': city,
            'state': state,
            'country_code': country_code,
            'zipcode': zipcode,
            'phone_cc': phone_cc,
            'phone': phone_number,
            'lang_pref': partner.lang[:2] if partner.lang else 'en',
        }

    def _generate_temp_password(self):
        """Generate a temporary password for new ResellerClub customers."""
        import secrets
        import string
        alphabet = string.ascii_letters + string.digits + '!@#$%'
        return ''.join(secrets.choice(alphabet) for _ in range(12))

    def action_create_in_resellerclub(self):
        """Create this customer in ResellerClub."""
        self.ensure_one()

        if self.resellerclub_customer_id:
            raise UserError(_("Customer already exists in ResellerClub with ID: %s") % self.resellerclub_customer_id)

        api = self.env['resellerclub.api']
        data = self._prepare_resellerclub_data()

        try:
            result = api.customer_create(**data)

            if isinstance(result, (int, str)):
                customer_id = str(result)
            elif isinstance(result, dict) and 'customerid' in result:
                customer_id = str(result['customerid'])
            else:
                raise UserError(_("Unexpected response from ResellerClub: %s") % result)

            # Also create a default contact
            contact_result = api.contact_create(
                customer_id=customer_id,
                email=data['email'],
                name=data['name'],
                company=data['company'],
                address=data['address'],
                city=data['city'],
                state=data['state'],
                country_code=data['country_code'],
                zipcode=data['zipcode'],
                phone_cc=data['phone_cc'],
                phone=data['phone'],
            )

            contact_id = None
            if isinstance(contact_result, (int, str)):
                contact_id = str(contact_result)
            elif isinstance(contact_result, dict) and 'contactid' in contact_result:
                contact_id = str(contact_result['contactid'])

            self.write({
                'resellerclub_customer_id': customer_id,
                'default_contact_id': contact_id,
                'sync_status': 'synced',
                'last_sync_date': fields.Datetime.now(),
                'sync_error_message': False,
            })

            self.message_post(
                body=_("Customer created in ResellerClub with ID: %s") % customer_id,
                message_type='notification'
            )

        except Exception as e:
            self.write({
                'sync_status': 'error',
                'sync_error_message': str(e),
            })
            raise

        return True

    def action_sync_from_resellerclub(self):
        """Sync customer data from ResellerClub."""
        self.ensure_one()

        if not self.resellerclub_customer_id:
            raise UserError(_("No ResellerClub Customer ID set."))

        api = self.env['resellerclub.api']

        try:
            result = api.customer_get_details(customer_id=self.resellerclub_customer_id)

            if isinstance(result, dict):
                self.write({
                    'rc_status': result.get('customerstatus', 'active').lower(),
                    'rc_total_receipts': float(result.get('totalreceipts', 0)),
                    'rc_selling_currency': result.get('sellingcurrency', 'USD'),
                    'rc_language': result.get('langpref', 'en'),
                    'sync_status': 'synced',
                    'last_sync_date': fields.Datetime.now(),
                    'sync_error_message': False,
                })

        except Exception as e:
            self.write({
                'sync_status': 'error',
                'sync_error_message': str(e),
            })
            raise

        return True

    def action_view_domains(self):
        """View domains for this customer."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Domains'),
            'res_model': 'resellerclub.domain',
            'view_mode': 'list,form',
            'domain': [('customer_id', '=', self.id)],
            'context': {'default_customer_id': self.id},
        }

    def action_view_hosting(self):
        """View hosting plans for this customer."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Hosting Plans'),
            'res_model': 'resellerclub.hosting',
            'view_mode': 'list,form',
            'domain': [('customer_id', '=', self.id)],
            'context': {'default_customer_id': self.id},
        }

    def action_view_ssl(self):
        """View SSL certificates for this customer."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('SSL Certificates'),
            'res_model': 'resellerclub.ssl',
            'view_mode': 'list,form',
            'domain': [('customer_id', '=', self.id)],
            'context': {'default_customer_id': self.id},
        }

    def action_open_resellerclub(self):
        """Open customer in ResellerClub control panel."""
        self.ensure_one()
        if not self.resellerclub_customer_id:
            raise UserError(_("Customer is not linked to ResellerClub."))

        # Generate control panel URL
        base_url = 'https://manage.resellerclub.com'
        if self.env.company.resellerclub_test_mode:
            base_url = 'https://test.manage.resellerclub.com'

        return {
            'type': 'ir.actions.act_url',
            'url': f"{base_url}/servlet/ResellerSignupServlet?&role=reseller",
            'target': 'new',
        }

    @api.model
    def cron_sync_customers(self):
        """Cron job to sync all customers with ResellerClub."""
        customers = self.search([
            ('resellerclub_customer_id', '!=', False),
            ('sync_status', '!=', 'synced'),
        ], limit=100)

        for customer in customers:
            try:
                customer.action_sync_from_resellerclub()
            except Exception as e:
                _logger.warning("Failed to sync customer %s: %s", customer.id, str(e))

        return True


class ResellerClubContact(models.Model):
    """
    Model to store ResellerClub contact records.

    Contacts in ResellerClub are used for domain registrations (registrant,
    admin, tech, billing contacts).
    """
    _name = 'resellerclub.contact'
    _description = 'ResellerClub Contact'
    _order = 'name'

    name = fields.Char(string='Contact Name', required=True)
    customer_id = fields.Many2one(
        'resellerclub.customer',
        string='Customer',
        required=True,
        ondelete='cascade'
    )
    resellerclub_contact_id = fields.Char(
        string='ResellerClub Contact ID',
        index=True
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Linked Contact',
        help="Odoo contact linked to this ResellerClub contact"
    )

    contact_type = fields.Selection([
        ('Contact', 'Generic Contact'),
        ('CoopContact', 'Coop Contact'),
        ('UkContact', 'UK Contact'),
        ('EuContact', 'EU Contact'),
        ('CnContact', 'CN Contact'),
        ('CoContact', 'CO Contact'),
        ('CaContact', 'CA Contact'),
        ('DeContact', 'DE Contact'),
        ('EsContact', 'ES Contact'),
    ], string='Contact Type', default='Contact')

    email = fields.Char(string='Email')
    company = fields.Char(string='Company')
    address = fields.Char(string='Address')
    city = fields.Char(string='City')
    state = fields.Char(string='State')
    country_code = fields.Char(string='Country Code')
    zipcode = fields.Char(string='ZIP Code')
    phone_cc = fields.Char(string='Phone Country Code')
    phone = fields.Char(string='Phone')

    is_default = fields.Boolean(
        string='Default Contact',
        help="Use as default contact for this customer"
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='customer_id.company_id',
        store=True
    )

    _sql_constraints = [
        ('rc_contact_id_uniq', 'unique(resellerclub_contact_id, company_id)',
         'ResellerClub contact ID must be unique!'),
    ]

    def action_sync_to_resellerclub(self):
        """Create or update this contact in ResellerClub."""
        self.ensure_one()
        api = self.env['resellerclub.api']

        if not self.customer_id.resellerclub_customer_id:
            raise UserError(_("Customer must be created in ResellerClub first."))

        if self.resellerclub_contact_id:
            # Update existing contact
            result = api.contact_modify(
                contact_id=self.resellerclub_contact_id,
                name=self.name,
                company=self.company or 'N/A',
                email=self.email,
                address1=self.address,
                city=self.city,
                state=self.state,
                country=self.country_code,
                zipcode=self.zipcode,
                phone_cc=self.phone_cc,
                phone=self.phone,
            )
        else:
            # Create new contact
            result = api.contact_create(
                customer_id=self.customer_id.resellerclub_customer_id,
                email=self.email,
                name=self.name,
                company=self.company or 'N/A',
                address=self.address,
                city=self.city,
                state=self.state,
                country_code=self.country_code,
                zipcode=self.zipcode,
                phone_cc=self.phone_cc,
                phone=self.phone,
                contact_type=self.contact_type,
            )

            if isinstance(result, (int, str)):
                self.resellerclub_contact_id = str(result)
            elif isinstance(result, dict) and 'contactid' in result:
                self.resellerclub_contact_id = str(result['contactid'])

        return True

# -*- coding: utf-8 -*-

import logging
from datetime import datetime, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResellerClubSSL(models.Model):
    """
    Model to manage SSL certificates from ResellerClub.

    Supports various SSL certificate types including:
    - Domain Validation (DV)
    - Organization Validation (OV)
    - Extended Validation (EV)
    - Wildcard certificates
    - Multi-domain certificates
    """
    _name = 'resellerclub.ssl'
    _description = 'ResellerClub SSL Certificate'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'expiration_date asc'
    _rec_name = 'display_name'

    display_name = fields.Char(
        string='Name',
        compute='_compute_display_name',
        store=True
    )

    # Basic Info
    domain_name = fields.Char(
        string='Domain Name',
        required=True,
        index=True,
        tracking=True,
        help="Primary domain for the SSL certificate"
    )
    ssl_type = fields.Selection([
        ('dv', 'Domain Validation (DV)'),
        ('ov', 'Organization Validation (OV)'),
        ('ev', 'Extended Validation (EV)'),
        ('wildcard', 'Wildcard'),
        ('multi', 'Multi-Domain (SAN)'),
        ('code_signing', 'Code Signing'),
    ], string='Certificate Type', default='dv', tracking=True)

    brand = fields.Selection([
        ('comodo', 'Comodo'),
        ('thawte', 'Thawte'),
        ('geotrust', 'GeoTrust'),
        ('rapidssl', 'RapidSSL'),
        ('digicert', 'DigiCert'),
        ('symantec', 'Symantec'),
    ], string='Brand', default='comodo')

    plan_id = fields.Char(string='Plan ID')
    plan_name = fields.Char(string='Plan Name', tracking=True)

    # ResellerClub IDs
    resellerclub_order_id = fields.Char(
        string='RC Order ID',
        index=True,
        tracking=True
    )

    # Customer & Partner
    customer_id = fields.Many2one(
        'resellerclub.customer',
        string='RC Customer',
        required=True,
        ondelete='restrict',
        index=True
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        related='customer_id.partner_id',
        store=True
    )

    # Status & Dates
    status = fields.Selection([
        ('pending', 'Pending Order'),
        ('pending_issuance', 'Pending Issuance'),
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
        ('revoked', 'Revoked'),
    ], string='Status', default='pending', tracking=True, index=True)

    issuance_date = fields.Date(string='Issuance Date')
    expiration_date = fields.Date(
        string='Expiration Date',
        tracking=True,
        index=True
    )
    days_until_expiry = fields.Integer(
        string='Days Until Expiry',
        compute='_compute_days_until_expiry',
        store=True
    )
    expiry_status = fields.Selection([
        ('ok', 'OK'),
        ('warning', 'Expiring Soon'),
        ('critical', 'Critical'),
        ('expired', 'Expired'),
    ], string='Expiry Status', compute='_compute_days_until_expiry', store=True)

    months = fields.Integer(
        string='Validity (Months)',
        default=12
    )

    # Certificate Details
    csr = fields.Text(
        string='CSR',
        help="Certificate Signing Request"
    )
    private_key = fields.Text(
        string='Private Key',
        help="Private key (keep confidential)"
    )
    certificate = fields.Text(
        string='Certificate',
        help="Issued SSL certificate"
    )
    ca_bundle = fields.Text(
        string='CA Bundle',
        help="Certificate Authority chain"
    )

    # Validation
    validation_method = fields.Selection([
        ('email', 'Email Validation'),
        ('http', 'HTTP Validation'),
        ('dns', 'DNS Validation'),
    ], string='Validation Method', default='email')

    validation_email = fields.Char(
        string='Validation Email',
        help="Email address for domain validation"
    )
    validation_status = fields.Char(string='Validation Status')

    # Additional domains (for multi-domain certs)
    additional_domains = fields.Text(
        string='Additional Domains',
        help="Additional domains for multi-domain certificates (one per line)"
    )

    # Organization details (for OV/EV certs)
    organization_name = fields.Char(string='Organization Name')
    organization_unit = fields.Char(string='Department/Unit')
    city = fields.Char(string='City')
    state = fields.Char(string='State/Province')
    country_code = fields.Char(string='Country Code')

    # Sync tracking
    last_sync_date = fields.Datetime(
        string='Last Synchronized',
        readonly=True
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True
    )

    notes = fields.Text(string='Internal Notes')

    _sql_constraints = [
        ('order_id_company_uniq', 'unique(resellerclub_order_id, company_id)',
         'Order ID must be unique per company!'),
    ]

    @api.depends('domain_name', 'ssl_type', 'brand')
    def _compute_display_name(self):
        type_names = dict(self._fields['ssl_type'].selection)
        brand_names = dict(self._fields['brand'].selection)
        for record in self:
            type_name = type_names.get(record.ssl_type, 'SSL')
            brand_name = brand_names.get(record.brand, '')
            record.display_name = f"{record.domain_name} ({brand_name} {type_name})"

    @api.depends('expiration_date')
    def _compute_days_until_expiry(self):
        today = fields.Date.today()
        for record in self:
            if record.expiration_date:
                delta = record.expiration_date - today
                record.days_until_expiry = delta.days

                if delta.days < 0:
                    record.expiry_status = 'expired'
                elif delta.days <= 14:
                    record.expiry_status = 'critical'
                elif delta.days <= 30:
                    record.expiry_status = 'warning'
                else:
                    record.expiry_status = 'ok'
            else:
                record.days_until_expiry = 0
                record.expiry_status = 'ok'

    def action_order_ssl(self):
        """Order SSL certificate from ResellerClub."""
        self.ensure_one()

        if self.resellerclub_order_id:
            raise UserError(_("SSL already ordered with ID: %s") % self.resellerclub_order_id)

        if not self.customer_id.resellerclub_customer_id:
            raise UserError(_("Customer must be created in ResellerClub first."))

        if not self.plan_id:
            raise UserError(_("Please select an SSL plan."))

        api = self.env['resellerclub.api']

        try:
            result = api.ssl_order(
                domain_name=self.domain_name,
                customer_id=self.customer_id.resellerclub_customer_id,
                plan_id=self.plan_id,
                months=self.months,
                csr=self.csr if self.csr else None,
            )

            order_id = None
            if isinstance(result, dict):
                order_id = result.get('orderid') or result.get('entityid')
            elif isinstance(result, (int, str)):
                order_id = str(result)

            if order_id:
                self.write({
                    'resellerclub_order_id': str(order_id),
                    'status': 'pending_issuance',
                    'last_sync_date': fields.Datetime.now(),
                })

                self.message_post(
                    body=_("SSL certificate ordered. Order ID: %s") % order_id,
                    message_type='notification'
                )
            else:
                raise UserError(_("Order failed: No order ID returned"))

        except Exception as e:
            self.message_post(
                body=_("SSL order failed: %s") % str(e),
                message_type='notification'
            )
            raise

        return True

    def action_generate_csr(self):
        """Generate CSR for the SSL certificate."""
        self.ensure_one()

        if not self.resellerclub_order_id:
            raise UserError(_("SSL must be ordered first."))

        api = self.env['resellerclub.api']

        try:
            result = api.ssl_generate_csr(
                order_id=self.resellerclub_order_id,
                domain=self.domain_name,
                org=self.organization_name or self.partner_id.name,
                orgunit=self.organization_unit or 'IT',
                city=self.city or self.partner_id.city,
                state=self.state or (self.partner_id.state_id.name if self.partner_id.state_id else ''),
                country=self.country_code or (self.partner_id.country_id.code if self.partner_id.country_id else 'US'),
            )

            if isinstance(result, dict):
                self.csr = result.get('csr')
                self.private_key = result.get('privatekey')

            self.message_post(
                body=_("CSR generated successfully"),
                message_type='notification'
            )

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('CSR Generated'),
                    'message': _('Certificate Signing Request has been generated.'),
                    'type': 'success',
                    'sticky': False,
                }
            }

        except Exception as e:
            raise UserError(_("CSR generation failed: %s") % str(e))

    def action_enroll_certificate(self):
        """Enroll/activate the SSL certificate."""
        self.ensure_one()

        if not self.resellerclub_order_id:
            raise UserError(_("SSL must be ordered first."))

        if not self.csr:
            raise UserError(_("Please generate or provide a CSR first."))

        api = self.env['resellerclub.api']

        try:
            enroll_data = {
                'approver-email': self.validation_email,
            }

            if self.additional_domains:
                domains = [d.strip() for d in self.additional_domains.split('\n') if d.strip()]
                for i, domain in enumerate(domains):
                    enroll_data[f'additional-domain-{i+1}'] = domain

            result = api.ssl_enroll(
                order_id=self.resellerclub_order_id,
                csr=self.csr,
                **enroll_data
            )

            self.write({
                'status': 'pending_issuance',
                'last_sync_date': fields.Datetime.now(),
            })

            self.message_post(
                body=_("SSL certificate enrollment submitted. Awaiting validation."),
                message_type='notification'
            )

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Enrollment Submitted'),
                    'message': _('Certificate enrollment submitted. Please complete domain validation.'),
                    'type': 'info',
                    'sticky': True,
                }
            }

        except Exception as e:
            raise UserError(_("Enrollment failed: %s") % str(e))

    def action_sync_from_resellerclub(self):
        """Sync SSL certificate details from ResellerClub."""
        self.ensure_one()

        if not self.resellerclub_order_id:
            raise UserError(_("No ResellerClub Order ID set."))

        api = self.env['resellerclub.api']

        try:
            result = api.ssl_get_details(order_id=self.resellerclub_order_id)

            if isinstance(result, dict):
                # Parse dates
                exp_timestamp = result.get('endtime')
                exp_date = None
                if exp_timestamp:
                    exp_date = datetime.fromtimestamp(int(exp_timestamp)).date()

                issuance_timestamp = result.get('issuancetime')
                issuance_date = None
                if issuance_timestamp:
                    issuance_date = datetime.fromtimestamp(int(issuance_timestamp)).date()

                # Map status
                rc_status = result.get('orderstatus', '').lower()
                status_map = {
                    'active': 'active',
                    'inactive': 'expired',
                    'pendingissuance': 'pending_issuance',
                    'cancelled': 'cancelled',
                    'revoked': 'revoked',
                }
                status = status_map.get(rc_status, 'pending')

                update_vals = {
                    'status': status,
                    'issuance_date': issuance_date,
                    'expiration_date': exp_date,
                    'plan_name': result.get('planname'),
                    'validation_status': result.get('validationstatus'),
                    'last_sync_date': fields.Datetime.now(),
                }

                # Get certificate if issued
                if result.get('certificate'):
                    update_vals['certificate'] = result.get('certificate')
                if result.get('cabundle'):
                    update_vals['ca_bundle'] = result.get('cabundle')

                self.write(update_vals)

                self.message_post(
                    body=_("SSL synchronized from ResellerClub"),
                    message_type='notification'
                )

        except Exception as e:
            self.message_post(
                body=_("Sync failed: %s") % str(e),
                message_type='notification'
            )
            raise

        return True

    def action_renew_ssl(self):
        """Renew SSL certificate."""
        self.ensure_one()

        if not self.resellerclub_order_id:
            raise UserError(_("SSL must be ordered first."))

        api = self.env['resellerclub.api']

        try:
            exp_timestamp = int(datetime.combine(
                self.expiration_date,
                datetime.min.time()
            ).timestamp()) if self.expiration_date else 0

            result = api.ssl_renew(
                order_id=self.resellerclub_order_id,
                months=self.months,
                exp_date=exp_timestamp,
            )

            # Update status
            self.write({
                'status': 'pending_issuance',
                'last_sync_date': fields.Datetime.now(),
            })

            self.message_post(
                body=_("SSL renewal initiated. Please complete validation."),
                message_type='notification'
            )

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('SSL Renewal'),
                    'message': _('Renewal initiated. Complete domain validation to activate.'),
                    'type': 'info',
                    'sticky': True,
                }
            }

        except Exception as e:
            raise UserError(_("Renewal failed: %s") % str(e))

    def action_download_certificate(self):
        """Download the SSL certificate and related files."""
        self.ensure_one()

        if not self.certificate:
            raise UserError(_("Certificate has not been issued yet."))

        # Create a zip file with certificate files
        import base64
        import io
        import zipfile

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            if self.certificate:
                zf.writestr(f"{self.domain_name}.crt", self.certificate)
            if self.private_key:
                zf.writestr(f"{self.domain_name}.key", self.private_key)
            if self.ca_bundle:
                zf.writestr(f"{self.domain_name}.ca-bundle", self.ca_bundle)

        buffer.seek(0)
        zip_content = base64.b64encode(buffer.read())

        # Create attachment
        attachment = self.env['ir.attachment'].create({
            'name': f'{self.domain_name}_ssl_certificate.zip',
            'type': 'binary',
            'datas': zip_content,
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/zip',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def action_view_certificate(self):
        """View certificate details in a popup."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('SSL Certificate Details'),
            'res_model': 'resellerclub.ssl',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    @api.model
    def cron_sync_ssl(self):
        """Cron job to sync all SSL certificates."""
        ssls = self.search([
            ('resellerclub_order_id', '!=', False),
            ('status', 'in', ['active', 'pending_issuance']),
        ])

        for ssl in ssls:
            try:
                ssl.action_sync_from_resellerclub()
            except Exception as e:
                _logger.warning("Failed to sync SSL %s: %s", ssl.id, str(e))

        return True

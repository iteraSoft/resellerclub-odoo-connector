# -*- coding: utf-8 -*-

import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class ResellerClubDNSRecord(models.Model):
    """
    Model to manage DNS records for domains in ResellerClub.

    Supports various record types:
    - A (IPv4 address)
    - AAAA (IPv6 address)
    - CNAME (Canonical name)
    - MX (Mail exchange)
    - TXT (Text record)
    - NS (Nameserver)
    - SRV (Service)
    - CAA (Certificate Authority Authorization)
    """
    _name = 'resellerclub.dns.record'
    _description = 'DNS Record'
    _order = 'record_type, host'
    _rec_name = 'display_name'

    display_name = fields.Char(
        string='Name',
        compute='_compute_display_name',
        store=True
    )

    domain_id = fields.Many2one(
        'resellerclub.domain',
        string='Domain',
        required=True,
        ondelete='cascade',
        index=True
    )
    domain_name = fields.Char(
        string='Domain Name',
        related='domain_id.domain_name',
        store=True
    )

    record_type = fields.Selection([
        ('A', 'A (IPv4 Address)'),
        ('AAAA', 'AAAA (IPv6 Address)'),
        ('CNAME', 'CNAME (Canonical Name)'),
        ('MX', 'MX (Mail Exchange)'),
        ('TXT', 'TXT (Text Record)'),
        ('NS', 'NS (Nameserver)'),
        ('SRV', 'SRV (Service)'),
        ('CAA', 'CAA (Certificate Authority)'),
        ('SOA', 'SOA (Start of Authority)'),
    ], string='Record Type', required=True, default='A')

    host = fields.Char(
        string='Host',
        required=True,
        default='@',
        help="Use @ for the root domain, or enter subdomain (e.g., www, mail)"
    )

    value = fields.Char(
        string='Value',
        required=True,
        help="The target/value for this DNS record"
    )

    ttl = fields.Integer(
        string='TTL (seconds)',
        default=14400,
        help="Time To Live in seconds"
    )

    priority = fields.Integer(
        string='Priority',
        default=10,
        help="Priority for MX and SRV records (lower = higher priority)"
    )

    # SRV record specific fields
    srv_weight = fields.Integer(
        string='Weight',
        default=0,
        help="Weight for SRV records"
    )
    srv_port = fields.Integer(
        string='Port',
        help="Port for SRV records"
    )

    # Status
    is_synced = fields.Boolean(
        string='Synced',
        default=False
    )
    sync_error = fields.Char(string='Sync Error')

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='domain_id.company_id',
        store=True
    )

    @api.depends('host', 'record_type', 'domain_name')
    def _compute_display_name(self):
        for record in self:
            host_display = record.host if record.host != '@' else record.domain_name
            if record.host and record.host != '@' and record.domain_name:
                host_display = f"{record.host}.{record.domain_name}"
            record.display_name = f"{host_display} ({record.record_type})"

    @api.constrains('record_type', 'value')
    def _check_value_format(self):
        import re
        for record in self:
            if record.record_type == 'A':
                # Validate IPv4
                ipv4_pattern = re.compile(r'^(\d{1,3}\.){3}\d{1,3}$')
                if not ipv4_pattern.match(record.value):
                    raise ValidationError(_("Invalid IPv4 address format for A record."))
            elif record.record_type == 'AAAA':
                # Basic IPv6 validation
                try:
                    import ipaddress
                    ipaddress.IPv6Address(record.value)
                except (ValueError, ImportError):
                    pass  # Skip validation if ipaddress not available

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            try:
                record.action_sync_to_resellerclub()
            except Exception as e:
                record.sync_error = str(e)
                _logger.warning("Failed to sync DNS record: %s", str(e))
        return records

    def write(self, vals):
        result = super().write(vals)
        if any(f in vals for f in ['value', 'ttl', 'priority', 'host']):
            for record in self:
                try:
                    record.action_sync_to_resellerclub()
                except Exception as e:
                    record.sync_error = str(e)
        return result

    def unlink(self):
        for record in self:
            if record.is_synced:
                try:
                    record.action_delete_from_resellerclub()
                except Exception as e:
                    _logger.warning("Failed to delete DNS record from RC: %s", str(e))
        return super().unlink()

    def action_sync_to_resellerclub(self):
        """Sync this DNS record to ResellerClub."""
        self.ensure_one()

        if not self.domain_id.resellerclub_order_id:
            raise UserError(_("Domain must be registered in ResellerClub first."))

        api = self.env['resellerclub.api']

        try:
            api.dns_add_record(
                domain_name=self.domain_name,
                record_type=self.record_type,
                value=self.value,
                host=self.host,
                ttl=self.ttl,
                priority=self.priority if self.record_type in ['MX', 'SRV'] else None,
            )

            self.write({
                'is_synced': True,
                'sync_error': False,
            })

        except Exception as e:
            self.write({
                'is_synced': False,
                'sync_error': str(e),
            })
            raise

        return True

    def action_delete_from_resellerclub(self):
        """Delete this DNS record from ResellerClub."""
        self.ensure_one()

        if not self.domain_id.resellerclub_order_id:
            return True

        api = self.env['resellerclub.api']

        try:
            api.dns_delete_record(
                domain_name=self.domain_name,
                record_type=self.record_type,
                value=self.value,
                host=self.host,
            )
        except Exception as e:
            _logger.warning("Failed to delete DNS record: %s", str(e))

        return True

    @api.model
    def sync_records_from_resellerclub(self, domain):
        """
        Sync all DNS records from ResellerClub for a domain.

        :param domain: resellerclub.domain record
        """
        if not domain.resellerclub_order_id:
            raise UserError(_("Domain must be registered in ResellerClub first."))

        api = self.env['resellerclub.api']

        try:
            result = api.dns_get_records(domain_name=domain.domain_name)

            if isinstance(result, dict) and 'records' in result:
                # Delete existing records that aren't synced from RC
                domain.dns_record_ids.filtered(lambda r: not r.is_synced).unlink()

                for rc_record in result['records']:
                    existing = self.search([
                        ('domain_id', '=', domain.id),
                        ('record_type', '=', rc_record.get('type')),
                        ('host', '=', rc_record.get('host', '@')),
                        ('value', '=', rc_record.get('value')),
                    ], limit=1)

                    vals = {
                        'domain_id': domain.id,
                        'record_type': rc_record.get('type'),
                        'host': rc_record.get('host', '@'),
                        'value': rc_record.get('value'),
                        'ttl': int(rc_record.get('ttl', 14400)),
                        'priority': int(rc_record.get('priority', 10)),
                        'is_synced': True,
                    }

                    if existing:
                        existing.write(vals)
                    else:
                        self.create(vals)

        except Exception as e:
            raise UserError(_("Failed to sync DNS records: %s") % str(e))

        return True


class ResellerClubDNSTemplate(models.Model):
    """
    DNS template for quick setup of common configurations.
    """
    _name = 'resellerclub.dns.template'
    _description = 'DNS Template'
    _order = 'name'

    name = fields.Char(string='Template Name', required=True)
    description = fields.Text(string='Description')
    is_active = fields.Boolean(string='Active', default=True)

    record_ids = fields.One2many(
        'resellerclub.dns.template.record',
        'template_id',
        string='DNS Records'
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company
    )

    def action_apply_to_domain(self, domain):
        """
        Apply this template to a domain.

        :param domain: resellerclub.domain record
        """
        self.ensure_one()

        for template_record in self.record_ids:
            # Check if record already exists
            existing = self.env['resellerclub.dns.record'].search([
                ('domain_id', '=', domain.id),
                ('record_type', '=', template_record.record_type),
                ('host', '=', template_record.host),
            ], limit=1)

            vals = {
                'domain_id': domain.id,
                'record_type': template_record.record_type,
                'host': template_record.host,
                'value': template_record.value.replace('{domain}', domain.domain_name),
                'ttl': template_record.ttl,
                'priority': template_record.priority,
            }

            if existing:
                existing.write(vals)
            else:
                self.env['resellerclub.dns.record'].create(vals)

        return True


class ResellerClubDNSTemplateRecord(models.Model):
    """Template record for DNS templates."""
    _name = 'resellerclub.dns.template.record'
    _description = 'DNS Template Record'
    _order = 'record_type, host'

    template_id = fields.Many2one(
        'resellerclub.dns.template',
        string='Template',
        required=True,
        ondelete='cascade'
    )

    record_type = fields.Selection([
        ('A', 'A (IPv4 Address)'),
        ('AAAA', 'AAAA (IPv6 Address)'),
        ('CNAME', 'CNAME (Canonical Name)'),
        ('MX', 'MX (Mail Exchange)'),
        ('TXT', 'TXT (Text Record)'),
        ('NS', 'NS (Nameserver)'),
    ], string='Record Type', required=True, default='A')

    host = fields.Char(
        string='Host',
        required=True,
        default='@'
    )

    value = fields.Char(
        string='Value',
        required=True,
        help="Use {domain} as placeholder for the actual domain name"
    )

    ttl = fields.Integer(
        string='TTL',
        default=14400
    )

    priority = fields.Integer(
        string='Priority',
        default=10
    )

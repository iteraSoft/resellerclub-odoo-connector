# -*- coding: utf-8 -*-

import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # ResellerClub integration fields
    rc_customer_ids = fields.One2many(
        'resellerclub.customer',
        'partner_id',
        string='RC Customers'
    )

    rc_customer_id = fields.Many2one(
        'resellerclub.customer',
        string='RC Customer',
        compute='_compute_rc_customer',
        store=True
    )

    has_rc_account = fields.Boolean(
        string='Has RC Account',
        compute='_compute_has_rc_account',
        store=True
    )

    rc_domains_count = fields.Integer(
        string='Domains',
        compute='_compute_rc_counts'
    )

    rc_hosting_count = fields.Integer(
        string='Hosting',
        compute='_compute_rc_counts'
    )

    rc_ssl_count = fields.Integer(
        string='SSL Certs',
        compute='_compute_rc_counts'
    )

    rc_total_services = fields.Integer(
        string='Total Services',
        compute='_compute_rc_counts'
    )

    @api.depends('rc_customer_ids')
    def _compute_rc_customer(self):
        for partner in self:
            # Get RC customer for current company
            rc_customer = self.env['resellerclub.customer'].search([
                ('partner_id', '=', partner.id),
                ('company_id', '=', self.env.company.id),
            ], limit=1)
            partner.rc_customer_id = rc_customer

    @api.depends('rc_customer_ids')
    def _compute_has_rc_account(self):
        for partner in self:
            partner.has_rc_account = bool(partner.rc_customer_ids.filtered(
                lambda c: c.resellerclub_customer_id
            ))

    def _compute_rc_counts(self):
        for partner in self:
            rc_customer = partner.rc_customer_id
            if rc_customer:
                partner.rc_domains_count = len(rc_customer.domain_ids)
                partner.rc_hosting_count = len(rc_customer.hosting_ids)
                partner.rc_ssl_count = len(rc_customer.ssl_ids)
                partner.rc_total_services = (
                    partner.rc_domains_count +
                    partner.rc_hosting_count +
                    partner.rc_ssl_count
                )
            else:
                partner.rc_domains_count = 0
                partner.rc_hosting_count = 0
                partner.rc_ssl_count = 0
                partner.rc_total_services = 0

    def action_create_rc_customer(self):
        """Create a ResellerClub customer for this partner."""
        self.ensure_one()

        existing = self.env['resellerclub.customer'].search([
            ('partner_id', '=', self.id),
            ('company_id', '=', self.env.company.id),
        ], limit=1)

        if existing:
            if existing.resellerclub_customer_id:
                return {
                    'type': 'ir.actions.act_window',
                    'res_model': 'resellerclub.customer',
                    'res_id': existing.id,
                    'view_mode': 'form',
                }
            else:
                # Try to create in RC
                existing.action_create_in_resellerclub()
                return {
                    'type': 'ir.actions.act_window',
                    'res_model': 'resellerclub.customer',
                    'res_id': existing.id,
                    'view_mode': 'form',
                }

        rc_customer = self.env['resellerclub.customer'].create({
            'partner_id': self.id,
        })

        rc_customer.action_create_in_resellerclub()

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'resellerclub.customer',
            'res_id': rc_customer.id,
            'view_mode': 'form',
        }

    def action_view_rc_customer(self):
        """View the ResellerClub customer record."""
        self.ensure_one()

        if self.rc_customer_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'resellerclub.customer',
                'res_id': self.rc_customer_id.id,
                'view_mode': 'form',
            }
        else:
            return self.action_create_rc_customer()

    def action_view_rc_domains(self):
        """View domains for this partner."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Domains'),
            'res_model': 'resellerclub.domain',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
        }

    def action_view_rc_hosting(self):
        """View hosting services for this partner."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Hosting'),
            'res_model': 'resellerclub.hosting',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
        }

    def action_view_rc_ssl(self):
        """View SSL certificates for this partner."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('SSL Certificates'),
            'res_model': 'resellerclub.ssl',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
        }

    def action_view_all_rc_services(self):
        """Open a view showing all RC services for this partner."""
        self.ensure_one()

        if not self.rc_customer_id:
            return self.action_create_rc_customer()

        return {
            'type': 'ir.actions.act_window',
            'name': _('ResellerClub Services'),
            'res_model': 'resellerclub.customer',
            'res_id': self.rc_customer_id.id,
            'view_mode': 'form',
        }

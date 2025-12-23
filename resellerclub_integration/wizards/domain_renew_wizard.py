# -*- coding: utf-8 -*-

from datetime import datetime, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class DomainRenewWizard(models.TransientModel):
    """Wizard to renew domains."""
    _name = 'resellerclub.domain.renew.wizard'
    _description = 'Renew Domain Wizard'

    domain_id = fields.Many2one(
        'resellerclub.domain',
        string='Domain',
        required=True,
        readonly=True
    )

    domain_name = fields.Char(
        string='Domain Name',
        related='domain_id.domain_name',
        readonly=True
    )

    current_expiration = fields.Date(
        string='Current Expiration',
        related='domain_id.expiration_date',
        readonly=True
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
    ], string='Renewal Period', default='1', required=True)

    new_expiration = fields.Date(
        string='New Expiration',
        compute='_compute_new_expiration'
    )

    estimated_cost = fields.Float(
        string='Estimated Cost',
        compute='_compute_estimated_cost'
    )

    @api.depends('domain_id', 'years')
    def _compute_new_expiration(self):
        for wizard in self:
            if wizard.domain_id and wizard.domain_id.expiration_date:
                exp = wizard.domain_id.expiration_date
                new_exp = exp + timedelta(days=365 * int(wizard.years or 1))
                wizard.new_expiration = new_exp
            else:
                wizard.new_expiration = fields.Date.today() + timedelta(
                    days=365 * int(wizard.years or 1)
                )

    @api.depends('domain_id', 'years')
    def _compute_estimated_cost(self):
        for wizard in self:
            wizard.estimated_cost = 0.0

            if wizard.domain_id:
                tld = wizard.domain_id.tld
                product = self.env['product.template'].search([
                    ('is_resellerclub_product', '=', True),
                    ('rc_product_type', 'in', ['domain', 'domain_renewal']),
                    ('rc_tld', '=', tld),
                ], limit=1)

                if product:
                    wizard.estimated_cost = product.list_price * int(wizard.years or 1)

    def action_renew(self):
        """Renew the domain."""
        self.ensure_one()

        domain = self.domain_id
        if not domain.resellerclub_order_id:
            raise UserError(_("Domain must be registered in ResellerClub first."))

        api = self.env['resellerclub.api']

        try:
            exp_timestamp = int(datetime.combine(
                domain.expiration_date,
                datetime.min.time()
            ).timestamp()) if domain.expiration_date else 0

            result = api.domain_renew(
                order_id=domain.resellerclub_order_id,
                years=int(self.years),
                exp_date=exp_timestamp,
            )

            # Update domain
            domain.write({
                'expiration_date': self.new_expiration,
                'last_sync_date': fields.Datetime.now(),
            })

            domain.message_post(
                body=_("Domain renewed for %s year(s). New expiration: %s") % (
                    self.years, self.new_expiration
                ),
                message_type='notification'
            )

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Domain Renewed'),
                    'message': _('%s renewed until %s') % (
                        domain.domain_name, self.new_expiration
                    ),
                    'type': 'success',
                    'sticky': False,
                    'next': {
                        'type': 'ir.actions.act_window_close',
                    },
                }
            }

        except Exception as e:
            raise UserError(_("Renewal failed: %s") % str(e))

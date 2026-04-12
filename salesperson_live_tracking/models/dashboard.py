# models/salesperson_dashboard.py

from odoo import api, fields, models, _


class SalespersonDashboard(models.Model):
    _name = "sales.person.dashboard"
    _description = "Sales Person Dashboard"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string="Reference",
        required=True,
        default=lambda self: _('New')
    )
    sales_person = fields.Char(string="Sales Person", tracking=True)
    manager = fields.Char(string="Manager")

    partner_ids = fields.Many2many(
        'res.partner',
        string="Partners"
    )
    line_ids = fields.One2many(
        'sales.person.space.line',
        'dashboard_id',
        string="Visit Lines"
    )

    state = fields.Selection([
    ('planned',  'Planned'),
    ('visited',  'Visited'),
    ('accepted', 'Accepted'),
    ('rejected', 'Rejected'),
    ], string='Stage', default='planned', tracking=True, index=True)

    def action_set_visited(self):
      self.write({'state': 'visited'})

    def action_set_accepted(self):
        self.write({'state': 'accepted'})

    def action_set_rejected(self):
        self.write({'state': 'rejected'})

    def action_set_planned(self):
        self.write({'state': 'planned'})


class SalesPersonSpaceLine(models.Model):
    _name = "sales.person.space.line"
    _description = "Sales Person Space Line"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    dashboard_id = fields.Many2one(
        'sales.person.dashboard',
        string="Dashboard",
        ondelete="cascade"
    )

    plan_id = fields.Many2one(
        'salesperson.visit.plan',
        string="Plan",
        ondelete="set null"
    )

    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        required=True
    )
    visit_date = fields.Date(
        string="Visit Date",
        required=True
    )
    from_location = fields.Char(string="From")
    to_location = fields.Char(string="To")
    total_cost = fields.Char(string="Total Cost")
    notes = fields.Text(string="Notes")

  
    state = fields.Selection(
        related="plan_id.state",
        string="Status",
        store=True
    )
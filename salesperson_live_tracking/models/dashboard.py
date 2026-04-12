from odoo import api, fields, models, _

class SalespersonDashboard(models.Model):
    _name = "sales.person.dashboard"
    _description = "Sales Person Dashboard"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Reference", required=True, default=lambda self: _('New'))
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


class SalesPersonSpaceLine(models.Model):
    _name = "sales.person.space.line"
    _description = "Sales Person Space Line"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    dashboard_id = fields.Many2one(
        'sales.person.dashboard',
        string="Dashboard",
        ondelete="cascade"
    )

    partner_id = fields.Many2one(
        'res.partner',
        string="Partner",
        required=True,
        tracking=True
    )

    visit_date = fields.Datetime(
        string="Visit Date",
        default=fields.Datetime.now,
        tracking=True
    )

    location = fields.Char(
        string="Location"
    )

    latitude = fields.Float(string="Latitude")
    longitude = fields.Float(string="Longitude")

    status = fields.Selection([
        ('planned', 'Planned'),
        ('visited', 'Visited'),
        ('cancelled', 'Cancelled')
    ], default='planned', tracking=True)
    notes = fields.Text(string="Notes")
    is_successful = fields.Boolean(string="Successful Visit", default=False)
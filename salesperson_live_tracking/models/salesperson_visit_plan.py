
from collections import defaultdict
from datetime import datetime, time, timedelta
from math import asin, cos, radians, sin, sqrt
import pytz
from odoo import api, fields, models
from odoo.exceptions import ValidationError


def _haversine_distance_meters(lat1, lon1, lat2, lon2):
    radius = 6371000.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2.0) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2.0) ** 2
    return 2.0 * radius * asin(sqrt(a))

class SalespersonVisitPlan(models.Model):
    _name = "salesperson.visit.plan"
    _description = "Salesperson Planned Visit"
    _order = "visit_date desc, sequence, id"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(default="New", copy=False, tracking=True)
    date = fields.Date(default=fields.Date.today)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    space_line_ids = fields.One2many(
        "add.space.for.salesperson.line",
        "plan_id",
        string="Space Lines"
    )
    user_id = fields.Many2one("res.users", required=True,string="Salesperson" ,ondelete="cascade")
    company_id = fields.Many2one("res.company", related="user_id.company_id", store=True)
    sale_team_id = fields.Many2one("crm.team", related="user_id.sale_team_id", store=True)
    visit_date = fields.Date(required=True,tracking=True, default=fields.Date.context_today)
    partner_ids = fields.Many2many(
    comodel_name="res.partner",
    relation="salesperson_visit_plan_partner_rel",
    column1="plan_id",
    column2="partner_id",
    string="Customers",
     )
    location_name = fields.Char(default="New Location")
    manual_latitude = fields.Float(digits=(16, 7))
    manual_longitude = fields.Float(digits=(16, 7))
    latitude = fields.Float(store=True, digits=(16, 7))
    longitude = fields.Float(store=True, digits=(16, 7))
    radius_meters = fields.Float(default=100.0)
    is_covered = fields.Boolean()
    first_arrival = fields.Datetime()
    last_departure = fields.Datetime()
    stay_duration_minutes = fields.Float()
    stay_duration_display = fields.Char()
    openstreetmap_url = fields.Char()
    manager_notes = fields.Text()
    priority = fields.Selection([
        ("0", "Normal"),
        ("1", "High"),
        ("2", "Urgent")
    ], default="0")
    coverage_color = fields.Integer(compute="_compute_coverage_color")
    state = fields.Selection([
        ("draft", "Draft"),
        ("submitted", "Submitted"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("done", "Done")
    ], default="draft", tracking=True)
    html_note = fields.Html(string="HTML Note", sanitize=True)
    is_manager = fields.Boolean("res.users",
    related="user_id.is_manager",
    store=False
     )
    
    def _compute_coverage_color(self):
        for rec in self:
            rec.coverage_color = 10 if rec.is_covered else 1

    def _push_to_dashboard(self):
        Dashboard = self.env["salesperson.tracker"]
        Line = self.env["sales.person.space.line"]

        for rec in self:
            
            dashboard = Dashboard.search([
                ("sales_person", "=", rec.user_id.name)
            ], limit=1)

            if not dashboard:
                dashboard = Dashboard.create({
                    "sales_person": rec.user_id.name,
                    "manager": rec.user_id.parent_id.name if rec.user_id.parent_id else False,
                })

            for space_line in rec.space_line_ids:
                existing_line = Line.search([
                    ("partner_id", "=", space_line.partner_id.id),
                    ("visit_date", "=", space_line.visit_date),
                ], limit=1)

                if not existing_line:
                    Line.create({
                        "plan_id": rec.id,
                        "partner_id": space_line.partner_id.id,
                        "visit_date": space_line.visit_date,
                        "from_location": space_line.from_location,
                        "to_location": space_line.to_location,
                        "total_cost": space_line.total_cost,
                        "notes": space_line.notes or "",
                    })


    def action_submit(self):
        for rec in self:
            rec.state = "submitted"
    def action_approve(self):
        for rec in self:
            rec.state = "approved"
            rec._push_to_dashboard()

    def action_reject(self):
        for rec in self:
            rec.state = "rejected"

    def action_done(self):
        for rec in self:
            rec.state = "done"

    def action_reset_draft(self):
        for rec in self:
            rec.state = "draft"

   
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                today_str = datetime.today().strftime("%d-%m-%Y")
                last = self.search([], order="id desc", limit=1)
                next_seq = 1
                if last:
                    try:
                        next_seq = int(last.name.split("-")[-1]) + 1
                    except Exception:
                        next_seq = 1
                vals["name"] = f"{today_str}-{str(next_seq).zfill(5)}"
        return super().create(vals_list)



class AddSpaceForSalespersonLine(models.Model):
    _name = "add.space.for.salesperson.line"
    _description = "Space Line for Salesperson Visit Plan"

    plan_id = fields.Many2one(
        "salesperson.visit.plan",
        string="Visit Plan",
        required=True,
        ondelete="cascade"
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
    sequence = fields.Integer(default=10)
    from_location = fields.Char(string="From")
    to_location = fields.Char(string="To")
    total_cost = fields.Char(string="Total Cost")
    notes = fields.Text(string="Notes")

    state = fields.Selection(
        related="plan_id.state",
        string="Status",
        store=True
    )

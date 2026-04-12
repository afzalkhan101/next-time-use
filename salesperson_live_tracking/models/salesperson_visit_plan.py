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

    user_id = fields.Many2one("res.users", required=True, ondelete="cascade")
    company_id = fields.Many2one("res.company", related="user_id.company_id", store=True)
    sale_team_id = fields.Many2one("crm.team", related="user_id.sale_team_id", store=True)

    visit_date = fields.Date(required=True, default=fields.Date.context_today)

    partner_id = fields.Many2one("res.partner")
    location_name = fields.Char(default="New Location")

    manual_latitude = fields.Float(digits=(16, 7))
    manual_longitude = fields.Float(digits=(16, 7))

    latitude = fields.Float(compute="_compute_coordinates", store=True, digits=(16, 7))
    longitude = fields.Float(compute="_compute_coordinates", store=True, digits=(16, 7))

    radius_meters = fields.Float(default=100.0)

    is_covered = fields.Boolean(compute="_compute_visit_metrics",store=True)
    first_arrival = fields.Datetime(compute="_compute_visit_metrics")
    last_departure = fields.Datetime(compute="_compute_visit_metrics")
    stay_duration_minutes = fields.Float(compute="_compute_visit_metrics")
    stay_duration_display = fields.Char(compute="_compute_visit_metrics")

    openstreetmap_url = fields.Char(compute="_compute_map_url")

    manager_notes = fields.Text()
    priority = fields.Selection([
        ("0", "Normal"),
        ("1", "High"),
        ("2", "Urgent")
    ], default="0")

    coverage_color = fields.Integer(compute="_compute_coverage_color")


    def _push_to_dashboard(self):
        Dashboard = self.env["sales.person.dashboard"]
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

            existing_line = Line.search([
                ("dashboard_id", "=", dashboard.id),
                ("partner_id", "=", rec.partner_id.id),
                ("visit_date", "=", rec.visit_date)
            ], limit=1)

            if not existing_line:
                Line.create({
                    "dashboard_id": dashboard.id,
                    "partner_id": rec.partner_id.id,
                    "visit_date": rec.visit_date,
                    "location": rec.location_name,
                    "latitude": rec.latitude,
                    "longitude": rec.longitude,
                    "status": "visited" if rec.is_covered else "planned",
                    "notes": rec.manager_notes or "",
                    "is_successful": rec.is_covered,
                })

    state = fields.Selection([
        ("draft", "Draft"),
        ("submitted", "Submitted"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("done", "Done")
    ], default="draft", tracking=True)

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
                    except:
                        next_seq = 1
                vals["name"] = f"M/D/{today_str}-{str(next_seq).zfill(5)}"

        return super().create(vals_list)


    @api.depends("partner_id", "manual_latitude", "manual_longitude")
    def _compute_coordinates(self):
        for rec in self:
            if rec.partner_id and (rec.partner_id.partner_latitude or rec.partner_id.partner_longitude):
                rec.latitude = rec.partner_id.partner_latitude
                rec.longitude = rec.partner_id.partner_longitude
            else:
                rec.latitude = rec.manual_latitude
                rec.longitude = rec.manual_longitude

    @api.depends("latitude", "longitude")
    def _compute_map_url(self):
        for rec in self:
            if rec.latitude and rec.longitude:
                rec.openstreetmap_url = f"https://www.openstreetmap.org/?mlat={rec.latitude}&mlon={rec.longitude}#map=16/{rec.latitude}/{rec.longitude}"
            else:
                rec.openstreetmap_url = False



    @api.depends("user_id", "visit_date", "latitude", "longitude", "radius_meters")
    def _compute_visit_metrics(self):

        log_model = self.env["salesperson.location.log"].sudo()
        grouped = defaultdict(lambda: self.env["salesperson.visit.plan"])

        for rec in self:
            rec.is_covered = False
            rec.first_arrival = False
            rec.last_departure = False
            rec.stay_duration_minutes = 0
            rec.stay_duration_display = "0m"

            if rec.user_id and rec.visit_date and rec.latitude and rec.longitude:
                grouped[(rec.user_id.id, rec.visit_date)] |= rec

        for (user_id, visit_date), plans in grouped.items():

            start, end = plans._get_day_bounds(visit_date, plans[0].user_id)

            logs = log_model.search([
                ("user_id", "=", user_id),
                ("tracked_at", ">=", start),
                ("tracked_at", "<", end),
            ], order="tracked_at asc")

            plan_logs = {p.id: [] for p in plans}

            for log in logs:
                best_plan = None
                best_dist = 999999

                for plan in plans:
                    dist = _haversine_distance_meters(
                        plan.latitude, plan.longitude,
                        log.latitude, log.longitude
                    )

                    if dist <= plan.radius_meters and dist < best_dist:
                        best_plan = plan
                        best_dist = dist

                if best_plan:
                    plan_logs[best_plan.id].append(log)

            for plan in plans:
                assigned = plan_logs.get(plan.id, [])

                if not assigned:
                    continue

                plan.is_covered = True
                plan.first_arrival = assigned[0].tracked_at
                plan.last_departure = assigned[-1].tracked_at

                total = timedelta(0)
                start_t = assigned[0].tracked_at
                prev = assigned[0].tracked_at

                for log in assigned[1:]:
                    if log.tracked_at - prev > timedelta(minutes=30):
                        total += max(prev - start_t, timedelta(minutes=1))
                        start_t = log.tracked_at
                    prev = log.tracked_at

                total += max(prev - start_t, timedelta(minutes=1))

                plan.stay_duration_minutes = total.total_seconds() / 60.0
                plan.stay_duration_display = plan._format_duration(plan.stay_duration_minutes)


    @api.model
    def _format_duration(self, minutes):
        m = int(round(minutes))
        h, m = divmod(m, 60)
        return f"{h}h {m}m" if h else f"{m}m"

    @api.model
    def _get_day_bounds(self, target_date, user):
        tz = pytz.timezone(user.tz or "UTC")
        start_local = tz.localize(datetime.combine(target_date, time.min))
        end_local = start_local + timedelta(days=1)

        return (
            start_local.astimezone(pytz.UTC).replace(tzinfo=None),
            end_local.astimezone(pytz.UTC).replace(tzinfo=None),
        )


    @api.constrains("latitude", "longitude", "radius_meters")
    def _check_coords(self):
        for rec in self:
            if not (rec.latitude or rec.longitude):
                raise ValidationError("Coordinates are required.")
            if rec.radius_meters <= 0:
                raise ValidationError("Radius must be greater than 0.")

    @api.depends("is_covered")
    def _compute_coverage_color(self):
        for rec in self:
            rec.coverage_color = 10 if rec.is_covered else 1
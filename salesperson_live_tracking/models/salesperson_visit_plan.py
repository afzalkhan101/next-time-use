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

    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    user_id = fields.Many2one("res.users", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one("res.company", related="user_id.company_id", store=True, readonly=True)
    sale_team_id = fields.Many2one("crm.team", related="user_id.sale_team_id", store=True, readonly=True)
    visit_date = fields.Date(required=True, default=fields.Date.context_today, index=True)
    partner_id = fields.Many2one("res.partner", string="Location Partner")
    location_name = fields.Char(required=True, default="New Location")
    manual_latitude = fields.Float(string="Manual Latitude", digits=(16, 7))
    manual_longitude = fields.Float(string="Manual Longitude", digits=(16, 7))
    latitude = fields.Float(compute="_compute_coordinates", digits=(16, 7), store=True)
    longitude = fields.Float(compute="_compute_coordinates", digits=(16, 7), store=True)
    radius_meters = fields.Float(string="Visit Radius (m)", default=100.0, digits=(16, 2))
    is_covered = fields.Boolean(compute="_compute_visit_metrics", search="_search_is_covered")
    first_arrival = fields.Datetime(compute="_compute_visit_metrics")
    last_departure = fields.Datetime(compute="_compute_visit_metrics")
    stay_duration_minutes = fields.Float(compute="_compute_visit_metrics", digits=(16, 2))
    stay_duration_display = fields.Char(compute="_compute_visit_metrics")
    openstreetmap_url = fields.Char(compute="_compute_map_url")

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        for plan in self:
            if plan.partner_id and (not plan.location_name or plan.location_name == "New Location"):
                plan.location_name = plan.partner_id.display_name

    @api.depends("partner_id.partner_latitude", "partner_id.partner_longitude", "manual_latitude", "manual_longitude")
    def _compute_coordinates(self):
        for plan in self:
            if plan.partner_id and (plan.partner_id.partner_latitude or plan.partner_id.partner_longitude):
                plan.latitude = plan.partner_id.partner_latitude
                plan.longitude = plan.partner_id.partner_longitude
            else:
                plan.latitude = plan.manual_latitude
                plan.longitude = plan.manual_longitude

    @api.depends("latitude", "longitude")
    def _compute_map_url(self):
        for plan in self:
            if plan.latitude or plan.longitude:
                plan.openstreetmap_url = "https://www.openstreetmap.org/?mlat=%s&mlon=%s#map=16/%s/%s" % (
                    plan.latitude,
                    plan.longitude,
                    plan.latitude,
                    plan.longitude,
                )
            else:
                plan.openstreetmap_url = False

    @api.depends("user_id", "visit_date", "latitude", "longitude", "radius_meters")
    def _compute_visit_metrics(self):
        grouped_plans = defaultdict(lambda: self.env["salesperson.visit.plan"])
        for plan in self:
            plan.is_covered = False
            plan.first_arrival = False
            plan.last_departure = False
            plan.stay_duration_minutes = 0.0
            plan.stay_duration_display = "0m"
            if plan.user_id and plan.visit_date and (plan.latitude or plan.longitude):
                grouped_plans[(plan.user_id.id, plan.visit_date)] |= plan

        location_log_model = self.env["salesperson.location.log"].sudo()
        max_tracking_gap = timedelta(minutes=30)

        for (user_id, visit_date), plans in grouped_plans.items():
            date_start, date_end = plans._get_day_bounds(visit_date, plans[0].user_id)
            logs = location_log_model.search(
                [
                    ("user_id", "=", user_id),
                    ("tracked_at", ">=", fields.Datetime.to_string(date_start)),
                    ("tracked_at", "<", fields.Datetime.to_string(date_end)),
                ],
                order="tracked_at asc, id asc",
            )
            plan_logs = {plan.id: [] for plan in plans}
            for log in logs:
                matched_plan = None
                matched_distance = None
                for plan in plans:
                    if not (plan.latitude or plan.longitude):
                        continue
                    distance = _haversine_distance_meters(plan.latitude, plan.longitude, log.latitude, log.longitude)
                    if distance <= plan.radius_meters and (matched_distance is None or distance < matched_distance):
                        matched_plan = plan
                        matched_distance = distance
                if matched_plan:
                    plan_logs[matched_plan.id].append(log)

            for plan in plans:
                assigned_logs = plan_logs.get(plan.id) or []
                if not assigned_logs:
                    continue
                plan.is_covered = True
                plan.first_arrival = assigned_logs[0].tracked_at
                plan.last_departure = assigned_logs[-1].tracked_at
                total_duration = timedelta(0)
                segment_start = assigned_logs[0].tracked_at
                previous_time = assigned_logs[0].tracked_at
                for log in assigned_logs[1:]:
                    if log.tracked_at - previous_time > max_tracking_gap:
                        total_duration += max(previous_time - segment_start, timedelta(minutes=1))
                        segment_start = log.tracked_at
                    previous_time = log.tracked_at
                total_duration += max(previous_time - segment_start, timedelta(minutes=1))
                plan.stay_duration_minutes = total_duration.total_seconds() / 60.0
                plan.stay_duration_display = plan._format_duration(plan.stay_duration_minutes)

    def _search_is_covered(self, operator, value):
        if operator not in ("=", "!=") or value not in (True, False):
            return []
        matching_ids = self.search([]).filtered(lambda plan: plan.is_covered).ids
        domain = [("id", "in", matching_ids)]
        if (operator == "=" and not value) or (operator == "!=" and value):
            domain = [("id", "not in", matching_ids)]
        return domain

    @api.model
    def _format_duration(self, duration_minutes):
        total_minutes = int(round(duration_minutes))
        hours, minutes = divmod(total_minutes, 60)
        if hours:
            return "%sh %sm" % (hours, minutes)
        return "%sm" % minutes

    @api.model
    def _get_day_bounds(self, target_date, user):
        user_tz = pytz.timezone(user.tz or self.env.user.tz or "UTC")
        start_local = user_tz.localize(datetime.combine(target_date, time.min))
        end_local = start_local + timedelta(days=1)
        start_utc = start_local.astimezone(pytz.UTC).replace(tzinfo=None)
        end_utc = end_local.astimezone(pytz.UTC).replace(tzinfo=None)
        return start_utc, end_utc

    @api.constrains("latitude", "longitude", "radius_meters")
    def _check_visit_plan_coordinates(self):
        for plan in self:
            if not (plan.latitude or plan.longitude):
                raise ValidationError("Planned visit coordinates are required.")
            if plan.radius_meters <= 0:
                raise ValidationError("Visit radius must be greater than zero.")

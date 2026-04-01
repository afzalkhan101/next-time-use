from collections import defaultdict
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

import requests
from requests.exceptions import RequestException


class SalespersonTracker(models.Model):
    _name = "salesperson.tracker"
    _description = "Salesperson Live Tracker"
    _order = "last_seen desc, id desc"

    _MAX_PRECISE_LOCATION_ACCURACY_METERS = 200.0

    user_id = fields.Many2one("res.users", required=True, ondelete="cascade", index=True)
    partner_id = fields.Many2one("res.partner", related="user_id.partner_id", store=True, readonly=True)
    company_id = fields.Many2one("res.company", related="user_id.company_id", store=True, readonly=True)
    sale_team_id = fields.Many2one("crm.team", related="user_id.sale_team_id", store=True, readonly=True)
    is_tracking = fields.Boolean(string="Tracking Active", default=False)
    last_seen = fields.Datetime(string="Last Update", index=True)
    last_accuracy = fields.Float(string="Accuracy (m)", digits=(16, 2))
    last_speed = fields.Float(string="Speed (m/s)", digits=(16, 2))
    last_heading = fields.Float(string="Heading", digits=(16, 2))
    tracking_status = fields.Selection(
        [
            ("live", "Live"),
            ("idle", "Idle"),
            ("offline", "Offline"),
        ],
        compute="_compute_tracking_status",
        search="_search_tracking_status",
    )
    tracking_status_label = fields.Char(compute="_compute_tracking_status")
    openstreetmap_url = fields.Char(compute="_compute_map_links")
    latitude = fields.Float(related="partner_id.partner_latitude", readonly=True, digits=(16, 7))
    longitude = fields.Float(related="partner_id.partner_longitude", readonly=True, digits=(16, 7))
    location_name = fields.Char(string="Current Location")
    history_count = fields.Integer(compute="_compute_history_count")
    today_plan_count = fields.Integer(compute="_compute_today_visit_stats")
    today_covered_count = fields.Integer(compute="_compute_today_visit_stats")
    today_visit_summary = fields.Text(compute="_compute_today_visit_stats")

    _sql_constraints = [
        ("salesperson_tracker_user_unique", "unique(user_id)", "A salesperson can only have one live tracker."),
    ]

    @api.depends("last_seen", "is_tracking")
    def _compute_tracking_status(self):
        now = fields.Datetime.now()
        for tracker in self:
            status = "offline"
            if tracker.last_seen:
                if tracker.is_tracking and tracker.last_seen >= now - timedelta(minutes=2):
                    status = "live"
                elif tracker.last_seen >= now - timedelta(minutes=30):
                    status = "idle"
            tracker.tracking_status = status
            tracker.tracking_status_label = dict(self._fields["tracking_status"].selection).get(status)

    def _search_tracking_status(self, operator, value):
        now = fields.Datetime.now()
        live_domain = [
            ("is_tracking", "=", True),
            ("last_seen", ">=", fields.Datetime.to_string(now - timedelta(minutes=2))),
        ]
        idle_domain = [
            "&",
            ("last_seen", ">=", fields.Datetime.to_string(now - timedelta(minutes=30))),
            "|",
            ("is_tracking", "=", False),
            ("last_seen", "<", fields.Datetime.to_string(now - timedelta(minutes=2))),
        ]
        offline_domain = [
            "|",
            ("last_seen", "=", False),
            ("last_seen", "<", fields.Datetime.to_string(now - timedelta(minutes=30))),
        ]
        mapping = {
            "live": live_domain,
            "idle": idle_domain,
            "offline": offline_domain,
        }
        if operator != "=" or value not in mapping:
            return []
        return mapping[value]

    @api.depends("partner_id.partner_latitude", "partner_id.partner_longitude")
    def _compute_map_links(self):
        for tracker in self:
            if tracker.partner_id.partner_latitude or tracker.partner_id.partner_longitude:
                tracker.openstreetmap_url = (
                    "https://www.openstreetmap.org/?mlat=%s&mlon=%s#map=16/%s/%s"
                    % (
                        tracker.partner_id.partner_latitude,
                        tracker.partner_id.partner_longitude,
                        tracker.partner_id.partner_latitude,
                        tracker.partner_id.partner_longitude,
                    )
                )
            else:
                tracker.openstreetmap_url = False

    @api.depends("user_id")
    def _compute_history_count(self):
        counts = self.env["salesperson.location.log"].read_group(
            [("tracker_id", "in", self.ids)],
            ["tracker_id"],
            ["tracker_id"],
        )
        mapped_counts = {item["tracker_id"][0]: item["tracker_id_count"] for item in counts}
        for tracker in self:
            tracker.history_count = mapped_counts.get(tracker.id, 0)

    @api.depends("user_id")
    def _compute_today_visit_stats(self):
        plan_model = self.env["salesperson.visit.plan"]
        today = fields.Date.context_today(self)
        grouped = defaultdict(list)
        for tracker in self:
            tracker.today_plan_count = 0
            tracker.today_covered_count = 0
            tracker.today_visit_summary = False
            if tracker.user_id:
                grouped[tracker.user_id.id].append(tracker)

        if not grouped:
            return

        plans = plan_model.search([("user_id", "in", list(grouped.keys())), ("visit_date", "=", today)], order="sequence, id")
        plans_by_user = defaultdict(lambda: plan_model)
        for plan in plans:
            plans_by_user[plan.user_id.id] |= plan

        for user_id, trackers in grouped.items():
            user_plans = plans_by_user[user_id]
            covered_count = len(user_plans.filtered("is_covered"))
            summary = "\n".join(
                "%s: %s" % (plan.location_name, plan.stay_duration_display)
                for plan in user_plans
            )
            for tracker in trackers:
                tracker.today_plan_count = len(user_plans)
                tracker.today_covered_count = covered_count
                tracker.today_visit_summary = summary or False

    def update_live_location(self, latitude, longitude, accuracy=None, speed=None, heading=None, source="browser"):
        self.ensure_one()
        accuracy_value = accuracy or 0.0
        location_name = self.location_name
        if not accuracy_value or accuracy_value <= self._MAX_PRECISE_LOCATION_ACCURACY_METERS:
            location_name = self._reverse_geocode_location(latitude, longitude) or self.location_name
        values = {
            "is_tracking": True,
            "last_seen": fields.Datetime.now(),
            "last_accuracy": accuracy_value,
            "last_speed": speed or 0.0,
            "last_heading": heading or 0.0,
            "location_name": location_name,
        }
        self.write(values)
        if self.partner_id:
            self.partner_id.sudo().write({
                "partner_latitude": latitude,
                "partner_longitude": longitude,
                "date_localization": fields.Date.context_today(self),
            })
        self.env["salesperson.location.log"].sudo().create({
            "tracker_id": self.id,
            "tracked_at": fields.Datetime.now(),
            "latitude": latitude,
            "longitude": longitude,
            "accuracy": accuracy_value,
            "speed": speed or 0.0,
            "heading": heading or 0.0,
            "source": source,
            "location_name": location_name,
        })

    def _reverse_geocode_location(self, latitude, longitude):
        self.ensure_one()
        try:
            response = requests.get(
                "https://nominatim.openstreetmap.org/reverse",
                headers={"User-Agent": "Odoo (http://www.odoo.com/contactus)"},
                params={
                    "format": "jsonv2",
                    "lat": latitude,
                    "lon": longitude,
                    "zoom": 18,
                    "addressdetails": 1,
                    "accept-language": "en",
                },
                timeout=10,
            )
            response.raise_for_status()
            result = response.json()
            detailed_location = self._format_reverse_geocode_result(result)
            if detailed_location:
                return detailed_location
        except (UserError, RequestException):
            pass
        try:
            return self.env["base.geocoder"].sudo()._get_localisation(latitude, longitude)
        except (UserError, RequestException):
            return False

    def _format_reverse_geocode_result(self, result):
        address = result.get("address") or {}
        area = (
            address.get("city_district")
            or address.get("suburb")
            or address.get("quarter")
            or address.get("neighbourhood")
            or address.get("residential")
            or address.get("hamlet")
        )
        area = self._clean_location_area(area)
        city = address.get("city") or address.get("town") or address.get("municipality") or address.get("village")
        postcode = address.get("postcode")
        parts = []
        if area:
            parts.append(area)
        city_postcode = " ".join(part for part in (city, postcode) if part)
        if city_postcode:
            parts.append(city_postcode)
        if not parts and result.get("display_name"):
            display_name = result["display_name"].split(",")
            fallback_parts = [part.strip() for part in display_name if part.strip()]
            if len(fallback_parts) >= 3:
                parts = [fallback_parts[1], fallback_parts[2]]
            else:
                parts = fallback_parts[:2]
        return ", ".join(parts)

    def _clean_location_area(self, area):
        if not area:
            return area
        lowered_area = area.lower()
        generic_tokens = ("housing", "residential", "apartment", "building", "tower")
        if any(token in lowered_area for token in generic_tokens):
            return False
        return area

    def action_view_history(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Location History"),
            "res_model": "salesperson.location.log",
            "view_mode": "list,form",
            "domain": [("tracker_id", "=", self.id)],
            "context": {
                "default_tracker_id": self.id,
                "search_default_today": 1,
            },
        }

    def action_open_moving_map_view(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": "/salesperson_tracking/moving_map/%d" % self.id,
            "target": "new",
        }

    def action_open_live_tracking_page(self):
        self.ensure_one()
        return self.user_id.action_open_live_tracking_page()

    def action_view_today_visit_plan(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        action = self.env.ref("salesperson_live_tracking.action_salesperson_visit_plan").read()[0]
        action["domain"] = [("user_id", "=", self.user_id.id), ("visit_date", "=", today)]
        action["context"] = {
            "default_user_id": self.user_id.id,
            "default_visit_date": today,
            "search_default_today": 1,
        }
        return action


class SalespersonLocationLog(models.Model):
    _name = "salesperson.location.log"
    _description = "Salesperson Location History"
    _order = "tracked_at desc, id desc"

    tracker_id = fields.Many2one("salesperson.tracker", required=True, ondelete="cascade", index=True)
    user_id = fields.Many2one("res.users", related="tracker_id.user_id", store=True, readonly=True, index=True)
    partner_id = fields.Many2one("res.partner", related="tracker_id.partner_id", store=True, readonly=True, index=True)
    company_id = fields.Many2one("res.company", related="tracker_id.company_id", store=True, readonly=True)
    tracked_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    latitude = fields.Float(required=True, digits=(16, 7))
    longitude = fields.Float(required=True, digits=(16, 7))
    accuracy = fields.Float(string="Accuracy (m)", digits=(16, 2))
    speed = fields.Float(string="Speed (m/s)", digits=(16, 2))
    heading = fields.Float(string="Heading", digits=(16, 2))
    source = fields.Char(default="browser")
    location_name = fields.Char(string="Location")
    openstreetmap_url = fields.Char(compute="_compute_map_url")

    @api.depends("latitude", "longitude")
    def _compute_map_url(self):
        for log in self:
            if log.latitude or log.longitude:
                log.openstreetmap_url = "https://www.openstreetmap.org/?mlat=%s&mlon=%s#map=16/%s/%s" % (
                    log.latitude,
                    log.longitude,
                    log.latitude,
                    log.longitude,
                )
            else:
                log.openstreetmap_url = False

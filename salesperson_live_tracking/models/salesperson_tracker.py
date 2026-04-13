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
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _MAX_PRECISE_LOCATION_ACCURACY_METERS = 200.0
    _rec_name = "user_id"

    sales_person = fields.Char(string="Sales Person", tracking=True)
    manager = fields.Char(string="Manager")

    partner_ids = fields.Many2many(
        'res.partner',
        string="Partners",
    )
    line_ids = fields.One2many(
        'sales.person.space.line',
        'salesperson_tracker_id',      
        string="Visit Lines",
    )
    state = fields.Selection([
        ('planned',  'Planned'),
        ('visited',  'Visited'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
    ], string='Stage', default='planned', tracking=True, index=True)
    user_id    = fields.Many2one("res.users",   required=True, ondelete="cascade", index=True)
    partner_id = fields.Many2one("res.partner", related="user_id.partner_id",  store=True, readonly=True)
    company_id = fields.Many2one("res.company", related="user_id.company_id",  store=True, readonly=True)
    sale_team_id = fields.Many2one("crm.team",  related="user_id.sale_team_id", store=True, readonly=True)
    is_tracking   = fields.Boolean(string="Tracking Active", default=False, tracking=True)
    last_seen     = fields.Datetime(string="Last Update", index=True)
    last_accuracy = fields.Float(string="Accuracy (m)",  digits=(16, 2), tracking=True)
    last_speed    = fields.Float(string="Speed (m/s)",   digits=(16, 2), tracking=True)
    last_heading  = fields.Float(string="Heading",       digits=(16, 2), tracking=True)
    tracking_status = fields.Selection(
        [("live", "Live"), ("idle", "Idle"), ("offline", "Offline")],
        compute="_compute_tracking_status",
        search="_search_tracking_status",
        tracking=True,
    )
    tracking_status_label = fields.Char(compute="_compute_tracking_status")
    openstreetmap_url     = fields.Char(compute="_compute_map_links")
    latitude      = fields.Float(related="partner_id.partner_latitude",  readonly=True, digits=(16, 7))
    longitude     = fields.Float(related="partner_id.partner_longitude", readonly=True, digits=(16, 7))
    location_name = fields.Char(string="Current Location")
    history_count             = fields.Integer(compute="_compute_history_count")
    today_plan_count          = fields.Integer(compute="_compute_today_visit_stats")
    today_covered_count       = fields.Integer(compute="_compute_today_visit_stats")
    today_visit_summary       = fields.Text(compute="_compute_today_visit_stats")
    kpi_visit_completion_rate = fields.Float(
        string="Visit Completion Rate (%)",
        compute="_compute_today_visit_stats",
        digits=(16, 2),
    )
    is_manager = fields.Boolean("res.users",
    related="user_id.is_manager",
    store=False
   )

    last_tracking_start    = fields.Datetime(string="Tracking Started At")
    last_tracking_duration = fields.Integer(string="Last Session Duration (sec)", default=0)
    route_deviation_alert  = fields.Boolean(string="Route Deviation Alert", default=False)
    last_alert_sent        = fields.Datetime(string="Last Alert Sent")


    def action_set_planned(self):
        self.write({'state': 'planned'})

    def action_set_visited(self):
        self.write({'state': 'visited'})

    def action_set_accepted(self):
        self.write({'state': 'accepted'})

    def action_set_rejected(self):
        self.write({'state': 'rejected'})

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
            tracker.tracking_status_label = (
                dict(self._fields["tracking_status"].selection).get(status)
            )

    def _search_tracking_status(self, operator, value):
        now = fields.Datetime.now()
        live_cutoff    = fields.Datetime.to_string(now - timedelta(minutes=2))
        idle_cutoff    = fields.Datetime.to_string(now - timedelta(minutes=30))

        mapping = {
            "live": [
                ("is_tracking", "=", True),
                ("last_seen", ">=", live_cutoff),
            ],
            "idle": [
                "&",
                ("last_seen", ">=", idle_cutoff),
                "|",
                ("is_tracking", "=", False),
                ("last_seen", "<", live_cutoff),
            ],
            "offline": [
                "|",
                ("last_seen", "=", False),
                ("last_seen", "<", idle_cutoff),
            ],
        }
        if operator != "=" or value not in mapping:
            return []
        return mapping[value]

    @api.depends("partner_id.partner_latitude", "partner_id.partner_longitude")
    def _compute_map_links(self):
        for tracker in self:
            lat = tracker.partner_id.partner_latitude
            lon = tracker.partner_id.partner_longitude
            if lat or lon:
                tracker.openstreetmap_url = (
                    "https://www.openstreetmap.org/?mlat=%s&mlon=%s#map=16/%s/%s"
                    % (lat, lon, lat, lon)
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
        mapped = {item["tracker_id"][0]: item["tracker_id_count"] for item in counts}
        for tracker in self:
            tracker.history_count = mapped.get(tracker.id, 0)

    @api.depends("user_id")
    def _compute_today_visit_stats(self):
        plan_model = self.env["salesperson.visit.plan"]
        today = fields.Date.context_today(self)
        grouped = defaultdict(list)

        for tracker in self:
            tracker.today_plan_count = 0
            tracker.today_covered_count = 0
            tracker.today_visit_summary = False
            tracker.kpi_visit_completion_rate = 0.0
            if tracker.user_id:
                grouped[tracker.user_id.id].append(tracker)

        if not grouped:
            return

        plans = plan_model.search(
            [("user_id", "in", list(grouped.keys())), ("visit_date", "=", today)],
            order="sequence, id",
        )
        plans_by_user = defaultdict(lambda: plan_model)
        for plan in plans:
            plans_by_user[plan.user_id.id] |= plan

        for user_id, trackers in grouped.items():
            user_plans     = plans_by_user[user_id]
            covered_count  = len(user_plans.filtered("is_covered"))
            total          = len(user_plans)
            completion_rate = (covered_count / total * 100.0) if total else 0.0
            summary = "\n".join(
                "%s: %s" % (p.location_name, p.stay_duration_display) for p in user_plans
            )
            for tracker in trackers:
                tracker.today_plan_count          = total
                tracker.today_covered_count       = covered_count
                tracker.today_visit_summary       = summary or False
                tracker.kpi_visit_completion_rate = completion_rate
                
    def update_live_location(
        self, latitude, longitude,
        accuracy=None, speed=None, heading=None, source="browser"
    ):
        self.ensure_one()
        accuracy_value = accuracy or 0.0
        location_name  = self.location_name

        if not accuracy_value or accuracy_value <= self._MAX_PRECISE_LOCATION_ACCURACY_METERS:
            location_name = (
                self._reverse_geocode_location(latitude, longitude) or self.location_name
            )

        self.write({
            "is_tracking":  True,
            "last_seen":    fields.Datetime.now(),
            "last_accuracy": accuracy_value,
            "last_speed":   speed or 0.0,
            "last_heading": heading or 0.0,
            "location_name": location_name,
        })

        if self.partner_id:
            self.partner_id.sudo().write({
                "partner_latitude":  latitude,
                "partner_longitude": longitude,
                "date_localization": fields.Date.context_today(self),
            })

        self.env["salesperson.location.log"].sudo().create({
            "tracker_id":    self.id,
            "tracked_at":    fields.Datetime.now(),
            "latitude":      latitude,
            "longitude":     longitude,
            "accuracy":      accuracy_value,
            "speed":         speed or 0.0,
            "heading":       heading or 0.0,
            "source":        source,
            "location_name": location_name,
        })
        self._check_route_deviation(latitude, longitude)

    

    def _check_route_deviation(self, latitude, longitude):
        self.ensure_one()
        today = fields.Date.context_today(self)
        plans = self.env["salesperson.visit.plan"].sudo().search([
            ("user_id",    "=", self.user_id.id),
            ("visit_date", "=", today),
            ("is_covered", "=", False),
        ])
        if not plans:
            return

        from math import asin, cos, radians, sin, sqrt

        def haversine(lat1, lon1, lat2, lon2):
            R = 6_371_000.0
            dlat = radians(lat2 - lat1)
            dlon = radians(lon2 - lon1)
            a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
            return 2.0 * R * asin(sqrt(a))

        valid_plans = [p for p in plans if p.latitude and p.longitude]
        if not valid_plans:
            return

        min_dist = min(haversine(latitude, longitude, p.latitude, p.longitude) for p in valid_plans)
        now = fields.Datetime.now()
        alert_threshold = now - timedelta(minutes=30)

        if min_dist > 2000 and (not self.last_alert_sent or self.last_alert_sent < alert_threshold):
            self.sudo().write({"route_deviation_alert": True, "last_alert_sent": now})
            self.message_post(
                body=_(
                    "⚠️ Route Deviation Alert: %s is %.0f meters away from nearest unvisited location."
                ) % (self.user_id.name, min_dist),
                subject=_("Route Deviation Alert"),
                partner_ids=[self.env.ref("base.user_admin").partner_id.id],
            )

    def _reverse_geocode_location(self, latitude, longitude):
        self.ensure_one()
        try:
            response = requests.get(
                "https://nominatim.openstreetmap.org/reverse",
                headers={"User-Agent": "Odoo (http://www.odoo.com/contactus)"},
                params={
                    "format":         "jsonv2",
                    "lat":            latitude,
                    "lon":            longitude,
                    "zoom":           18,
                    "addressdetails": 1,
                    "accept-language": "en",
                },
                timeout=10,
            )
            response.raise_for_status()
            result = self._format_reverse_geocode_result(response.json())
            if result:
                return result
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
        city = (
            address.get("city")
            or address.get("town")
            or address.get("municipality")
            or address.get("village")
        )
        postcode = address.get("postcode")
        parts = []
        if area:
            parts.append(area)
        city_postcode = " ".join(p for p in (city, postcode) if p)
        if city_postcode:
            parts.append(city_postcode)
        if not parts and result.get("display_name"):
            fallback = [p.strip() for p in result["display_name"].split(",") if p.strip()]
            parts = fallback[1:3] if len(fallback) >= 3 else fallback[:2]
        return ", ".join(parts)

    def _clean_location_area(self, area):
        if not area:
            return area
        generic_tokens = ("housing", "residential", "apartment", "building", "tower")
        if any(token in area.lower() for token in generic_tokens):
            return False
        return area

    # ── Smart Buttons / Actions ────────────────────────────────────────────────
    def action_view_history(self):
        self.ensure_one()
        return {
            "type":      "ir.actions.act_window",
            "name":      _("Location History"),
            "res_model": "salesperson.location.log",
            "view_mode": "list,form",
            "domain":    [("tracker_id", "=", self.id)],
            "context":   {"default_tracker_id": self.id, "search_default_today": 1},
        }

    def action_open_moving_map_view(self):
        self.ensure_one()
        return {
            "type":   "ir.actions.act_url",
            "url":    "/salesperson_tracking/moving_map/%d" % self.id,
            "target": "new",
        }

    def action_open_live_tracking_page(self):
        self.ensure_one()
        return self.user_id.action_open_live_tracking_page()

    def action_view_today_visit_plan(self):
        self.ensure_one()
        today  = fields.Date.context_today(self)
        action = self.env.ref("salesperson_live_tracking.action_salesperson_visit_plan").read()[0]
        action["domain"]  = [("user_id", "=", self.user_id.id), ("visit_date", "=", today)]
        action["context"] = {
            "default_user_id":    self.user_id.id,
            "default_visit_date": today,
            "search_default_today": 1,
        }
        return action

    def action_view_checkins(self):
        self.ensure_one()
        return {
            "type":      "ir.actions.act_window",
            "name":      _("Check-Ins"),
            "res_model": "salesperson.checkin",
            "view_mode": "list,form",
            "domain":    [("tracker_id", "=", self.id)],
            "context":   {"default_tracker_id": self.id},
        }

    def action_view_kpi(self):
        self.ensure_one()
        return {
            "type":      "ir.actions.act_window",
            "name":      _("KPI Summary"),
            "res_model": "salesperson.kpi",
            "view_mode": "list,form",
            "domain":    [("user_id", "=", self.user_id.id)],
        }


# ─────────────────────────────────────────────────────────────────────────────
class SalesPersonSpaceLine(models.Model):
    _name = "sales.person.space.line"
    _description = "Sales Person Space Line"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    salesperson_tracker_id = fields.Many2one(   # ✅ inverse of line_ids above
        'salesperson.tracker',
        string="Salesperson Tracker",
        ondelete="cascade",
        index=True,
    )
    plan_id = fields.Many2one(
        'salesperson.visit.plan',
        string="Plan",
        ondelete="set null",
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        required=True,
    )
    visit_date    = fields.Date(string="Visit Date", required=True ,tracking=True)
    from_location = fields.Char(string="From")
    to_location   = fields.Char(string="To")
    total_cost    = fields.Char(string="Total Cost")
    notes         = fields.Text(string="Notes")
    state = fields.Selection(
        related="plan_id.state",
        string="Status",
        store=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
class SalespersonLocationLog(models.Model):
    _name = "salesperson.location.log"
    _description = "Salesperson Location History"
    _order = "tracked_at desc, id desc"

    tracker_id = fields.Many2one(
        "salesperson.tracker", required=True, ondelete="cascade", index=True
    )
    user_id = fields.Many2one(
        "res.users", related="tracker_id.user_id", store=True, readonly=True, index=True
    )
    partner_id = fields.Many2one(
        "res.partner", related="tracker_id.partner_id", store=True, readonly=True, index=True
    )
    company_id = fields.Many2one(
        "res.company", related="tracker_id.company_id", store=True, readonly=True
    )
    tracked_at    = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    latitude      = fields.Float(required=True, digits=(16, 7))
    longitude     = fields.Float(required=True, digits=(16, 7))
    accuracy      = fields.Float(string="Accuracy (m)", digits=(16, 2))
    speed         = fields.Float(string="Speed (m/s)",  digits=(16, 2))
    heading       = fields.Float(string="Heading",      digits=(16, 2))
    source        = fields.Char(default="browser")
    location_name = fields.Char(string="Location")
    openstreetmap_url = fields.Char(compute="_compute_map_url")

    @api.depends("latitude", "longitude")
    def _compute_map_url(self):
        for log in self:
            if log.latitude or log.longitude:
                log.openstreetmap_url = (
                    "https://www.openstreetmap.org/?mlat=%s&mlon=%s#map=16/%s/%s"
                    % (log.latitude, log.longitude, log.latitude, log.longitude)
                )
            else:
                log.openstreetmap_url = False
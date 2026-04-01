import json

from odoo import fields, http, _
from odoo.exceptions import AccessError, ValidationError
from odoo.http import request


class SalespersonTrackingController(http.Controller):
    def _check_salesperson_access(self):
        user = request.env.user
        if not user.has_group("sales_team.group_sale_salesman"):
            raise AccessError(_("Only salespeople can use live tracking."))
        return user

    def _json_body(self):
        payload = request.httprequest.data or b"{}"
        return json.loads(payload.decode("utf-8"))

    @http.route("/salesperson_tracking/live", type="http", auth="user", website=False)
    def salesperson_tracking_live_page(self, **kwargs):
        user = self._check_salesperson_access()
        tracker = user.sudo()._ensure_salesperson_tracker()
        my_tracking_action = request.env.ref("salesperson_live_tracking.action_salesperson_tracker_my")
        values = {
            "tracker": tracker,
            "user": user,
            "my_tracking_url": "/web#action=%s&model=salesperson.tracker&view_type=list" % my_tracking_action.id,
        }
        return request.render("salesperson_live_tracking.live_tracking_page", values)

    @http.route("/salesperson_tracking/update", type="http", auth="user", methods=["POST"], csrf=False)
    def salesperson_tracking_update(self, **kwargs):
        user = self._check_salesperson_access()
        payload = self._json_body()
        try:
            latitude = float(payload["latitude"])
            longitude = float(payload["longitude"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValidationError(_("Latitude and longitude are required.")) from error

        if not -90.0 <= latitude <= 90.0:
            raise ValidationError(_("Latitude must be between -90 and 90."))
        if not -180.0 <= longitude <= 180.0:
            raise ValidationError(_("Longitude must be between -180 and 180."))

        tracker = user.sudo()._ensure_salesperson_tracker()
        tracker.sudo().update_live_location(
            latitude=latitude,
            longitude=longitude,
            accuracy=payload.get("accuracy"),
            speed=payload.get("speed"),
            heading=payload.get("heading"),
            source=payload.get("source") or "browser",
        )
        return request.make_json_response({
            "ok": True,
            "tracker_id": tracker.id,
            "status": tracker.tracking_status,
            "status_label": tracker.tracking_status_label,
            "last_seen": fields.Datetime.to_string(tracker.last_seen),
            "latitude": tracker.partner_id.partner_latitude,
            "longitude": tracker.partner_id.partner_longitude,
            "location_name": tracker.location_name,
            "map_url": tracker.openstreetmap_url,
        })

    @http.route("/salesperson_tracking/moving_map/<int:tracker_id>", type="http", auth="user", website=False)
    def salesperson_tracking_moving_map(self, tracker_id, **kwargs):
        user = self._check_salesperson_access()
        tracker = request.env["salesperson.tracker"].sudo().browse(tracker_id)
        if not tracker.exists():
            return request.not_found()
        today_start = fields.Datetime.to_string(
            fields.Datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        )
        logs = request.env["salesperson.location.log"].sudo().search(
            [
                ("tracker_id", "=", tracker_id),
                ("tracked_at", ">=", today_start),
            ],
            order="tracked_at asc",
        )
        location_points = [
            {
                "lat": log.latitude,
                "lng": log.longitude,
                "accuracy": log.accuracy,
                "speed": log.speed,
                "time": fields.Datetime.to_string(log.tracked_at),
                "location_name": log.location_name or "",
            }
            for log in logs
            if log.latitude and log.longitude
        ]
        import json as json_lib
        import base64 as base64_lib
        json_str = json_lib.dumps(location_points)
        json_b64 = base64_lib.b64encode(json_str.encode("utf-8")).decode("ascii")
        values = {
            "tracker": tracker,
            "user": user,
            "location_points_b64": json_b64,
            "total_logs": len(location_points),
        }
        return request.render("salesperson_live_tracking.moving_map_page", values)


    @http.route("/salesperson_tracking/stop", type="http", auth="user", methods=["POST"], csrf=False)
    def salesperson_tracking_stop(self, **kwargs):
        user = self._check_salesperson_access()
        tracker = user.sudo()._ensure_salesperson_tracker()
        tracker.sudo().write({"is_tracking": False})
        return request.make_json_response({"ok": True, "status": tracker.tracking_status})

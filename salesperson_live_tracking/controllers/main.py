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

    @http.route("/salesperson_tracking/stop", type="http", auth="user", methods=["POST"], csrf=False)
    def salesperson_tracking_stop(self, **kwargs):
        user = self._check_salesperson_access()
        tracker = user.sudo()._ensure_salesperson_tracker()
        tracker.sudo().write({"is_tracking": False})
        return request.make_json_response({"ok": True, "status": tracker.tracking_status})

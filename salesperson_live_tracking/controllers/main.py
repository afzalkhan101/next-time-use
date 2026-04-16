import base64
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
        today = fields.Date.context_today(request.env.user)
        # Today's planned visits for map markers
        plans = request.env["salesperson.visit.plan"].sudo().search(
            [("user_id", "=", user.id), ("visit_date", "=", today)]
        )
        plan_data = [
            {
                "id": p.id,
                "name": p.location_name,
                "lat": p.latitude,
                "lng": p.longitude,
                "covered": p.is_covered,
                "stay": p.stay_duration_display,
                "radius": p.radius_meters,
            }
            for p in plans
            if p.latitude or p.longitude
        ]
        # Active check-in if any
        active_checkin = request.env["salesperson.checkin"].sudo().search(
            [("user_id", "=", user.id), ("state", "=", "checked_in")], limit=1
        )
        my_tracking_action = request.env.ref("salesperson_live_tracking.action_salesperson_tracker_my")
        import json as json_lib, base64 as b64_lib
        plan_b64 = b64_lib.b64encode(json_lib.dumps(plan_data).encode()).decode()
        values = {
            "tracker": tracker,
            "user": user,
            "my_tracking_url": "/web#action=%s&model=salesperson.tracker&view_type=list" % my_tracking_action.id,
            "plan_points_b64": plan_b64,
            "active_checkin": active_checkin,
            "today_plan_count": len(plans),
            "today_covered_count": len(plans.filtered("is_covered")),
        }
        return request.render("salesperson_live_tracking.live_tracking_page", values)

    # ── location update ────────────────────────────────────────────────────────

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
        user    = self._check_salesperson_access()
        payload = self._json_body()
        tracker = user.sudo()._ensure_salesperson_tracker()
        vals = {
            "is_tracking":         False,
            "last_tracking_start": False,
        }
        
        try:
            duration_seconds = int(payload.get("duration_seconds") or 0)   
        except (TypeError, ValueError):
            duration_seconds = 0

        if duration_seconds <= 0 and tracker.last_tracking_start:
            delta = fields.Datetime.now() - tracker.last_tracking_start
            duration_seconds = int(delta.total_seconds())

        if 0 < duration_seconds < 86400:
            vals["last_tracking_duration"] = duration_seconds

    
        tracker.sudo().write(vals)

        return request.make_json_response({
            "ok":             True,
            "status":         tracker.tracking_status,
            "duration_saved": duration_seconds,
        })
    

    @http.route("/salesperson_tracking/checkin", type="http", auth="user", methods=["POST"], csrf=False)
    def salesperson_tracking_checkin(self, **kwargs):
        """
        Req #7: Check-In with auto time & location capture.
        JSON body: { latitude, longitude, location_name, visit_plan_id (optional) }
        """
        user = self._check_salesperson_access()
        payload = self._json_body()
        try:
            latitude = float(payload["latitude"])
            longitude = float(payload["longitude"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValidationError(_("Latitude and longitude are required.")) from error

        tracker = user.sudo()._ensure_salesperson_tracker()
        location_name = payload.get("location_name") or tracker.location_name or "Unknown Location"

        # Close any existing open check-in first
        existing = request.env["salesperson.checkin"].sudo().search(
            [("user_id", "=", user.id), ("state", "=", "checked_in")], limit=1
        )
        if existing:
            existing.action_checkout(latitude=latitude, longitude=longitude)

        checkin = request.env["salesperson.checkin"].sudo().create({
            "tracker_id": tracker.id,
            "location_name": location_name,
            "checkin_latitude": latitude,
            "checkin_longitude": longitude,
            "checkin_time": fields.Datetime.now(),
            "state": "checked_in",
            "visit_plan_id": payload.get("visit_plan_id") or False,
        })
        return request.make_json_response({
            "ok": True,
            "checkin_id": checkin.id,
            "checkin_name": checkin.name,
            "location_name": location_name,
            "checkin_time": fields.Datetime.to_string(checkin.checkin_time),
        })

    # ── check-out ──────────────────────────────────────────────────────────────

    @http.route("/salesperson_tracking/checkout", type="http", auth="user", methods=["POST"], csrf=False)
    def salesperson_tracking_checkout(self, **kwargs):
        """
        Req #7: Check-Out with automatic time capture.
        JSON body: { checkin_id, latitude, longitude, notes (opt), meeting_outcome (opt) }
        """
        user = self._check_salesperson_access()
        payload = self._json_body()
        checkin_id = payload.get("checkin_id")
        if checkin_id:
            checkin = request.env["salesperson.checkin"].sudo().browse(int(checkin_id))
        else:
            checkin = request.env["salesperson.checkin"].sudo().search(
                [("user_id", "=", user.id), ("state", "=", "checked_in")], limit=1
            )
        if not checkin or not checkin.exists():
            return request.make_json_response({"ok": False, "error": "No active check-in found."})

        write_vals = {}
        if payload.get("notes"):
            write_vals["notes"] = payload["notes"]
        if payload.get("meeting_outcome"):
            write_vals["meeting_outcome"] = payload["meeting_outcome"]
        if payload.get("customer_feedback"):
            write_vals["customer_feedback"] = payload["customer_feedback"]
        if write_vals:
            checkin.write(write_vals)

        lat = payload.get("latitude")
        lng = payload.get("longitude")
        checkin.action_checkout(
            latitude=float(lat) if lat else None,
            longitude=float(lng) if lng else None,
        )
        return request.make_json_response({
            "ok": True,
            "checkin_id": checkin.id,
            "duration": checkin.duration_display,
            "checkout_time": fields.Datetime.to_string(checkin.checkout_time),
        })

    # ── selfie upload ──────────────────────────────────────────────────────────

    @http.route("/salesperson_tracking/selfie", type="http", auth="user", methods=["POST"], csrf=False)
    def salesperson_tracking_selfie(self, **kwargs):
        """
        Req #3: Geo-Tagged Selfie Proof.
        JSON body: { checkin_id, image_b64, latitude, longitude }
        """
        user = self._check_salesperson_access()
        payload = self._json_body()
        checkin_id = payload.get("checkin_id")
        image_b64 = payload.get("image_b64", "")
        lat = payload.get("latitude")
        lng = payload.get("longitude")

        if not checkin_id:
            # attach to the currently open check-in
            checkin = request.env["salesperson.checkin"].sudo().search(
                [("user_id", "=", user.id), ("state", "=", "checked_in")], limit=1
            )
        else:
            checkin = request.env["salesperson.checkin"].sudo().browse(int(checkin_id))

        if not checkin or not checkin.exists():
            return request.make_json_response({"ok": False, "error": "No active check-in."})

        # Strip data URL prefix if present
        if "," in image_b64:
            image_b64 = image_b64.split(",", 1)[1]

        checkin.write({
            "selfie_image": image_b64,
            "selfie_filename": "selfie_%s.jpg" % checkin.id,
            "selfie_taken_at": fields.Datetime.now(),
            "selfie_latitude": float(lat) if lat else 0.0,
            "selfie_longitude": float(lng) if lng else 0.0,
        })
        return request.make_json_response({
            "ok": True,
            "checkin_id": checkin.id,
            "selfie_taken_at": fields.Datetime.to_string(checkin.selfie_taken_at),
        })

    # ── offline sync ───────────────────────────────────────────────────────────

    @http.route("/salesperson_tracking/sync_offline", type="http", auth="user", methods=["POST"], csrf=False)
    def salesperson_tracking_sync_offline(self, **kwargs):
        """
        Req #8: Offline Mode Support.
        Accepts a batch of queued location updates collected while offline.
        JSON body: { events: [ {type, payload, queued_at}, … ] }
        """
        user = self._check_salesperson_access()
        payload = self._json_body()
        events = payload.get("events") or []
        tracker = user.sudo()._ensure_salesperson_tracker()
        processed = 0
        errors = []
        for event in events:
            try:
                etype = event.get("type")
                ep = event.get("payload") or {}
                if etype == "location":
                    tracker.sudo().update_live_location(
                        latitude=float(ep["latitude"]),
                        longitude=float(ep["longitude"]),
                        accuracy=ep.get("accuracy"),
                        speed=ep.get("speed"),
                        heading=ep.get("heading"),
                        source="offline_sync",
                    )
                elif etype == "checkin":
                    request.env["salesperson.checkin"].sudo().create({
                        "tracker_id": tracker.id,
                        "location_name": ep.get("location_name") or "Offline Check-In",
                        "checkin_latitude": float(ep.get("latitude") or 0),
                        "checkin_longitude": float(ep.get("longitude") or 0),
                        "checkin_time": ep.get("checkin_time") or fields.Datetime.to_string(fields.Datetime.now()),
                        "state": "checked_in",
                    })
                elif etype == "checkout":
                    cid = ep.get("checkin_id")
                    if cid:
                        ci = request.env["salesperson.checkin"].sudo().browse(int(cid))
                        if ci.exists() and ci.state == "checked_in":
                            if ep.get("notes"):
                                ci.write({"notes": ep["notes"]})
                            if ep.get("meeting_outcome"):
                                ci.write({"meeting_outcome": ep["meeting_outcome"]})
                            ci.action_checkout(
                                latitude=float(ep["latitude"]) if ep.get("latitude") else None,
                                longitude=float(ep["longitude"]) if ep.get("longitude") else None,
                            )
                processed += 1
            except Exception as e:
                errors.append(str(e))
        return request.make_json_response({
            "ok": True,
            "processed": processed,
            "errors": errors,
        })

    # ── visit plan data for mobile map ─────────────────────────────────────────

    @http.route("/salesperson_tracking/my_plans", type="http", auth="user", methods=["GET"], csrf=False)
    def salesperson_tracking_my_plans(self, **kwargs):
        """Return today's visit plans as JSON for the mobile tracking page."""
        user = self._check_salesperson_access()
        today = fields.Date.context_today(request.env.user)
        plans = request.env["salesperson.visit.plan"].sudo().search(
            [("user_id", "=", user.id), ("visit_date", "=", today)]
        )
        data = [
            {
                "id": p.id,
                "name": p.location_name,
                "lat": p.latitude,
                "lng": p.longitude,
                "covered": p.is_covered,
                "stay": p.stay_duration_display,
                "radius": p.radius_meters,
                "priority": p.priority,
                "notes": p.manager_notes or "",
            }
            for p in plans
            if p.latitude or p.longitude
        ]
        return request.make_json_response({"ok": True, "plans": data})

    # ── moving map ─────────────────────────────────────────────────────────────

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
            [("tracker_id", "=", tracker_id), ("tracked_at", ">=", today_start)],
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
        # Also fetch today's visit plans for coverage overlay
        today = fields.Date.context_today(request.env.user)
        plans = request.env["salesperson.visit.plan"].sudo().search(
            [("user_id", "=", tracker.user_id.id), ("visit_date", "=", today)]
        )
        plan_markers = [
            {
                "lat": p.latitude,
                "lng": p.longitude,
                "name": p.location_name,
                "covered": p.is_covered,
                "stay": p.stay_duration_display,
                "radius": p.radius_meters,
            }
            for p in plans
            if p.latitude or p.longitude
        ]
        import json as json_lib, base64 as b64_lib
        json_b64 = b64_lib.b64encode(json_lib.dumps(location_points).encode()).decode()
        plans_b64 = b64_lib.b64encode(json_lib.dumps(plan_markers).encode()).decode()
        values = {
            "tracker": tracker,
            "user": user,
            "location_points_b64": json_b64,
            "plan_markers_b64": plans_b64,
            "total_logs": len(location_points),
        }
        return request.render("salesperson_live_tracking.moving_map_page", values)

from collections import defaultdict
from datetime import date, timedelta

from odoo import _, api, fields, models


class SalespersonKpi(models.Model):
  
    _name = "salesperson.kpi"
    _description = "Salesperson KPI Summary"
    _order = "kpi_date desc, id desc"

    user_id = fields.Many2one("res.users", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one("res.company", related="user_id.company_id", store=True, readonly=True)
    sale_team_id = fields.Many2one("crm.team", related="user_id.sale_team_id", store=True, readonly=True)
    kpi_date = fields.Date(required=True, default=fields.Date.context_today, index=True)

    planned_visits = fields.Integer(string="Planned Visits")
    completed_visits = fields.Integer(string="Completed Visits")
    visit_completion_rate = fields.Float(string="Visit Completion Rate (%)", digits=(16, 2))

    total_field_minutes = fields.Float(string="Total Field Time (min)", digits=(16, 2))
    avg_visit_duration = fields.Float(string="Avg Visit Duration (min)", digits=(16, 2))
    total_field_display = fields.Char(string="Total Field Time", compute="_compute_display_fields")

    checkin_count = fields.Integer(string="Check-Ins")
    selfie_count = fields.Integer(string="Selfies Captured")

    deals_closed = fields.Integer(string="Deals Closed")
    followups_created = fields.Integer(string="Follow-Ups Needed")
    
    positive_outcomes = fields.Integer(string="Positive Outcomes")
    neutral_outcomes = fields.Integer(string="Neutral Outcomes")
    negative_outcomes = fields.Integer(string="Negative Outcomes")

    _sql_constraints = [
        ("kpi_user_date_unique", "unique(user_id, kpi_date)", "KPI record must be unique per user per day."),
    ]

    @api.depends("total_field_minutes")
    def _compute_display_fields(self):
        for rec in self:
            mins = int(rec.total_field_minutes or 0)
            hours, m = divmod(mins, 60)
            rec.total_field_display = "%sh %sm" % (hours, m) if hours else "%sm" % m

    @api.model
    def _refresh_today(self, user):
        """Recalculate KPI for a given user for today."""
        today = fields.Date.context_today(self)
        kpi = self.search([("user_id", "=", user.id), ("kpi_date", "=", today)], limit=1)
        vals = self._compute_kpi_values(user, today)
        if kpi:
            kpi.write(vals)
        else:
            vals.update({"user_id": user.id, "kpi_date": today})
            self.create(vals)

    @api.model
    def _compute_kpi_values(self, user, target_date):
        plan_model = self.env["salesperson.visit.plan"].sudo()
        checkin_model = self.env["salesperson.checkin"].sudo()

        plans = plan_model.search([("user_id", "=", user.id), ("visit_date", "=", target_date)])
        planned = len(plans)
        completed = len(plans.filtered("is_covered"))
        rate = (completed / planned * 100.0) if planned else 0.0

        checkins = checkin_model.search(
            [("user_id", "=", user.id), ("checkin_time", ">=", "%s 00:00:00" % target_date), ("checkin_time", "<", "%s 23:59:59" % target_date)]
        )
        checked_out = checkins.filtered(lambda c: c.state == "checked_out")
        total_mins = sum(c.duration_minutes for c in checked_out)
        avg_mins = (total_mins / len(checked_out)) if checked_out else 0.0
        selfie_count = len(checkins.filtered("selfie_image"))

        outcomes = defaultdict(int)
        for c in checkins:
            if c.meeting_outcome:
                outcomes[c.meeting_outcome] += 1

        return {
            "planned_visits": planned,
            "completed_visits": completed,
            "visit_completion_rate": rate,
            "total_field_minutes": total_mins,
            "avg_visit_duration": avg_mins,
            "checkin_count": len(checkins),
            "selfie_count": selfie_count,
            "deals_closed": outcomes.get("deal_closed", 0),
            "followups_created": outcomes.get("followup_needed", 0),
            "positive_outcomes": outcomes.get("positive", 0),
            "neutral_outcomes": outcomes.get("neutral", 0),
            "negative_outcomes": outcomes.get("negative", 0),
        }

    @api.model
    def action_generate_weekly_report(self, user_id=None):
        """Generate weekly KPI summary for all or specific user."""
        user_id = user_id or self.env.uid
        today = fields.Date.context_today(self)
        week_start = today - timedelta(days=today.weekday())
        kpis = self.search(
            [("user_id", "=", user_id), ("kpi_date", ">=", week_start), ("kpi_date", "<=", today)]
        )
        return kpis

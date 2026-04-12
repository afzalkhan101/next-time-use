{
    "name": "Salesperson Live Tracking",
    "summary": "Full salesperson field tracking: GPS, check-in/out, selfie proof, KPI, alerts, offline sync, CRM integration",
    "version": "19.0.2.0.0",
    "category": "Sales/Sales",
    "depends": ["sale_management", "web_map", "base_geolocalize", "crm", "mail"],
    "data": [
        # "security/salesperson_tracking_security.xml",
        "security/ir.model.access.csv",
        "views/salesperson_tracking_views.xml",
        "views/salesperson_visit_plan_views.xml",
        "views/salesperson_checkin_views.xml",
        "views/salesperson_kpi_views.xml",
        "views/res_users_views.xml",
        "views/templates.xml",
        "data/mail_template_data.xml",
        "views/sales_person_dashboard_views.xml",
    ],
    'assets': {
    'web.assets_backend': [
        'salesperson_live_tracking/static/src/scss/style.css'
    ],
    }
    ,
    "application": False,
    "license": "LGPL-3",
}

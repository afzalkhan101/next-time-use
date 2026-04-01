# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    "name": "Salesperson Live Tracking",
    "summary": "Track salesperson live location with map and history",
    "version": "19.0.1.0.0",
    "category": "Sales/Sales",
    "depends": ["sale_management", "web_map", "base_geolocalize"],
    "data": [
        "security/salesperson_tracking_security.xml",
        "security/ir.model.access.csv",
        "views/salesperson_tracking_views.xml",
        "views/salesperson_visit_plan_views.xml",
        "views/res_users_views.xml",
        "views/templates.xml",
    ],
    "application": False,
    "license": "LGPL-3",
}

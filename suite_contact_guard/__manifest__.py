# -*- coding: utf-8 -*-
{
    'name': 'Contact Guard',
    'version': '19.0.1.0.0',
    'category': 'Sales',
    'summary': (
        'Phone uniqueness, contact field permissions, customer '
        'activity status. ORM-enforced governance for res.partner '
        'without breaking sales workflows.'
    ),
    'description': """
Contact Guard
=============

Guard-rails for Odoo Contacts. Three independent layers of governance
on res.partner, each configurable per company:

- Phone uniqueness, ORM-enforced with normalized matching
- Role-based visibility and edit protection on phone, email, and
  salesperson fields
- Daily-cron customer activity status (Active / Warning / Sleeping
  / Dormant) based on confirmed sale orders

Built and used at SuiteState. Open-sourced under LGPL-3. See the
app's listing page for full documentation.
    """,
    'author': 'SuiteState',
    'support': 'hello@suitestate.com',
    'website': 'https://suitestate.com',
    'license': 'LGPL-3',
    'depends': [
        'contacts',
        'mail',
        'sales_team',
        'sale',
        'purchase',
    ],
    'data': [
        'security/contact_guard_groups.xml',
        'security/ir.model.access.csv',
        'data/contact_guard_cron.xml',
        'views/config_views.xml',
        'views/res_partner_views.xml',
        'views/res_partner_list_views.xml',
        'views/res_partner_kanban_views.xml',
    ],
    # Apps Store images:
    # - First entry = product card thumbnail AND detail page hero.
    #   Apps Store renders this image automatically; the index.html
    #   below does NOT reference it (hero is rendered outside the
    #   description HTML body).
    # - Subsequent entries are referenced by index.html as inline
    #   content screenshots.
    # - 16:9 aspect, 1920x1080 preferred. Anything else gets cropped.
    # - icon.png is NOT listed here; it belongs only at static/description/icon.png.
    'images': [
        'static/description/suite_contact_guard_screenshot.png',
        'static/description/screenshot_phone_uniqueness.png',
        'static/description/screenshot_field_permissions.png',
        'static/description/screenshot_activity_status.png',
        'static/description/screenshot_configuration.png',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

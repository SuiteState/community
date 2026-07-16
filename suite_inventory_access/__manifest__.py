{
    'name': 'Sales Stock Viewer',
    'version': '19.0.2.0.0',
    'category': 'Sales/Sales',
    'summary': (
        'Stock visibility for sales teams: read-only on-hand '
        'quantities by location without Inventory user rights -- '
        'sales stock access, stock viewer, sales warehouse access, '
        'sales inventory access, stock by location for sales, '
        'read only stock, sales stock visibility, warehouse viewer'
    ),
    'description': """
Keywords: sales stock viewer, stock visibility for sales,
read-only stock access, sales warehouse access, on-hand for sales,
stock by location, sales inventory access, warehouse viewer,
sales stock access control, read only stock view,
sales team stock, stock viewer without inventory,
inventory access control, sales stock report

Sales Stock Viewer
==================

Gives sales users read-only access to current on-hand quantities
by location, without granting any Inventory user rights.

A new Sales Stock Viewer group adds a Stock View menu under
Sales -> Products. The view shows current on-hand quantities
grouped by location, with search/filter capabilities.

Optional per-user location restriction lets administrators scope
each sales user to specific warehouse locations. An On Hand
column is also added to the product variants list.

Pure permission layer. No new models, no business logic changes.
Safe to install and uninstall at any time.
""",
    'author': 'SuiteState',
    'maintainer': 'ElectroState FZCO',
    'website': 'https://suitestate.com',
    'license': 'LGPL-3',
    'depends': [
        'sale',
        'stock',
    ],
    'data': [
        'security/inventory_access_groups.xml',
        'security/ir.model.access.csv',
        'security/inventory_access_rules.xml',
        'views/res_users_views.xml',
        'views/product_views.xml',
        'views/quant_views.xml',
        'views/menu.xml',
    ],
    'images': [
        'static/description/suite_inventory_access_screenshort.png',
        'static/description/screenshort_quant.png',
        'static/description/screenshort_setting.png',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

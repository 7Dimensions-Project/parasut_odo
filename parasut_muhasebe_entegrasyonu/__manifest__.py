{
    'name': 'Paraşüt Odoo Muhasebe Entegrasyonu',
    'version': '19.0.1.0.0',
    'summary': 'Paraşüt ve Odoo arasında otomatik muhasebe senkronizasyonu',
    'description': """
Paraşüt Odoo Muhasebe Entegrasyonu
==================================

Complete integration solution for syncing data between Odoo ERP and Paraşüt accounting software.

Key Features:
-------------
* **Customer Synchronization**: Automatically sync customer data from Paraşüt to Odoo
* **Product Management**: Keep your product catalog up-to-date across both platforms
* **Invoice Integration**: Sync sales invoices automatically
* **Payment Tracking**: Synchronize payment records
* **Employee Management**: Import employee data from Paraşüt
* **Salary Integration**: Automatically create journal entries for salary payments
* **Tax Synchronization**: Keep tax records in sync
* **Secure API Connection**: OAuth 2.0 authentication with encrypted credentials
* **Easy Configuration**: Simple setup through Odoo settings interface
* **Manual & Automatic Sync**: Choose between manual buttons or scheduled synchronization
* **Turkish Language Support**: Full Turkish interface and documentation

Perfect for Turkish businesses using both Odoo and Paraşüt!

Configuration:
--------------
1. Go to Settings > General Settings
2. Find the "Parasut Integration" section
3. Enter your Paraşüt API credentials
4. Click sync buttons to import your data

Support:
--------
For questions, issues, or feature requests, please contact us through GitHub.
    """,
    'category': 'Accounting/Accounting',
    'author': '7Dimensions',
    'website': 'https://7dimensions.eu',
    'license': 'LGPL-3',
    'depends': ['account', 'hr'],
    'data': [
        'views/menu_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'icon': 'static/description/icon.png',
    'images': [
        'static/description/icon.png',
        'static/description/banner.png',
        'static/description/screenshot_1.png',
        'static/description/screenshot_2.png',
        'static/description/screenshot_3.png',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'support': 'support@7dimensions.eu',
    'maintainer': '7Dimensions',
}

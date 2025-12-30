{
    'name': 'Paraşüt Odoo Muhasebe Entegrasyonu',
    'version': '19.0.1.1.9',
    'summary': 'Paraşüt ve Odoo arasında otomatik muhasebe senkronizasyonu',
    'description': """
Paraşüt Odoo Muhasebe Entegrasyonu (Woodique Edition)
=====================================================

Bu modül, Paraşüt ve Odoo arasında tam veri senkronizasyonu sağlar.

Özellikler:
----------
* Kasa/Banka hesapları senkronizasyonu
* Müşteri ve Tedarikçi (Cari) senkronizasyonu
* Ürün kataloğu eşleştirme
* Satış ve Gider faturaları aktarımı
* Tahsilat ve Ödeme eşleştirme
* Maaş ve Vergi ödemeleri entegrasyonu

Yapılandırma:
-------------
1. Ayarlar > Genel Ayarlar > Paraşüt Entegrasyonu bölümüne gidin.
2. API bilgilerini (Client ID, Secret, vb.) girin.
3. 'Bağlantıyı Test Et' butonu ile kontrol edin.
4. Muhasebe menüsü altındaki 'Paraşüt Entegrasyonu' panelini kullanın.
    """,
    'category': 'Accounting/Accounting',
    'author': '7Dimensions',
    'website': 'https://7dimensions.eu',
    'depends': ['account', 'hr', 'product'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'views/parasut_views.xml',
        'views/menu_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'icon': 'static/description/icon.png',
    'images': [
        'static/description/icon.png',
        'static/description/banner.png',
    ],
    'installable': True,
    'application': True,
    'license': 'OPL-1',
    'price': 149.00,
    'currency': 'EUR',
}

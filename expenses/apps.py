from django.apps import AppConfig


class ShishutuukagaiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'expenses'
    
    def ready(self):
        # テンプレートタグを読み込む
        from . import templatetags

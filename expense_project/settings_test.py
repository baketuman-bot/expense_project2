"""テスト用設定: MySQL の代わりに SQLite インメモリ DB を使用"""
from expense_project.settings import *  # noqa: F401, F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# テスト時はメール送信をコンソール出力にして副作用を回避
EMAIL_BACKEND = 'django.core.mail.backends.dummy.EmailBackend'

# StaticFiles は CompressedManifest を使うとテストでエラーになることがあるので差し替え
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

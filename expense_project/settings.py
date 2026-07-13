from pathlib import Path
import os
import pymysql  # type: ignore
pymysql.install_as_MySQLdb()


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-your-secret-key')
# DEBUG: 環境変数で明示指定がなければ True（社内LAN運用のため）
DEBUG = os.environ.get('DEBUG', '').lower() in {'1', 'true', 'yes'}
if 'DEBUG' not in os.environ:
    DEBUG = True
MEDIA_URL = "/media/"
# ローカルの実ファイル配置に合わせて media をルートにする
# 既存ファイルが BASE_DIR/media 配下にあるため、ここを参照先に設定
MEDIA_ROOT = BASE_DIR / "media"

ALLOWED_HOSTS = [
"127.0.0.1",
"localhost",
"*",
"172.16.100.149",
"172.16.100.150",
"172.16.102.223",
"192.168.0.128"
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'expenses.apps.ShishutuukagaiConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'expense_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'expenses.context_processors.sidebar_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'expense_project.wsgi.application'


# DATABASES: 社内LAN上のMySQLサーバーを使用（本番・開発共通）
# DJANGO_TEST_DB_NAME 環境変数でテスト用DBを指定可能（デフォルト: test_expense_db）
# ※ ex_user は CREATE DATABASE 権限がないため、test_expense_db を使うには
#   別途 MySQL 管理者が GRANT ALL ON `test_expense_db`.* TO 'ex_user'@'%' を実行すること。
_test_db_name = os.environ.get('DJANGO_TEST_DB_NAME', 'test_expense_db')
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'expense_db',
        'USER': 'ex_user',
        'PASSWORD': 'Django3592',
#        'HOST': '192.168.0.128',
#        'HOST': '172.16.100.149',
        'HOST': '172.16.100.150',
        'PORT': '3306',
        'OPTIONS': {
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            'charset': 'utf8mb4',
        },
        # 接続の永続化
        'CONN_MAX_AGE': 60,
        'ATOMIC_REQUESTS': True,
        # DANGER: TEST.NAME に本番DBと同名を設定しないこと。
        # 誤ってテストを実行すると本番DBが削除される。
        # テストDB名を明示しない場合、Django は 'test_expense_db' を自動使用する。
        # 'TEST': {'NAME': 'expense_db'},  # ← 絶対に設定しないこと
        'TEST': {'NAME': _test_db_name},
    }
}

# /media の配信制御フラグ（DEBUG の最終値が決まった後に算出）
SERVE_MEDIA = (
    DEBUG or os.environ.get('SERVE_MEDIA', '').lower() in {'1', 'true', 'yes'}
)

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = 'ja'
TIME_ZONE = 'Asia/Tokyo'
USE_I18N = True
USE_TZ = False

STATIC_URL = '/static/'
STATIC_ROOT = str(BASE_DIR / 'static')
# Django 5.x では STATICFILES_STORAGE は非推奨。STORAGES 辞書で指定する。
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Cloud Run(Flask) 画像アップロードアプリ連携
# 例: https://receipt-upload-xxxxx-an.a.run.app
IMAGE_UP_APP_BASE_URL = (os.environ.get('IMAGE_UP_APP_BASE_URL') or '').strip().rstrip('/')
IMAGE_UP_APP_TIMEOUT = int(os.environ.get('IMAGE_UP_APP_TIMEOUT', '15'))

# メールリンク用サイトURL
# 環境変数 SITE_URL で本番URLを上書き可能
SITE_URL = os.environ.get('SITE_URL', 'http://172.16.100.150')

# カスタムユーザー
AUTH_USER_MODEL = 'expenses.M_User'

# 認証バックエンド: man_number(社員番号)でもログイン可能に
AUTHENTICATION_BACKENDS = [
    'expenses.auth_backends.ManNumberModelBackend',
    'django.contrib.auth.backends.ModelBackend',
]

"""メール設定（開発/社内SMTP）
社内SMTP(172.16.100.243:25) は EHLO 応答から SMTP AUTH 非対応であることを確認済み。
ユーザー名/パスワードを指定すると Django は AUTH を試みて失敗するため、
デフォルトは空文字にして認証を行わないようにする。
必要であれば環境変数で上書き可能。
"""
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = '172.16.100.243'
EMAIL_PORT = 25
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = False
EMAIL_USE_SSL = False
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = 'keiri@idc-com.co.jp'

# 強制転送先（設定時は全メールがこのアドレスへ送信される。空文字で無効）
EMAIL_FORCE_TO = os.environ.get('EMAIL_FORCE_TO', '')

# 認証設定
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'expenses:home'
LOGOUT_REDIRECT_URL = 'login'

# 逆プロキシ配下のHTTPS検知とホスト/CSRF設定
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

# 内部公開用IP (HTTP アクセス) を信頼オリジンに追加
CSRF_TRUSTED_ORIGINS = ["http://172.16.100.150"]

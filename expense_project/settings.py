from pathlib import Path
import os
"""PyMySQL は MySQL 環境でのみ必要。Render(PostgreSQL)では未インストールでも起動できるようにする。"""
try:  # optional for local MySQL
    import pymysql  # type: ignore
    pymysql.install_as_MySQLdb()
except Exception:
    pass


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-your-secret-key')
# DEBUG: 本番(Render等)では環境変数で制御。ローカル（DATABASE_URL未設定）では明示未指定なら True。
DEBUG = os.environ.get('DEBUG', '').lower() in {'1', 'true', 'yes'}
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


# DATABASES = {
#    'default': {
#        'ENGINE': 'django.db.backends.sqlite3',
#        'NAME': BASE_DIR / 'db.sqlite3',
#    }
#}

"""
DATABASES 設定:
- Render など本番: 環境変数 DATABASE_URL を優先（conn_max_age/SSL 必須）
- ローカル開発: 環境変数がなければ既存の MySQL 設定を使用
"""

db_url_env = os.environ.get('DATABASE_URL')
if db_url_env:
    # Render の fromDatabase で注入される接続文字列を利用
    try:
        import dj_database_url  # type: ignore
        # sqlite のときは sslmode を付与しない
        scheme = db_url_env.split(':', 1)[0].lower()
        require_ssl = scheme not in {'sqlite', 'file'}
        DATABASES = {
            'default': dj_database_url.config(conn_max_age=600, ssl_require=require_ssl)
        }
    except Exception as e:
        # 依存関係が未インストールの場合は明示的に失敗させる
        raise RuntimeError(
            "DATABASE_URL が設定されていますが dj-database-url がインストールされていません。requirements に追加してください。"
        ) from e
else:
    # ローカル: DEBUG が環境変数で明示されていなければ有効化（/media の配信など開発用途のため）
    if 'DEBUG' not in os.environ:
        DEBUG = True
    # ローカル開発はMySQL (既存設定) を使用
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
            # 接続の永続化（ローカルでも有効にしておく）
            'CONN_MAX_AGE': 60,
            'TEST': {
                'NAME': 'expense_db',
            },
        }
    }

# 共通のDBオプション（接続の永続化とリクエストトランザクション）
if 'default' in globals().get('DATABASES', {}):
    _db = DATABASES['default']
    # 既に設定済みでなければデフォルト値を補完
    _db.setdefault('CONN_MAX_AGE', 600 if os.environ.get('DATABASE_URL') else 60)
    _db.setdefault('ATOMIC_REQUESTS', True)

# /media の配信制御フラグ（DEBUG の最終値が決まった後に算出）
SERVE_MEDIA = (
    DEBUG or os.environ.get('SERVE_MEDIA', '').lower() in {'1', 'true', 'yes'}
)

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = 'ja'
TIME_ZONE = 'Asia/Tokyo'
USE_I18N = True
USE_TZ = True

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
# 例: SITE_URL=https://myapp.onrender.com
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
DEFAULT_FROM_EMAIL = 'idc_work@idc-com.co.jp'

# 強制転送先（設定時は全メールがこのアドレスへ送信される。空文字で無効）
EMAIL_FORCE_TO = os.environ.get('EMAIL_FORCE_TO', '')

# 認証設定
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'expenses:home'
LOGOUT_REDIRECT_URL = 'login'

# Render / 逆プロキシ配下のHTTPS検知とホスト/CSRF設定
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
_render_host = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
_render_url = os.environ.get('RENDER_EXTERNAL_URL')
_csrf = []
if _render_host:
    _csrf.append(f"https://{_render_host}")
elif _render_url:
    _csrf.append(_render_url)

# 内部公開用IP (HTTP アクセス) を信頼オリジンに追加
try:
    _csrf.append("http://172.16.100.150")
except Exception:
    pass

if _csrf:
    CSRF_TRUSTED_ORIGINS = _csrf

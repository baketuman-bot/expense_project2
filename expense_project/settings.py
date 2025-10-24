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
# Render など本番では DEBUG を環境変数で制御（'True'/'true'/'1' で有効）
DEBUG = os.environ.get('DEBUG', '').lower() in {'1', 'true', 'yes'}

STATIC_URL = "/static/"  # 既にあればOK
MEDIA_URL = "/media/"
# www-data 所有の media とは分離し、ユーザーが書き込める専用ディレクトリへ
MEDIA_ROOT = BASE_DIR / "media_user"

ALLOWED_HOSTS = [
"127.0.0.1",
"localhost",
"*",
"172.16.100.149",
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

if os.environ.get('DATABASE_URL'):
    # Render の fromDatabase で注入される接続文字列を利用
    try:
        import dj_database_url  # type: ignore
        DATABASES = {
            'default': dj_database_url.config(conn_max_age=600, ssl_require=True)
        }
    except Exception as e:
        # 依存関係が未インストールの場合は明示的に失敗させる
        raise RuntimeError(
            "DATABASE_URL が設定されていますが dj-database-url がインストールされていません。requirements に追加してください。"
        ) from e
else:
    # ローカル開発はMySQL (既存設定) を使用
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': 'expense_db',
            'USER': 'ex_user',
            'PASSWORD': 'Django3592',
            'HOST': '192.168.0.128',
            'PORT': '3306',
            'OPTIONS': {
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
                'charset': 'utf8mb4',
            },
            # 接続の永続化（ローカルでも有効にしておく）
            'CONN_MAX_AGE': 60,
        }
    }

# 共通のDBオプション（接続の永続化とリクエストトランザクション）
if 'default' in globals().get('DATABASES', {}):
    _db = DATABASES['default']
    # 既に設定済みでなければデフォルト値を補完
    _db.setdefault('CONN_MAX_AGE', 600 if os.environ.get('DATABASE_URL') else 60)
    _db.setdefault('ATOMIC_REQUESTS', True)

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = 'ja'
TIME_ZONE = 'Asia/Tokyo'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = str(BASE_DIR / 'static')
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# カスタムユーザー
AUTH_USER_MODEL = 'expenses.M_User'

# 認証バックエンド: man_number(社員番号)でもログイン可能に
AUTHENTICATION_BACKENDS = [
    'expenses.auth_backends.ManNumberModelBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# メール（開発用: コンソール出力）
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = 'noreply@example.com'

# 認証設定
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'expenses:home'
LOGOUT_REDIRECT_URL = 'login'

# Render / 逆プロキシ配下のHTTPS検知とホスト/CSRF設定
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
_render_host = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
_render_url = os.environ.get('RENDER_EXTERNAL_URL')
if _render_host:
    CSRF_TRUSTED_ORIGINS = [f"https://{_render_host}"]
elif _render_url:
    CSRF_TRUSTED_ORIGINS = [_render_url]

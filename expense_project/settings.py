from pathlib import Path
import pymysql
pymysql.install_as_MySQLdb()


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-your-secret-key'
DEBUG = True

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

# ローカル開発はMySQL (localhost) を使用
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'expense_db',         # 1.2で作成したデータベース名
        'USER': 'ex_user',        # 1.3で作成したユーザー名
        'PASSWORD': 'Django3592',         # 1.3で設定したパスワード
        'HOST': '192.168.0.128',            # MySQLサーバーのホスト名 (通常はlocalhost)
#        'HOST': '172.16.100.149',  
#        'HOST': '192.168.1.63',
        'PORT': '3306',                 # MySQLサーバーのポート番号 (通常は3306)
        'OPTIONS': {
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            'charset': 'utf8mb4',
        },
    }
}


AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = 'ja'
TIME_ZONE = 'Asia/Tokyo'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = str(BASE_DIR / 'static')
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

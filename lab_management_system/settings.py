
import os
from pathlib import Path

from dotenv import load_dotenv

try:
    import dj_database_url
except ImportError:
    dj_database_url = None

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')


def env_bool(name, default='False'):
    return os.getenv(name, default).strip().lower() == 'true'


def env_list(name, default=''):
    return [item.strip() for item in os.getenv(name, default).split(',') if item.strip()]


SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'change-me-in-production')
DEBUG = env_bool('DJANGO_DEBUG', 'True')
ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost')
CSRF_TRUSTED_ORIGINS = env_list('DJANGO_CSRF_TRUSTED_ORIGINS')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'accounts.apps.AccountsConfig',
    'bookings.apps.BookingsConfig',
    'reports.apps.ReportsConfig',
]

MIDDLEWARE = [
    # Compress eligible dynamic responses of at least 200 bytes when the
    # client advertises gzip in Accept-Encoding.  It leaves already encoded
    # responses (including WhiteNoise's pre-compressed static assets) alone.
    'django.middleware.gzip.GZipMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'accounts.middleware.UserActivityMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'lab_management_system.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'lab_management_system.wsgi.application'
ASGI_APPLICATION = 'lab_management_system.asgi.application'

database_url = os.getenv('DATABASE_URL', '').strip()
use_postgres = env_bool('DJANGO_USE_POSTGRES', 'False')

if database_url:
    if dj_database_url is None:
        raise ImportError('DATABASE_URL is set but dj-database-url is not installed.')
    DATABASES = {
        'default': dj_database_url.parse(database_url, conn_max_age=600),
    }
elif use_postgres and os.getenv('POSTGRES_DB', '').strip():
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('POSTGRES_DB', '').strip(),
            'USER': os.getenv('POSTGRES_USER', '').strip(),
            'PASSWORD': os.getenv('POSTGRES_PASSWORD', '').strip(),
            'HOST': os.getenv('POSTGRES_HOST', '127.0.0.1').strip(),
            'PORT': os.getenv('POSTGRES_PORT', '5432').strip(),
            'CONN_MAX_AGE': 600,
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
    {'NAME': 'accounts.password_validators.MaximumPasswordLengthValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = os.getenv('DJANGO_TIME_ZONE', 'Asia/Kolkata')
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

SECURE_SSL_REDIRECT = env_bool('DJANGO_SECURE_SSL_REDIRECT', 'False')
SESSION_COOKIE_SECURE = env_bool('DJANGO_SESSION_COOKIE_SECURE', 'False')
CSRF_COOKIE_SECURE = env_bool('DJANGO_CSRF_COOKIE_SECURE', 'False')
SECURE_HSTS_SECONDS = int(os.getenv('DJANGO_SECURE_HSTS_SECONDS', '0').strip() or '0')
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS', 'False')
SECURE_HSTS_PRELOAD = env_bool('DJANGO_SECURE_HSTS_PRELOAD', 'False')
SECURE_BROWSER_XSS_FILTER = env_bool('DJANGO_SECURE_BROWSER_XSS_FILTER', 'True')
SECURE_CONTENT_TYPE_NOSNIFF = env_bool('DJANGO_SECURE_CONTENT_TYPE_NOSNIFF', 'True')
# Enable this only behind a proxy that strips client-supplied X-Forwarded-Proto
# and sets its own trusted value. Direct Gunicorn deployments must leave it off.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https') if env_bool('DJANGO_SECURE_PROXY_SSL_HEADER', 'False') else None
X_FRAME_OPTIONS = os.getenv('DJANGO_X_FRAME_OPTIONS', 'DENY').strip() or 'DENY'

if not DEBUG:
    SESSION_COOKIE_SECURE = env_bool('DJANGO_SESSION_COOKIE_SECURE', 'True')
    CSRF_COOKIE_SECURE = env_bool('DJANGO_CSRF_COOKIE_SECURE', 'True')
    SECURE_SSL_REDIRECT = env_bool('DJANGO_SECURE_SSL_REDIRECT', 'True')

SECURE_CROSS_ORIGIN_OPENER_POLICY = (
    os.getenv(
        'DJANGO_SECURE_CROSS_ORIGIN_OPENER_POLICY',
        'same-origin' if SECURE_SSL_REDIRECT else '',
    ).strip()
    or None
)

# Protect Gunicorn workers from an overloaded or failing LibreOffice preview
# converter. The circuit opens after repeated failures and automatically probes
# again after the recovery period.
DOCUMENT_CONVERTER_TIMEOUT_SECONDS = int(os.getenv('DOCUMENT_CONVERTER_TIMEOUT_SECONDS', '20'))
DOCUMENT_CONVERTER_FAILURE_THRESHOLD = int(os.getenv('DOCUMENT_CONVERTER_FAILURE_THRESHOLD', '3'))
DOCUMENT_CONVERTER_RECOVERY_SECONDS = int(os.getenv('DOCUMENT_CONVERTER_RECOVERY_SECONDS', '60'))
DOCUMENT_CONVERTER_MAX_CONCURRENT = int(os.getenv('DOCUMENT_CONVERTER_MAX_CONCURRENT', '1'))
DOCUMENT_CONVERTER_LOCK_PATH = os.getenv('DOCUMENT_CONVERTER_LOCK_PATH', '/tmp/arl-document-converter.lock')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'accounts:login'

"""Configuración de la API de consulta del SGR (proyecto separado).

Usa dos bases de datos:
- ``default``: base propia y pequeña de la API (tokens e intentos de acceso).
- ``sgr``: la base del sistema SGR, solo lectura. La API nunca escribe en ella.
"""
import sys
from pathlib import Path

from decouple import AutoConfig, Csv

BASE_DIR = Path(__file__).resolve().parent.parent
env = AutoConfig(search_path=BASE_DIR)

TESTING = len(sys.argv) > 1 and sys.argv[1] == 'test'

SECRET_KEY = env('SECRET_KEY', default='solo-pruebas-no-usar' if TESTING else None)
if not SECRET_KEY:
    raise RuntimeError('Falta SECRET_KEY en el archivo .env (ver .env.example).')
DEBUG = env('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = env('ALLOWED_HOSTS', default='127.0.0.1,localhost', cast=Csv())

INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
    'drf_spectacular',
    'consulta',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'sgr_api.urls'
WSGI_APPLICATION = 'sgr_api.wsgi.application'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': ['django.template.context_processors.request']},
}]


# ---------------------------------------------------------------------------
# Bases de datos
# ---------------------------------------------------------------------------
def _ruta(valor):
    ruta = Path(valor)
    return ruta if ruta.is_absolute() else (BASE_DIR / ruta).resolve()


SGR_DB_ENGINE = env('SGR_DB_ENGINE', default='sqlite').lower()
if TESTING:
    # Las pruebas crean una base temporal propia; nunca tocan la base real.
    base_sgr = {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'pruebas_sgr.sqlite3'}
elif SGR_DB_ENGINE == 'mysql':
    base_sgr = {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': env('SGR_DB_NAME'),
        'USER': env('SGR_DB_USER'),
        'PASSWORD': env('SGR_DB_PASSWORD'),
        'HOST': env('SGR_DB_HOST', default='127.0.0.1'),
        'PORT': env('SGR_DB_PORT', default='3306'),
        'OPTIONS': {
            'charset': 'utf8mb4',
            # Además del usuario con permiso SELECT, la sesión se abre en solo lectura.
            'init_command': "SET SESSION TRANSACTION READ ONLY, sql_mode='STRICT_TRANS_TABLES'",
        },
    }
else:
    ruta_sgr = _ruta(env('SGR_DB_NAME', default='../BackEnd3-main/backend/db.sqlite3'))
    base_sgr = {
        'ENGINE': 'django.db.backends.sqlite3',
        # mode=ro: SQLite rechaza cualquier escritura en la base del SGR.
        'NAME': f'file:{ruta_sgr.as_posix()}?mode=ro',
        'OPTIONS': {'uri': True},
    }

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': _ruta(env('API_DB_NAME', default='api.sqlite3')),
    },
    'sgr': base_sgr,
}
DATABASE_ROUTERS = ['consulta.db_router.RouterSGR']
TEST_RUNNER = 'consulta.pruebas.RunnerPruebas'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ---------------------------------------------------------------------------
# API REST y documentación Swagger / OpenAPI
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    'DEFAULT_AUTHENTICATION_CLASSES': ['consulta.autenticacion.TokenSGRAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'DEFAULT_PAGINATION_CLASS': 'consulta.paginacion.Paginacion',
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {'anon': '30/min', 'user': '240/min', 'token': '10/min'},
    'UNAUTHENTICATED_USER': None,
}
if TESTING:
    # Las pruebas hacen muchas solicitudes seguidas; el bloqueo por intentos se prueba aparte.
    REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] = {'anon': '10000/min', 'user': '10000/min', 'token': '10000/min'}

SPECTACULAR_SETTINGS = {
    'TITLE': 'API de consulta SGR - Municipalidad de La Serena',
    'DESCRIPTION': (
        'API REST de **solo lectura** del Sistema de Gestión de Resultados (SGR).\n\n'
        '1. Obtén un token en `POST /api/v1/token/` con tu usuario y contraseña del SGR '
        '(y `codigo_2fa` si tu cuenta tiene verificación en dos pasos).\n'
        '2. Presiona **Authorize** e ingresa el token.\n\n'
        'Cada usuario ve solo lo que su rol permite en el SGR. Los listados vienen paginados '
        '(50 por página; `?page=` y `?page_size=` hasta 500).'
    ),
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    'SCHEMA_PATH_PREFIX': r'/api/v1',
}

API_TOKEN_HORAS = env('API_TOKEN_HORAS', default=8, cast=int)
API_MAX_INTENTOS = env('API_MAX_INTENTOS', default=5, cast=int)
API_BLOQUEO_MINUTOS = env('API_BLOQUEO_MINUTOS', default=15, cast=int)

CORS_ALLOWED_ORIGINS = env('CORS_ALLOWED_ORIGINS', default='', cast=Csv())
CORS_ALLOW_CREDENTIALS = False


# ---------------------------------------------------------------------------
# Seguridad
# ---------------------------------------------------------------------------
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_SSL_REDIRECT = env('SECURE_SSL_REDIRECT', default=False, cast=bool)
if env('TRUST_PROXY_SSL_HEADER', default=False, cast=bool):
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

LANGUAGE_CODE = 'es-cl'
TIME_ZONE = 'America/Santiago'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'consola': {'class': 'logging.StreamHandler'}},
    'loggers': {'sgr_api.acceso': {'handlers': ['consola'], 'level': 'INFO'}},
}

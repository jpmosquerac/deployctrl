from pathlib import Path
from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY', default='django-insecure-change-me-in-production')
DEBUG = config('DEBUG', default=True, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())

INSTALLED_APPS = [
    'django.contrib.staticfiles',
    # Third-party
    'rest_framework',
    'corsheaders',
    # Local
    'apps.web',
    'apps.accounts.apps.AccountsConfig',  # connects MongoDB on startup
    'apps.catalog',
    'apps.infra_requests',
    'apps.audit',
    'apps.gitops',
    'apps.teams',
    'apps.terraform',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'deployctrl.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
            ],
        },
    },
]

WSGI_APPLICATION = 'deployctrl.wsgi.application'

# ── MongoDB (all data) ─────────────────────────────────────────────────────
MONGO_URI = config('MONGO_URI', default='mongodb://localhost:27017/deployctrl')
MONGO_DB  = config('MONGO_DB',  default='deployctrl')

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# ── Django REST Framework ──────────────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'apps.accounts.authentication.MongoJWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'apps.accounts.rbac.IsMongoAuthenticated',
    ),
    'UNAUTHENTICATED_USER': None,  # django.contrib.auth not installed
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
}

# ── JWT ────────────────────────────────────────────────────────────────────
JWT_ACCESS_HOURS  = config('JWT_ACCESS_HOURS',  default=8,  cast=int)
JWT_REFRESH_DAYS  = config('JWT_REFRESH_DAYS',  default=7,  cast=int)

# ── CORS ───────────────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = config(
    'CORS_ALLOWED_ORIGINS',
    default='http://localhost:5173,http://localhost:3000',
    cast=Csv(),
)
CORS_ALLOW_CREDENTIALS = True

# ── GitHub API (GitOps) ────────────────────────────────────────────────────
GITHUB_API_BASE = 'https://api.github.com'

# ── Terraform ──────────────────────────────────────────────────────────────
# Directory where full run logs are written (map to a PersistentVolume in k8s)
TERRAFORM_LOG_DIR  = config('TERRAFORM_LOG_DIR',  default='/tmp/deployctrl/logs')
# Directory where per-run workspaces are created; each run clones the repo
# into <TERRAFORM_WORK_DIR>/<run-id>/iac/ and executes from there.
TERRAFORM_WORK_DIR = config('TERRAFORM_WORK_DIR', default='/tmp/deployctrl/workspace')
# HTTP backend for Terraform state (stored in MongoDB)
# TF_BACKEND_BASE_URL must be reachable from the Terraform process.
TF_STATE_SECRET     = config('TF_STATE_SECRET',     default='change-me-in-production')
TF_BACKEND_BASE_URL = config('TF_BACKEND_BASE_URL', default='http://127.0.0.1:8000')


"""
SCLM Cloud — Base Settings
Django 5.x | Domain-Driven Modular Monolith | Schema-Based Multi-Tenancy
"""

import os
from pathlib import Path
import dj_database_url
from decouple import config

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
SECRET_KEY = config("SECRET_KEY", default="change-me-in-production-use-env")
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    default="localhost,127.0.0.1",
    cast=lambda v: [s.strip() for s in v.split(",")],
)

# ---------------------------------------------------------------------------
# Multi-Tenancy (django-tenants)
# ---------------------------------------------------------------------------
# SHARED_APPS: Tables that live in the `public` schema (global SaaS routing).
# Order matters: django_tenants MUST be first.
SHARED_APPS = [
    "django_tenants",                   # Must be first
    # Django core (shared)
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.admin",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party (shared)
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    # Global domain apps (public schema)
    "apps.subscriptions",               # Client (Tenant) model lives here
    "apps.users",                       # GlobalUser, TenantUserMapping
]

# TENANT_APPS: Tables that are cloned into every tenant schema.
TENANT_APPS = [
    "django.contrib.contenttypes",
    # Operational domain apps (per-tenant schema)
    "apps.audit_ledger",
    "apps.inventory",
    "apps.forecasting",
    "apps.procurement",
    "apps.warehouse",
    "apps.transportation",
    "apps.logistics",
    "apps.returns",
    "apps.finance",
]

# The full INSTALLED_APPS is the union (django-tenants requirement).
INSTALLED_APPS = list(SHARED_APPS) + [
    app for app in TENANT_APPS if app not in SHARED_APPS
]

# The model that represents a Tenant (must subclass TenantMixin).
TENANT_MODEL = "subscriptions.Client"
# The model that maps domains to tenants (must subclass DomainMixin).
TENANT_DOMAIN_MODEL = "subscriptions.Domain"

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
MIDDLEWARE = [
    # 1. Tenant routing MUST be the very first middleware.
    #    It intercepts every request, reads the JWT, and switches the DB schema.
    "apps.users.middleware.JWTTenantRoutingMiddleware",
    # 2. Standard Django middleware chain
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# ---------------------------------------------------------------------------
# URL Configuration
# ---------------------------------------------------------------------------
# Public (shared) schema routes tenant admin / subscription endpoints.
PUBLIC_SCHEMA_URLCONF = "sclm_backend.urls_public"
# Tenant schema routes all 11 operational module endpoints.
ROOT_URLCONF = "sclm_backend.urls_public"

# ---------------------------------------------------------------------------
# WSGI
# ---------------------------------------------------------------------------
WSGI_APPLICATION = "sclm_backend.wsgi.application"

# ---------------------------------------------------------------------------
# Database — Neon DB (Serverless PostgreSQL 15+ with PostGIS)
# ---------------------------------------------------------------------------
# CONN_MAX_AGE=0 is CRITICAL for Neon's serverless connection pooler.
# Neon spins down connections aggressively; persistent connections will timeout.
# Each Django request gets a fresh connection from Neon's built-in pooler.
DATABASES = {
    "default": dj_database_url.config(
        env="DATABASE_URL",
        default=(
            "postgres://neondb_owner:password@ep-xxx.us-east-2.aws.neon.tech"
            "/neondb?sslmode=require"
        ),
        conn_max_age=0,       # Required for Neon serverless
        engine="django_tenants.postgresql_backend",
    )
}

# Explicit engine override — django-tenants requires its own backend.
DATABASES["default"]["ENGINE"] = "django_tenants.postgresql_backend"

# ---------------------------------------------------------------------------
# PostGIS — Geospatial extension for routing (apps.transportation, apps.logistics)
# ---------------------------------------------------------------------------
# django-tenants uses its own backend; we enable PostGIS via GDAL at the
# model level using django.contrib.gis geometry fields.
# Ensure PostGIS is installed on the Neon instance:
#   CREATE EXTENSION IF NOT EXISTS postgis;
DATABASE_ROUTERS = ("django_tenants.routers.TenantSyncRouter",)

# ---------------------------------------------------------------------------
# Caching — Redis (also used as Celery broker)
# ---------------------------------------------------------------------------
REDIS_URL = config("REDIS_URL", default="redis://127.0.0.1:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    }
}

# ---------------------------------------------------------------------------
# Celery — Async Task Queue
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
from celery.schedules import crontab  # noqa: E402

CELERY_BEAT_SCHEDULE = {
    # Run nightly at 2:00 AM UTC
    "generate-draft-pos-nightly": {
        "task": "apps.forecasting.tasks.generate_draft_pos",
        "schedule": crontab(hour=2, minute=0),
    },
    # Run every 4 hours
    "poll-ocean-carriers-every-4h": {
        "task": "apps.logistics.tasks.poll_ocean_carriers",
        "schedule": crontab(minute=0, hour="*/4"),
    },
}

# ---------------------------------------------------------------------------
# Authentication — Stateless JWT via djangorestframework-simplejwt
# ---------------------------------------------------------------------------
from datetime import timedelta  # noqa: E402

SIMPLE_JWT = {
    # Access token lifespan: short-lived for security
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    # Refresh token lifespan: long-lived for UX
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,   # requires token_blacklist app
    "UPDATE_LAST_LOGIN": True,
    # Custom claims — tenant_id and role are embedded in the token payload
    # so the middleware can extract them without hitting the DB on every request.
    "TOKEN_OBTAIN_SERIALIZER": "apps.users.api.serializers.CustomTokenObtainPairSerializer",
    "ALGORITHM": "HS256",
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # Custom renderer applies the standard JSON envelope to ALL responses.
    "DEFAULT_RENDERER_CLASSES": [
        "core.renderers.JSONEnvelopeRenderer",
    ],
    # Global pagination — StandardResultsPagination wraps results for the envelope.
    "DEFAULT_PAGINATION_CLASS": "core.pagination.StandardResultsPagination",
    "PAGE_SIZE": 20,
    # Throttling — prevents noisy-neighbor scenarios between tenants
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "20/minute",
        "user": "200/minute",
    },
    # Exception handler — routes all errors through the envelope renderer
    "EXCEPTION_HANDLER": "core.exceptions.sclm_exception_handler",
}

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="http://localhost:3000,http://127.0.0.1:3000",
    cast=lambda v: [s.strip() for s in v.split(",")],
)
CORS_ALLOW_CREDENTIALS = True

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static Files
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# ---------------------------------------------------------------------------
# Default Primary Key
# ---------------------------------------------------------------------------
# UUID PKs are enforced at the model level per-app using models.UUIDField.
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Custom User Model
# ---------------------------------------------------------------------------
# Must point to our GlobalUser which uses email as USERNAME_FIELD.
# Setting this BEFORE any migrations are run is critical.
AUTH_USER_MODEL = "users.GlobalUser"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{levelname}] {asctime} {module} {process:d} {thread:d} — {message}",
            "style": "{",
        },
        "simple": {
            "format": "[{levelname}] {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "apps": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}

# ---------------------------------------------------------------------------
# AWS S3 — ePOD Signature & Return Photo Storage (apps.logistics, apps.returns)
# ---------------------------------------------------------------------------
AWS_ACCESS_KEY_ID = config("AWS_ACCESS_KEY_ID", default="")
AWS_SECRET_ACCESS_KEY = config("AWS_SECRET_ACCESS_KEY", default="")
AWS_STORAGE_BUCKET_NAME = config("AWS_STORAGE_BUCKET_NAME", default="sclm-cloud-epod")
AWS_S3_REGION_NAME = config("AWS_S3_REGION_NAME", default="us-east-1")
AWS_S3_FILE_OVERWRITE = False

# ---------------------------------------------------------------------------
# Templates (needed for Django Admin)
# ---------------------------------------------------------------------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ---------------------------------------------------------------------------
# Password Validation
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

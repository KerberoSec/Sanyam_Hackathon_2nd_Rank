"""
HabitFlow Configuration Module
===============================
This module defines configuration classes for different execution environments
(development, testing, production) using Flask and SQLAlchemy conventions.
Environment variables are loaded automatically from the `.env` file if present.
"""

import os
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv

# Base directory of the application
BASE_DIR = Path(__file__).resolve().parent

# Load environment variables from .env file located at application root
ENV_FILE = BASE_DIR / '.env'
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)
else:
    load_dotenv()


class Config:
    """
    Base configuration class with default settings and environment fallbacks.
    Shared across development, testing, and production environments.
    """

    # Secret key for signing session cookies and CSRF protection
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production-habitflow')

    # Database configuration: defaults to SQLite inside an 'instance' directory if not provided
    INSTANCE_DIR = BASE_DIR / 'instance'
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_DB_PATH = f"sqlite:///{INSTANCE_DIR / 'habit_tracker.db'}"

    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', DEFAULT_DB_PATH)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_recycle': 280,
        'pool_pre_ping': True,
    }

    # JWT (JSON Web Token) configuration
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'jwt-secret-key-change-in-production-habitflow')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(days=30)
    JWT_ALGORITHM = 'HS256'

    # Session & Cookie security settings
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    # Optional SMTP settings used by the password reset flow.
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', '587'))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').strip().lower() in ('1', 'true', 'yes', 'on')
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER') or MAIL_USERNAME
    FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:5000')

    # Application settings
    APP_NAME = 'HabitFlow'
    DEFAULT_PAGE_SIZE = 20
    MAX_CONTENT_LENGTH = 1024 * 1024
    TRUSTED_PROXY_COUNT = max(0, int(os.environ.get('TRUSTED_PROXY_COUNT', '0')))


class DevelopmentConfig(Config):
    """Configuration for local development environment."""
    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    """Configuration for live production deployment."""
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True

    @classmethod
    def validate_secrets(cls):
        """Refuse to start production with missing or example signing keys."""
        placeholders = (
            'dev-secret-key-change-in-production-habitflow',
            'dev-secret-key-change-in-production',
            'jwt-secret-key-change-in-production-habitflow',
            'dev-jwt-secret-key-change-in-production',
            'change-this-in-production-with-a-secure-key',
        )
        for key_name, value in (
            ('SECRET_KEY', cls.SECRET_KEY),
            ('JWT_SECRET_KEY', cls.JWT_SECRET_KEY),
        ):
            normalized = (value or '').strip().lower()
            if (
                len(normalized) < 32
                or normalized in placeholders
                or 'change-this' in normalized
                or 'change-in-production' in normalized
                or 'your-' in normalized
            ):
                raise RuntimeError(
                    f'{key_name} must be set to a unique secret of at least 32 characters in production.'
                )
        if cls.SECRET_KEY == cls.JWT_SECRET_KEY:
            raise RuntimeError('SECRET_KEY and JWT_SECRET_KEY must be different values.')
        if not cls.MAIL_SERVER or not cls.MAIL_DEFAULT_SENDER:
            raise RuntimeError('MAIL_SERVER and MAIL_DEFAULT_SENDER must be configured in production.')
        if not cls.FRONTEND_URL.startswith('https://'):
            raise RuntimeError('FRONTEND_URL must use HTTPS in production.')
        if cls.MAIL_USERNAME and (not cls.MAIL_PASSWORD or 'your-' in cls.MAIL_USERNAME.lower()):
            raise RuntimeError('Configure real MAIL_USERNAME and MAIL_PASSWORD credentials in production.')


class TestingConfig(Config):
    """Configuration for automated test suites with an in-memory SQLite database."""
    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=15)


# Configuration mapping dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}

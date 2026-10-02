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

    # Gemini AI configuration
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', None)
    GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-1.5-flash')

    # Application settings
    APP_NAME = 'HabitFlow'
    DEFAULT_PAGE_SIZE = 20


class DevelopmentConfig(Config):
    """Configuration for local development environment."""
    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    """Configuration for live production deployment."""
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True


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

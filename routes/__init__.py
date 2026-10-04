"""
HabitFlow Routes Package
========================
This package exports all Flask route blueprints:
- auth_bp: User registration, login, profile, and JWT authentication.
- habits_bp: Habit definitions and daily completions, skips, and misses.
- analytics_bp: Dashboard metrics, weekly breakdowns, and monthly trends.
- mood_bp: Daily emotional check-in entries and wellbeing analytics.
- ai_bp: Rule-based coaching messages, summaries, and recommendations.
"""

from routes.auth import auth_bp
from routes.habits import habits_bp
from routes.analytics import analytics_bp
from routes.mood import mood_bp
from routes.ai import ai_bp

__all__ = [
    'auth_bp',
    'habits_bp',
    'analytics_bp',
    'mood_bp',
    'ai_bp'
]

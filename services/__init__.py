"""
HabitFlow Services Package
==========================
This package exports business logic and algorithmic engines:
- StreakEngine: Calculates active streaks, consistency scores, and completion rates.
- GamificationEngine: Manages XP point rewards, level progressions, and achievement badges.
- CoachEngine: Rule-based behavioral analytics, comeback messaging, and habit insights.
- AICoachService: Generative AI habit coaching, micro-habit recommendations, and reviews.
"""

from services.streak_engine import StreakEngine
from services.gamification import GamificationEngine
from services.coach_engine import CoachEngine
from services.ai_coach import AICoachService

__all__ = [
    'StreakEngine',
    'GamificationEngine',
    'CoachEngine',
    'AICoachService'
]

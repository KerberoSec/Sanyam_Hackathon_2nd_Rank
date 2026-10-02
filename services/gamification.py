"""
HabitFlow Gamification Engine
=============================
This service manages XP (experience points), level progressions, achievement badges,
and milestone celebrations.

Progression Model:
- Base XP per habit completion: +10 XP
- Streak milestone bonuses:
  - 7-day streak:  +50 XP
  - 14-day streak: +100 XP
  - 30-day streak: +200 XP
  - Every 7-day milestone beyond 30 days: +50 XP
- Leveling formula: Level = (Total XP // 100) + 1 (starts at Level 1, Level 2 at 100 XP, etc.)
- Achievement Badges:
  - Streak-based: 'First Week' (7d), 'Two Weeks Strong' (14d), 'Monthly Master' (30d)
  - Completion-based: 'Getting Started' (10), 'Habit Builder' (50), 'Centennial' (100),
                      'Consistency King' (200), 'Yearly Champion' (365)
"""

from datetime import datetime
from typing import Dict, Any, List, Optional
from models import User, UserBadge, Badge, HabitLog, db, seed_default_badges


class GamificationEngine:
    """Service managing points, levels, and badge achievements."""

    # XP reward constants
    XP_COMPLETION = 10
    XP_SKIPPED = 5
    XP_STREAK_7 = 50
    XP_STREAK_14 = 100
    XP_STREAK_30 = 200
    XP_STREAK_RECURRING_7 = 50

    @staticmethod
    def calculate_level(xp: int) -> int:
        """
        Calculates player level from total experience points.
        Level 1: 0 - 99 XP
        Level 2: 100 - 199 XP
        Level 3: 200 - 299 XP, etc.
        
        Args:
            xp: Total XP points accumulated.
            
        Returns:
            int: Player level (minimum 1).
        """
        return max(1, (xp // 100) + 1)

    @staticmethod
    def add_xp(user_id: int, amount: int, reason: str = "") -> Optional[Dict[str, Any]]:
        """
        Awards XP points to a user and evaluates whether a level up occurred.
        
        Args:
            user_id: Identifier of the user.
            amount: XP points to add.
            reason: Contextual note explaining reward (e.g. 'habit_completion', 'streak_bonus').
            
        Returns:
            dict: Current XP, level, level_up boolean flag, old and new level numbers.
        """
        user = db.session.get(User, user_id)
        if not user:
            return None

        old_level = user.level
        user.xp_points = max(0, user.xp_points + amount)
        new_level = GamificationEngine.calculate_level(user.xp_points)
        user.level = new_level

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Error updating user XP: {e}")
            return None

        level_up = new_level > old_level

        return {
            'xp': user.xp_points,
            'level': user.level,
            'level_up': level_up,
            'old_level': old_level,
            'new_level': new_level,
            'amount_added': amount,
            'reason': reason
        }

    @staticmethod
    def get_xp_progress(user_id: int) -> Optional[Dict[str, Any]]:
        """
        Returns detailed progress metrics toward the next level.
        
        Args:
            user_id: Identifier of the user.
            
        Returns:
            dict: Current level, XP within level, remaining XP needed, percentage progress.
        """
        user = db.session.get(User, user_id)
        if not user:
            return None

        xp_in_level = user.xp_points % 100
        xp_to_next = 100 - xp_in_level
        progress_pct = int((xp_in_level / 100) * 100)

        return {
            'current_xp': user.xp_points,
            'level': user.level,
            'xp_in_current_level': xp_in_level,
            'xp_to_next_level': xp_to_next,
            'progress_percent': progress_pct
        }

    @staticmethod
    def unlock_badge(user_id: int, badge_name: str, badge_description: str = "",
                     badge_icon: str = "🏆", category: str = "special") -> Optional[Dict[str, Any]]:
        """
        Unlocks a badge for a user if it has not been previously awarded.
        Creates the badge definition dynamically if it does not yet exist.
        
        Args:
            user_id: Identifier of the user.
            badge_name: Unique name of the badge.
            badge_description: Explanatory text for the badge.
            badge_icon: Emoji or icon representation.
            category: Classification category ('streak', 'completion', 'special').
            
        Returns:
            dict: Unlocked badge details if newly unlocked, or None if already awarded.
        """
        user = db.session.get(User, user_id)
        if not user:
            return None

        # Look up or create badge definition
        badge = Badge.query.filter_by(name=badge_name).first()
        if not badge:
            badge = Badge(
                name=badge_name,
                description=badge_description,
                icon=badge_icon,
                category=category
            )
            db.session.add(badge)
            db.session.flush()

        # Check if already awarded
        existing_unlock = UserBadge.query.filter_by(user_id=user_id, badge_id=badge.id).first()
        if existing_unlock:
            return None

        # Create new unlock entry
        user_badge = UserBadge(user_id=user_id, badge_id=badge.id)
        db.session.add(user_badge)

        try:
            db.session.commit()
            return badge.to_dict()
        except Exception as e:
            db.session.rollback()
            print(f"Error unlocking badge: {e}")
            return None

    @staticmethod
    def check_and_unlock_badges(user_id: int, current_streak: int, total_completions: int) -> List[Dict[str, Any]]:
        """
        Checks player metrics against all badge criteria and unlocks newly qualified badges.
        
        Args:
            user_id: Identifier of the user.
            current_streak: Current active streak achieved on the habit.
            total_completions: Total lifetime completions across all user habits.
            
        Returns:
            list: List of newly unlocked badge dictionaries.
        """
        unlocked = []

        # Streak milestone badges
        streak_milestones = [
            (7, "First Week", "Complete a habit for 7 days straight", "🔥", "streak"),
            (14, "Two Weeks Strong", "Complete a habit for 14 days straight", "💪", "streak"),
            (30, "Monthly Master", "Complete a habit for 30 days straight", "👑", "streak"),
        ]

        if current_streak > 0:
            for threshold, name, desc, icon, cat in streak_milestones:
                if current_streak >= threshold:
                    badge_dict = GamificationEngine.unlock_badge(user_id, name, desc, icon, cat)
                    if badge_dict:
                        unlocked.append(badge_dict)

        # Completion milestone badges
        completion_milestones = [
            (10, "Getting Started", "Log 10 habit completions", "🚀", "completion"),
            (50, "Habit Builder", "Log 50 habit completions", "🏗️", "completion"),
            (100, "Centennial", "Log 100 habit completions", "💯", "completion"),
            (200, "Consistency King", "Log 200 habit completions", "👑", "completion"),
            (365, "Yearly Champion", "Log 365 habit completions", "🎯", "completion"),
        ]

        for threshold, name, desc, icon, cat in completion_milestones:
            if total_completions >= threshold:
                badge_dict = GamificationEngine.unlock_badge(user_id, name, desc, icon, cat)
                if badge_dict:
                    unlocked.append(badge_dict)

        return unlocked

    @staticmethod
    def get_all_badges_with_user_status(user_id: int) -> List[Dict[str, Any]]:
        """
        Returns all badges defined in the database, annotated with whether the user
        has unlocked them and the timestamp of achievement.
        
        Args:
            user_id: Identifier of the user.
            
        Returns:
            list: List of badge dictionaries with 'unlocked' and 'earned_at' fields.
        """
        seed_default_badges()

        all_badges = Badge.query.all()
        user_unlocks = UserBadge.query.filter_by(user_id=user_id).all()
        unlock_map = {ub.badge_id: ub.earned_at.isoformat() for ub in user_unlocks if ub.earned_at}

        result = []
        for badge in all_badges:
            b_dict = badge.to_dict()
            is_unlocked = badge.id in unlock_map
            b_dict['unlocked'] = is_unlocked
            b_dict['earned_at'] = unlock_map.get(badge.id, None)
            result.append(b_dict)

        # Sort: unlocked first, then by badge ID
        result.sort(key=lambda x: (not x['unlocked'], x['id']))
        return result

    @staticmethod
    def process_completion_xp(user_id: int, habit_id: int, current_streak: int) -> Dict[str, Any]:
        """
        Calculates and credits XP for habit completion, including streak bonuses,
        and triggers badge unlock checks.
        
        Args:
            user_id: Identifier of the user.
            habit_id: Identifier of the completed habit.
            current_streak: The newly updated streak count.
            
        Returns:
            dict: Summary of earned XP, level progression, and any newly unlocked badges.
        """
        xp_earned = GamificationEngine.XP_COMPLETION

        # Streak milestone bonus calculation
        if current_streak == 7:
            xp_earned += GamificationEngine.XP_STREAK_7
        elif current_streak == 14:
            xp_earned += GamificationEngine.XP_STREAK_14
        elif current_streak == 30:
            xp_earned += GamificationEngine.XP_STREAK_30
        elif current_streak > 30 and current_streak % 7 == 0:
            xp_earned += GamificationEngine.XP_STREAK_RECURRING_7

        xp_result = GamificationEngine.add_xp(user_id, xp_earned, reason=f"habit_completion_streak_{current_streak}")

        # Check total completions across all habits
        total_completions = HabitLog.query.filter_by(user_id=user_id, status='completed').count()
        badges_unlocked = GamificationEngine.check_and_unlock_badges(user_id, current_streak, total_completions)

        return {
            'xp_earned': xp_earned,
            'xp_result': xp_result,
            'badges_unlocked': badges_unlocked
        }

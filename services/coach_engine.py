"""
HabitFlow Coach Engine
======================
This service generates rule-based behavioral insights, habit patterns, and motivational
coaching messages. It analyzes streak drops, periods of inactivity, day-of-week tendencies,
and correlations between emotional wellbeing (mood) and habit completion rates.
"""

import random
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional
from models import Habit, HabitLog, Mood, db


class CoachEngine:
    """Service providing motivational advice and behavioral analytics."""

    # Curated collection of habit formation and mindset quotes
    MOTIVATIONAL_QUOTES = [
        "Small steps taken consistently lead to massive transformations over time.",
        "Your future self will thank you for the habits you practice today.",
        "Consistency is the true gateway to mastery and personal freedom.",
        "You don't have to be extreme, just consistent.",
        "Every single day is a fresh opportunity to rebuild momentum.",
        "Progress over perfection — showing up is half the battle.",
        "You are what you repeatedly do. Excellence is a habit, not an act.",
        "Discipline is choosing between what you want now and what you want most.",
        "One small positive thought in the morning can change your whole day.",
        "Trust the process. Great achievements are composed of daily micro-habits."
    ]

    # Milestone celebration messages mapped to streak length in days
    STREAK_MESSAGES = {
        3: "🔥 3-day streak! You are establishing momentum!",
        7: "🌟 7 days straight! That's a full week of unwavering dedication!",
        14: "🚀 Two full weeks! Your habit loop is cementing into a permanent routine!",
        21: "🧠 21 days! Neuroplasticity in action — this habit is becoming second nature!",
        30: "👑 30 days! One whole month of consistency — you are a true Habit Master!",
        50: "⚡ 50 days strong! Halfway to the triple-digit milestone!",
        100: "💯 100 days! An extraordinary achievement of willpower and commitment!",
        365: "🎯 365 days! A full year of daily excellence — legendary status achieved!"
    }

    # Supportive messages when returning after a missed habit
    COMEBACK_MESSAGES = [
        "Missing a day happens to everyone. The secret to long-term success is never missing twice.",
        "Your past progress didn't vanish — today is the perfect moment to start your next great streak.",
        "A stumble is not a fall. Dust yourself off and tackle your habits today!",
        "Every master was once a beginner who refused to quit after a setback.",
        "Treat today as Day 1 of your greatest streak yet."
    ]

    @staticmethod
    def get_dashboard_message(user_id: int) -> str:
        """
        Generates a concise, personalized motivational greeting for the main dashboard header.
        
        Args:
            user_id: Identifier of the user.
            
        Returns:
            str: Motivational message tailored to user's current progress.
        """
        from services.streak_engine import StreakEngine
        stats = StreakEngine.calculate_stats_for_user(user_id)

        if stats['total_habits'] == 0:
            return "Welcome to HabitFlow! Create your very first habit to begin your journey."

        combined_streak = stats['combined_streak']
        if combined_streak == 0:
            return "Today is a brand new opportunity. Complete a habit today to ignite your streak!"
        elif combined_streak < 7:
            return f"Great start! You have {combined_streak} total streak days. Keep building momentum! 🔥"
        elif combined_streak < 30:
            return f"You're in the groove! {combined_streak} combined streak days across your habits. Awesome work! 🚀"
        else:
            return f"Unstoppable! {combined_streak} combined streak days. Your consistency is inspiring! 👑"

    @staticmethod
    def get_streak_milestone_message(habit_id: int, user_id: int, current_streak: int) -> Optional[str]:
        """
        Checks whether the newly achieved streak matches a notable milestone
        and returns an celebratory encouragement message.
        
        Args:
            habit_id: Identifier of the habit.
            user_id: Identifier of the user.
            current_streak: Newly updated streak value.
            
        Returns:
            str or None: Milestone message if applicable.
        """
        if current_streak in CoachEngine.STREAK_MESSAGES:
            return CoachEngine.STREAK_MESSAGES[current_streak]

        if current_streak > 30 and current_streak % 7 == 0:
            return f"🎉 {current_streak} days straight! Another full week conquered!"

        return None

    @staticmethod
    def detect_streak_drop(user_id: int) -> Optional[Dict[str, Any]]:
        """
        Analyzes the last 7 days to detect whether the user has experienced missed habits,
        providing empathetic encouragement rather than punitive messaging.
        
        Args:
            user_id: Identifier of the user.
            
        Returns:
            dict or None: Structured alert with comeback recommendation.
        """
        active_habits = Habit.query.filter_by(user_id=user_id, active=True).all()
        if not active_habits:
            return None

        seven_days_ago = date.today() - timedelta(days=7)
        recent_logs = HabitLog.query.filter(
            HabitLog.user_id == user_id,
            HabitLog.date >= seven_days_ago
        ).all()

        missed_count = sum(1 for log in recent_logs if log.status == 'missed')
        if missed_count > 0:
            return {
                'type': 'streak_drop',
                'icon': '🌱',
                'title': 'Fresh Start Available',
                'message': random.choice(CoachEngine.COMEBACK_MESSAGES),
                'missed_count': missed_count,
                'severity': 'medium' if missed_count <= 2 else 'high'
            }

        return None

    @staticmethod
    def detect_inactivity(user_id: int) -> Optional[Dict[str, Any]]:
        """
        Detects if the user has not logged any habits in 3 or more days.
        
        Args:
            user_id: Identifier of the user.
            
        Returns:
            dict or None: Inactivity notice if 3+ days have elapsed without activity.
        """
        last_log = HabitLog.query.filter_by(user_id=user_id).order_by(HabitLog.date.desc()).first()
        if not last_log:
            return None

        days_inactive = (date.today() - last_log.date).days
        if days_inactive >= 3:
            return {
                'type': 'inactivity',
                'icon': '⏰',
                'title': 'We Miss You!',
                'message': f"It has been {days_inactive} days since your last habit check-in. Take 2 minutes today to get back on track!",
                'days_since': days_inactive
            }

        return None

    @staticmethod
    def analyze_mood_habit_correlation(user_id: int) -> Optional[Dict[str, Any]]:
        """
        Analyzes statistical correlation between mood entries and habit completion rates.
        Calculates the completion percentage on happy days versus neutral/sad days.
        
        Args:
            user_id: Identifier of the user.
            
        Returns:
            dict or None: Correlation insight and comparative statistics.
        """
        thirty_days_ago = date.today() - timedelta(days=30)
        moods = Mood.query.filter(Mood.user_id == user_id, Mood.date >= thirty_days_ago).all()
        logs = HabitLog.query.filter(HabitLog.user_id == user_id, HabitLog.date >= thirty_days_ago).all()

        if len(moods) < 3 or len(logs) < 5:
            return None

        mood_by_date = {m.date: m.mood for m in moods}

        happy_completions = 0
        happy_total = 0
        other_completions = 0
        other_total = 0

        for log in logs:
            day_mood = mood_by_date.get(log.date)
            if day_mood == 'happy':
                happy_total += 1
                if log.status == 'completed':
                    happy_completions += 1
            elif day_mood in ('neutral', 'sad'):
                other_total += 1
                if log.status == 'completed':
                    other_completions += 1

        if happy_total == 0:
            return None

        happy_rate = int((happy_completions / happy_total) * 100)
        other_rate = int((other_completions / other_total) * 100) if other_total > 0 else happy_rate

        diff = happy_rate - other_rate
        if diff > 5:
            msg = f"You achieve a {happy_rate}% habit completion rate on happy days ({diff}% higher than other days). Positive emotions fuel your consistency!"
        else:
            msg = f"You maintain a solid {happy_rate}% completion rate on happy days. Keeping your habits going helps stabilize your emotional wellbeing!"

        return {
            'type': 'mood_correlation',
            'icon': '✨',
            'title': 'Mood & Habit Synergy',
            'message': msg,
            'happy_rate': happy_rate,
            'other_rate': other_rate
        }

    @staticmethod
    def get_best_day(user_id: int) -> Optional[Dict[str, Any]]:
        """
        Identifies which day of the week the user achieves the highest number of habit completions.
        
        Args:
            user_id: Identifier of the user.
            
        Returns:
            dict or None: Best weekday name, completion count, and encouragement message.
        """
        thirty_days_ago = date.today() - timedelta(days=30)
        completed_logs = HabitLog.query.filter(
            HabitLog.user_id == user_id,
            HabitLog.date >= thirty_days_ago,
            HabitLog.status == 'completed'
        ).all()

        if len(completed_logs) < 3:
            return None

        day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        day_counts = {i: 0 for i in range(7)}

        for log in completed_logs:
            day_counts[log.date.weekday()] += 1

        best_day_idx = max(day_counts, key=day_counts.get)
        best_count = day_counts[best_day_idx]
        best_name = day_names[best_day_idx]

        if best_count == 0:
            return None

        return {
            'type': 'best_day',
            'icon': '⭐',
            'title': f'Power Day: {best_name}',
            'day': best_name,
            'completions': best_count,
            'message': f"{best_name}s are your highest-performing days with {best_count} completed habits recently! Leverage this momentum."
        }

    @staticmethod
    def detect_weekend_warrior(user_id: int) -> Optional[Dict[str, Any]]:
        """
        Detects if user is particularly consistent on Saturday and Sunday.
        
        Args:
            user_id: Identifier of the user.
            
        Returns:
            dict or None: Weekend warrior badge insight if >= 40% of completions occur on weekends.
        """
        thirty_days_ago = date.today() - timedelta(days=30)
        completed_logs = HabitLog.query.filter(
            HabitLog.user_id == user_id,
            HabitLog.date >= thirty_days_ago,
            HabitLog.status == 'completed'
        ).all()

        total = len(completed_logs)
        if total < 6:
            return None

        weekend_completions = sum(1 for log in completed_logs if log.date.weekday() in (5, 6))
        ratio = weekend_completions / total

        if ratio >= 0.38:
            return {
                'type': 'weekend_warrior',
                'icon': '🛡️',
                'title': 'Weekend Warrior',
                'message': f"You thrive on weekends! Over {int(ratio * 100)}% of your recent completions happen on Saturday and Sunday."
            }

        return None

    @staticmethod
    def get_all_insights(user_id: int) -> List[Dict[str, Any]]:
        """
        Aggregates all behavioral analytics, pattern detections, and recommendations
        into a unified insights list for the dashboard.
        
        Args:
            user_id: Identifier of the user.
            
        Returns:
            list: List of structured insight dictionaries.
        """
        insights = []

        # 1. Streak drop detection
        drop = CoachEngine.detect_streak_drop(user_id)
        if drop:
            insights.append(drop)

        # 2. Inactivity detection
        inact = CoachEngine.detect_inactivity(user_id)
        if inact:
            insights.append(inact)

        # 3. Mood-Habit correlation
        mood_corr = CoachEngine.analyze_mood_habit_correlation(user_id)
        if mood_corr:
            insights.append(mood_corr)

        # 4. Best performing day of the week
        best = CoachEngine.get_best_day(user_id)
        if best:
            insights.append(best)

        # 5. Weekend pattern
        ww = CoachEngine.detect_weekend_warrior(user_id)
        if ww:
            insights.append(ww)

        # 6. Fallback motivational quote if few insights are triggered
        if len(insights) < 2:
            insights.append({
                'type': 'quote',
                'icon': '💡',
                'title': 'Coach Wisdom',
                'message': CoachEngine.get_random_quote()
            })

        return insights

    @staticmethod
    def get_random_quote() -> str:
        """
        Returns a random motivational habit formation quote.
        
        Returns:
            str: Inspiring quote text.
        """
        return random.choice(CoachEngine.MOTIVATIONAL_QUOTES)

"""
HabitFlow Coach Engine
======================
This service generates rule-based behavioral insights, habit patterns, and motivational
coaching messages. It analyzes streak drops, periods of inactivity, day-of-week tendencies,
and correlations between emotional wellbeing (mood) and habit completion rates.
"""

import random
from datetime import timedelta
from typing import Dict, Any, List, Optional
from date_utils import current_date
from models import Habit, HabitLog, Mood


class CoachEngine:
    """Service providing motivational advice and behavioral analytics."""

    # Curated collection of habit formation and mindset quotes
    MOTIVATIONAL_QUOTES = [
        "Small steps taken consistently lead to massive transformations over time.",
        "Your future self will thank you for the habits you practice today.",
        "Consistency is the true gateway to mastery and personal freedom.",
        "You don't have to be extreme, just consistent.",
        "Every single day is a fresh opportunity to rebuild momentum.",
        "Progress over perfection; showing up is half the battle.",
        "You are what you repeatedly do. Excellence is a habit, not an act.",
        "Discipline is choosing between what you want now and what you want most.",
        "One small positive thought in the morning can change your whole day.",
        "Trust the process. Great achievements are composed of daily micro-habits."
    ]

    # Milestone celebration messages mapped to streak length in days
    STREAK_MESSAGES = {
        3: "3-day streak! You are establishing momentum!",
        7: "7 days straight! That's a full week of unwavering dedication!",
        14: "Two full weeks! Your habit loop is cementing into a permanent routine!",
        21: "21 days of logged progress. Keep going at your own pace.",
        30: "30 days! One whole month of consistency - you are a true Habit Master!",
        50: "50 days strong! Halfway to the triple-digit milestone!",
        100: "100 days! An extraordinary achievement of willpower and commitment!",
        365: "365 days! A full year of daily excellence - legendary status achieved!"
    }

    # Supportive messages when returning after a missed habit
    COMEBACK_MESSAGES = [
        "Missing a day happens to everyone. The secret to long-term success is never missing twice.",
        "Your past progress did not vanish. Today is the perfect moment to start your next great streak.",
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
            return f"Great start! You have {combined_streak} total streak days. Keep building momentum!"
        elif combined_streak < 30:
            return f"You're in the groove! {combined_streak} combined streak days across your habits. Awesome work!"
        else:
            return f"Unstoppable! {combined_streak} combined streak days. Your consistency is inspiring!"

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
            return f"{current_streak} days straight! Another full week conquered!"

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

        today = current_date()
        seven_days_ago = today - timedelta(days=6)
        active_habit_ids = [habit.id for habit in active_habits]
        recent_logs = HabitLog.query.filter(
            HabitLog.user_id == user_id,
            HabitLog.habit_id.in_(active_habit_ids),
            HabitLog.date >= seven_days_ago,
            HabitLog.date <= today
        ).all()

        active_habits_by_id = {habit.id: habit for habit in active_habits}
        missed_count = sum(
            1 for log in recent_logs
            if log.status == 'missed'
            and log.date >= (active_habits_by_id[log.habit_id].created_date or log.date)
            and active_habits_by_id[log.habit_id].is_scheduled_for_date(log.date)
        )
        if missed_count > 0:
            return {
                'type': 'streak_drop',
                'icon': 'growth',
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
        today = current_date()
        active_habits = Habit.query.filter_by(user_id=user_id, active=True).all()
        active_habit_ids = [habit.id for habit in active_habits]
        if not active_habit_ids:
            return None
        last_log = HabitLog.query.filter(
            HabitLog.user_id == user_id,
            HabitLog.habit_id.in_(active_habit_ids),
            HabitLog.date <= today
        ).order_by(HabitLog.date.desc()).first()
        if not last_log:
            return None

        days_inactive = (today - last_log.date).days
        if days_inactive >= 3:
            return {
                'type': 'inactivity',
                'icon': 'alert',
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
        today = current_date()
        thirty_days_ago = today - timedelta(days=29)
        moods = Mood.query.filter(
            Mood.user_id == user_id,
            Mood.date >= thirty_days_ago,
            Mood.date <= today
        ).all()
        habits = [
            habit for habit in Habit.query.filter_by(user_id=user_id).all()
            if (habit.created_date is None or habit.created_date <= today)
            and (habit.archived_date is None or habit.archived_date >= thirty_days_ago)
        ]
        if not habits:
            return None
        habits_by_id = {habit.id: habit for habit in habits}
        logs = HabitLog.query.filter(
            HabitLog.user_id == user_id,
            HabitLog.habit_id.in_(habits_by_id),
            HabitLog.date >= thirty_days_ago,
            HabitLog.date <= today
        ).all()

        if len(moods) < 3:
            return None

        mood_by_date = {m.date: m.mood for m in moods}

        happy_completions = 0
        happy_total = 0
        other_completions = 0
        other_total = 0

        completed_by_date = {}
        for log in logs:
            if (
                log.status == 'completed'
                and log.date >= (habits_by_id[log.habit_id].created_date or log.date)
                and (
                    habits_by_id[log.habit_id].archived_date is None
                    or log.date <= habits_by_id[log.habit_id].archived_date
                )
                and habits_by_id[log.habit_id].is_scheduled_for_date(log.date)
            ):
                completed_by_date[log.date] = completed_by_date.get(log.date, 0) + 1

        for mood_date, day_mood in mood_by_date.items():
            scheduled = sum(
                mood_date >= (habit.created_date or mood_date)
                and (habit.archived_date is None or mood_date <= habit.archived_date)
                and habit.is_scheduled_for_date(mood_date)
                for habit in habits
            )
            if scheduled == 0:
                continue
            completed = completed_by_date.get(mood_date, 0)
            if day_mood == 'happy':
                happy_total += scheduled
                happy_completions += completed
            elif day_mood in ('neutral', 'sad'):
                other_total += scheduled
                other_completions += completed

        if happy_total + other_total == 0:
            return None

        if happy_total == 0:
            return None

        happy_rate = int((happy_completions / happy_total) * 100)
        other_rate = int((other_completions / other_total) * 100) if other_total > 0 else happy_rate

        diff = happy_rate - other_rate
        if diff > 5:
            msg = (
                f"You completed {happy_rate}% of scheduled habits on logged happy days "
                f"({diff} points higher than on other mood days). This is a pattern in your logs, not proof that mood causes completion."
            )
        else:
            msg = (
                f"You completed {happy_rate}% of scheduled habits on logged happy days. "
                "More matching mood and habit records can make this comparison clearer."
            )

        return {
            'type': 'mood_correlation',
            'icon': 'insight',
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
        today = current_date()
        start_date = today - timedelta(days=29)
        active_habits = Habit.query.filter_by(user_id=user_id, active=True).all()
        if not active_habits:
            return None
        habit_by_id = {habit.id: habit for habit in active_habits}
        logs = HabitLog.query.filter(
            HabitLog.user_id == user_id,
            HabitLog.habit_id.in_(habit_by_id),
            HabitLog.date >= start_date,
            HabitLog.date <= today,
        ).all()
        log_map = {(log.habit_id, log.date): log.status for log in logs}
        day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        day_counts = {i: {'completed': 0, 'scheduled': 0} for i in range(7)}
        target_day = start_date
        while target_day <= today:
            for habit in active_habits:
                if target_day < (habit.created_date or start_date) or not habit.is_scheduled_for_date(target_day):
                    continue
                status = log_map.get((habit.id, target_day))
                if target_day == today and status is None:
                    continue
                day_counts[target_day.weekday()]['scheduled'] += 1
                if status == 'completed':
                    day_counts[target_day.weekday()]['completed'] += 1
            target_day += timedelta(days=1)

        completed_total = sum(values['completed'] for values in day_counts.values())
        if completed_total < 3:
            return None
        best_day_idx = max(
            day_counts,
            key=lambda weekday: (
                day_counts[weekday]['completed'] / day_counts[weekday]['scheduled']
                if day_counts[weekday]['scheduled'] else 0,
                day_counts[weekday]['completed'],
            ),
        )
        best_count = day_counts[best_day_idx]['completed']
        best_rate = int(
            best_count / day_counts[best_day_idx]['scheduled'] * 100
        ) if day_counts[best_day_idx]['scheduled'] else 0
        best_name = day_names[best_day_idx]

        if best_count == 0:
            return None

        return {
            'type': 'best_day',
            'icon': 'star',
            'title': f'Power Day: {best_name}',
            'day': best_name,
            'completions': best_count,
            'rate': best_rate,
            'message': f"You completed {best_rate}% of scheduled habits on {best_name}s recently. Use that pattern to plan your routines."
        }

    @staticmethod
    def detect_weekend_warrior(user_id: int) -> Optional[Dict[str, Any]]:
        """
        Detects if user is particularly consistent on Saturday and Sunday.

        Args:
            user_id: Identifier of the user.

        Returns:
            dict or None: Weekend insight when at least 40% of scheduled weekend opportunities are completed.
        """
        today = current_date()
        start_date = today - timedelta(days=29)
        active_habits = Habit.query.filter_by(user_id=user_id, active=True).all()
        if not active_habits:
            return None
        habit_by_id = {habit.id: habit for habit in active_habits}
        logs = HabitLog.query.filter(
            HabitLog.user_id == user_id,
            HabitLog.habit_id.in_(habit_by_id),
            HabitLog.date >= start_date,
            HabitLog.date <= today,
        ).all()
        log_map = {(log.habit_id, log.date): log.status for log in logs}
        weekend_opportunities = 0
        weekend_completions = 0
        target_day = start_date
        while target_day <= today:
            for habit in active_habits:
                if target_day < (habit.created_date or start_date) or not habit.is_scheduled_for_date(target_day):
                    continue
                status = log_map.get((habit.id, target_day))
                if target_day == today and status is None:
                    continue
                if target_day.weekday() in (5, 6):
                    weekend_opportunities += 1
                    if status == 'completed':
                        weekend_completions += 1
            target_day += timedelta(days=1)

        weekend_rate = weekend_completions / weekend_opportunities if weekend_opportunities else 0
        if weekend_opportunities >= 6 and weekend_rate >= 0.40:
            return {
                'type': 'weekend_warrior',
                'icon': 'shield',
                'title': 'Weekend Warrior',
                'message': f"You completed {int(weekend_rate * 100)}% of scheduled weekend habits recently."
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
                'icon': 'tip',
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

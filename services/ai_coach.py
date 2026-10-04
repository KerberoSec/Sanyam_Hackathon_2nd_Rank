"""Rule-based coaching messages, habit suggestions, and activity comparisons."""

from datetime import datetime, timezone
from typing import Dict, Any, List
from date_utils import current_date


class AICoachService:
    """Generate deterministic coaching from the user's logged activity."""

    ENGINE_VERSION = "3.0.3"
    ENGINE_NAME = "HabitFlow Behavioral Engine"

    # Curated habit ideas grouped by common goals.
    GOAL_FRAMEWORKS = {
        'sleep': [
            {
                'title': 'Take a Screen Break Before Bed',
                'category': 'health',
                'icon': 'moon',
                'duration': '30 mins',
                'frequency': ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'],
                'why': 'A quieter period before bed can make it easier to settle into your evening routine.'
            },
            {
                'title': 'Make Your Bedroom Comfortable for Sleep',
                'category': 'health',
                'icon': 'sleep',
                'duration': '1 min',
                'frequency': ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'],
                'why': 'Adjust the room to a temperature and light level that feels comfortable to you.'
            },
            {
                'title': 'Choose a Calming Evening Drink',
                'category': 'health',
                'icon': 'wellness',
                'duration': '5 mins',
                'frequency': ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'],
                'why': 'A familiar caffeine-free drink can be part of a calming evening routine.'
            }
        ],
        'productivity': [
            {
                'title': 'Identify Top 1 Priority Before Noon',
                'category': 'productivity',
                'icon': 'timer',
                'duration': '3 mins',
                'frequency': ['monday', 'tuesday', 'wednesday', 'thursday', 'friday'],
                'why': 'Choosing one priority gives you a clear place to start.'
            },
            {
                'title': '25-Minute Focused Deep Sprint',
                'category': 'productivity',
                'icon': 'timer',
                'duration': '25 mins',
                'frequency': ['monday', 'tuesday', 'wednesday', 'thursday', 'friday'],
                'why': 'A short timed session can help you give one task your attention.'
            },
            {
                'title': 'Write Down Tomorrow’s First Task',
                'category': 'productivity',
                'icon': 'planning',
                'duration': '5 mins',
                'frequency': ['monday', 'tuesday', 'wednesday', 'thursday', 'friday'],
                'why': 'A brief end-of-day note makes it easier to find your starting point tomorrow.'
            }
        ],
        'fitness': [
            {
                'title': 'Morning 10 Push-ups or Mobility',
                'category': 'fitness',
                'icon': 'mobility',
                'duration': '3 mins',
                'frequency': ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'],
                'why': 'A short movement break is a simple way to add activity to your day.'
            },
            {
                'title': '20-Minute Post-Lunch Brisk Walk',
                'category': 'fitness',
                'icon': 'walking',
                'duration': '20 mins',
                'frequency': ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'],
                'why': 'A short walk after lunch adds movement to your daily routine.'
            },
            {
                'title': 'Drink a Glass of Water',
                'category': 'health',
                'icon': 'hydration',
                'duration': '1 min',
                'frequency': ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'],
                'why': 'Keeping water nearby can serve as a simple reminder to drink.'
            }
        ],
        'mindfulness': [
            {
                'title': 'Box Breathing 4-4-4-4 for 3 Mins',
                'category': 'health',
                'icon': 'mindfulness',
                'duration': '3 mins',
                'frequency': ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'],
                'why': 'A paced breathing exercise offers a short pause in your day.'
            },
            {
                'title': 'Gratitude Log 3 Specific Micro-Wins',
                'category': 'learning',
                'icon': 'planning',
                'duration': '4 mins',
                'frequency': ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'],
                'why': 'Writing down a few small wins gives you a place to notice what went well.'
            },
            {
                'title': 'Unplugged 10-Minute Mindful Walk',
                'category': 'health',
                'icon': 'walking',
                'duration': '10 mins',
                'frequency': ['monday', 'wednesday', 'friday', 'sunday'],
                'why': 'A screen-free walk gives you a short break from your devices.'
            }
        ],
        'learning': [
            {
                'title': 'Read 10 Pages of Non-Fiction',
                'category': 'learning',
                'icon': 'planning',
                'duration': '15 mins',
                'frequency': ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'],
                'why': 'A small reading goal makes it easier to keep learning on your schedule.'
            },
            {
                'title': 'Summarize 1 Key Concept in Your Own Words',
                'category': 'learning',
                'icon': 'planning',
                'duration': '5 mins',
                'frequency': ['monday', 'tuesday', 'wednesday', 'thursday', 'friday'],
                'why': 'Explaining a concept in your own words is a useful way to review it.'
            },
            {
                'title': 'Practice Active Skill Drill for 15 Mins',
                'category': 'productivity',
                'icon': 'timer',
                'duration': '15 mins',
                'frequency': ['monday', 'wednesday', 'friday'],
                'why': 'A short practice session gives you time to work on one part of a skill.'
            }
        ]
    }

    # Core motivational guidance bank categorized by state
    FALLBACK_MESSAGES = {
        'daily': "Keep your momentum going! Every single completion lays another brick in your foundation of consistency.",
        'weekly': "Great effort this week! Consistency compounds over time. Celebrate your wins and set your intentions for next week.",
        'recommendation': "Start small with a micro-habit (<2 minutes). Anchor it immediately to an existing daily routine.",
        'mood': "Mood and routine patterns can vary together. Use your check-ins as personal context, and be kind to yourself on harder days."
    }

    @classmethod
    def generate_daily_coach_message(cls, user_stats: Dict[str, Any], user_habits: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Synthesizes active habits, longest and current streaks, and psychological
        principles into a tailored daily coaching directive.

        Args:
            user_stats: Aggregate user statistics (streaks, completions, consistency).
            user_habits: Active habits currently tracked.

        Returns:
            dict: Generated coaching message with metadata.
        """
        current = user_stats.get('combined_streak', user_stats.get('total_streak_days', 0))
        total_comps = user_stats.get('total_completions', 0)
        consistency = user_stats.get('consistency_score', user_stats.get('consistency_30d', 0))
        habit_count = len(user_habits)

        weekday_name = current_date().strftime("%A")

        # Select a message from the user's current activity summary.
        if habit_count == 0:
            msg = (
                "Welcome to HabitFlow! The secret of getting ahead is getting started. "
                "Create your first micro-habit today to activate your streak engine."
            )
        elif current == 0 and total_comps == 0:
            msg = (
                f"Happy {weekday_name}! You have {habit_count} active habit{'s' if habit_count > 1 else ''}. "
                "Pick one small action to make your first check-in simple."
            )
        elif current >= 30:
            msg = (
                f"Your active streaks add up to {current} days across your routines. "
                "Keep today's next step manageable and repeatable."
            )
        elif current >= 14:
            msg = (
                f"Your routines add up to {current} active streak days. "
                "Keep the next step easy to start."
            )
        elif current >= 7:
            msg = f"Your active streaks add up to {current} days. Choose one routine and keep its next step manageable."
        elif consistency >= 75:
            msg = (
                f"Your 30-day consistency score is {consistency}%. "
                f"Choose one upcoming habit and make it easy to start this {weekday_name}."
            )
        elif current > 0:
            msg = (
                f"Active momentum: {current} streak day{'s' if current > 1 else ''} in motion! "
                "Small, repeatable actions can be easier to maintain than occasional bursts."
            )
        else:
            msg = (
                "Every day is a fresh opportunity to reset and reignite your routines. "
                "Select your most accessible habit and log it early to rebuild momentum."
            )

        return {
            'message': msg,
            'source': 'behavioral_engine',
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'error': None
        }

    @classmethod
    def generate_weekly_summary(cls, user_stats: Dict[str, Any], user_habits: List[Dict[str, Any]],
                                weekly_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Synthesizes weekly performance metrics into a reflective summary.

        Args:
            user_stats: Aggregate user metrics.
            user_habits: Active habits.
            weekly_data: 7-day completion and skip tallies.

        Returns:
            dict: Structured weekly performance summary.
        """
        total_completed_this_week = sum(d.get('completed', 0) for d in weekly_data)
        total_skipped_this_week = sum(d.get('skipped', 0) for d in weekly_data)

        best_day = "mid-week"
        max_c = -1
        for d in weekly_data:
            if d.get('completed', 0) > max_c:
                max_c = d.get('completed', 0)
                best_day = d.get('day', 'mid-week')

        consistency = user_stats.get('consistency_score', user_stats.get('consistency_30d', 0))

        if total_completed_this_week == 0:
            summary = (
                "Weekly review: No habits were logged over the last 7 days. "
                "Focus on scheduling 1 friction-free routine to build momentum for the upcoming week."
            )
        elif total_completed_this_week >= 15:
            summary = (
                f"Exceptional performance over the last 7 days: {total_completed_this_week} habit completions "
                f"with peak execution on {best_day}. Your 30-day consistency score is {consistency}%."
            )
        elif total_completed_this_week >= 7:
            summary = (
                f"Solid execution over the last 7 days: {total_completed_this_week} total completions "
                f"({total_skipped_this_week} excused skips). {best_day} was your most productive day. "
                "Carry this momentum forward into next week."
            )
        else:
            summary = (
                f"Good foundational progress: {total_completed_this_week} completions logged over the last 7 days. "
                "Prioritize earlier completion windows to reduce end-of-day friction."
            )

        return {
            'summary': summary,
            'source': 'behavioral_engine',
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'error': None
        }

    @classmethod
    def generate_habit_recommendations(cls, user_goal: str, user_stats: Dict[str, Any],
                                       existing_habits: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Selects up to three goal-matched ideas from the local suggestion library.

        Args:
            user_goal: Stated goal or challenge keyword.
            user_stats: Aggregate user statistics.
            existing_habits: Existing habits to avoid duplicate titles.

        Returns:
            dict: List of 3 recommended micro-habits with rationale.
        """
        clean_goal = (user_goal or '').lower().strip()
        existing_titles = [h.get('title', '').lower() for h in existing_habits]

        # Categorize goal to domain
        target_domain = 'productivity'
        if any(w in clean_goal for w in ['sleep', 'rest', 'night', 'tired', 'insomnia']):
            target_domain = 'sleep'
        elif any(w in clean_goal for w in ['fit', 'gym', 'workout', 'muscle', 'exercise', 'weight', 'health', 'cardio']):
            target_domain = 'fitness'
        elif any(w in clean_goal for w in ['mind', 'stress', 'peace', 'anxiety', 'meditat', 'calm', 'zen']):
            target_domain = 'mindfulness'
        elif any(w in clean_goal for w in ['learn', 'read', 'book', 'study', 'focus', 'skill', 'code', 'write']):
            target_domain = 'learning'

        candidates = cls.GOAL_FRAMEWORKS.get(target_domain, cls.GOAL_FRAMEWORKS['productivity'])

        # Filter out existing duplicates or provide contextual alternatives
        recommendations = []
        for cand in candidates:
            if cand['title'].lower() not in existing_titles:
                recommendations.append(cand)

        # Fill from other domains when the user's existing habits overlap the
        # best matching domain. Return fewer only when every built-in option
        # is already represented.
        if len(recommendations) < 3:
            alt_pool = [
                item
                for framework in cls.GOAL_FRAMEWORKS.values()
                for item in framework
            ]
            for alt in alt_pool:
                if alt['title'].lower() not in existing_titles and alt not in recommendations:
                    recommendations.append(alt)
                if len(recommendations) == 3:
                    break

        return {
            'recommendations': recommendations[:3],
            'source': 'behavioral_engine',
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'error': None
        }

    @classmethod
    def analyze_mood_habit_correlation(cls, daily_records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Compares completion rates on mood-logged days using matched daily data.

        Args:
            daily_records: Entries with mood, completed scheduled habits, and
                scheduled habit opportunities for the same date.

        Returns:
            dict: Formatted insight text with metadata.
        """
        if not daily_records or len(daily_records) < 3:
            return {
                'insight': (
                    "Log your mood alongside scheduled habits on at least 3 days "
                    "to compare your daily patterns."
                ),
                'happy_percent': None,
                'source': 'behavioral_engine',
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'error': None
            }

        happy_days = [row for row in daily_records if row.get('mood') == 'happy']
        other_days = [row for row in daily_records if row.get('mood') in ('neutral', 'sad')]
        happy_percent = round((len(happy_days) / len(daily_records)) * 100)

        happy_total = sum(max(0, row.get('scheduled', 0)) for row in happy_days)
        happy_completed = sum(max(0, row.get('completed', 0)) for row in happy_days)
        other_total = sum(max(0, row.get('scheduled', 0)) for row in other_days)
        other_completed = sum(max(0, row.get('completed', 0)) for row in other_days)

        if not happy_total:
            insight = "No scheduled habits fell on your logged happy days, so there is not enough matching data to compare yet."
            happy_rate = None
            other_rate = int((other_completed / other_total) * 100) if other_total else None
        else:
            happy_rate = int((happy_completed / happy_total) * 100)
            other_rate = int((other_completed / other_total) * 100) if other_total else None
            if other_rate is None:
                insight = f"You completed {happy_rate}% of scheduled habits on your logged happy days. Log other moods to compare patterns."
            else:
                insight = (
                    f"You completed {happy_rate}% of scheduled habits on logged happy days and "
                    f"{other_rate}% on neutral or sad days. This is a pattern in your logs, not evidence that mood causes completion."
                )

        return {
            'insight': insight,
            'happy_percent': happy_percent,
            'happy_rate': happy_rate,
            'other_rate': other_rate,
            'source': 'behavioral_engine',
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'error': None
        }

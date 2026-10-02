"""
HabitFlow AI Coach Service
==========================
This service leverages Google Gemini generative AI to provide personalized,
adaptive behavioral coaching, habit recommendations, weekly performance reviews,
and emotional correlation insights.

Graceful Degradation:
If the Gemini API key is not configured, the network is unavailable, or quota limits
are exceeded, the service seamlessly falls back to dynamic, algorithmic coaching advice
generated from actual user metrics and behavioral science principles.
"""

import os
import json
import re
from datetime import datetime, date, timezone
from typing import Dict, Any, List, Optional

# Attempt to import Google Generative AI library
try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    genai = None
    GENAI_AVAILABLE = False


class AICoachService:
    """Service class managing AI-powered coaching interactions."""

    DEFAULT_MODEL = "gemini-1.5-flash"

    # Fallback message templates categorized by coaching interaction type
    FALLBACK_MESSAGES = {
        'daily': "Keep your momentum going! Every single completion lays another brick in your foundation of consistency.",
        'weekly': "Great effort this week! Consistency compounds over time. Celebrate your wins and set your intentions for next week.",
        'recommendation': "Start small with a micro-habit (<2 minutes). Anchor it immediately to an existing daily routine.",
        'mood': "Your emotional wellbeing and physical habits are intimately linked. Prioritize self-care on low-energy days."
    }

    @staticmethod
    def get_api_key() -> Optional[str]:
        """
        Retrieves the Gemini API key from environment variables.
        
        Returns:
            str or None: Configured API key if present.
        """
        return os.environ.get('GEMINI_API_KEY', None)

    @classmethod
    def is_available(cls) -> bool:
        """
        Verifies whether the Gemini library is installed and an API key is provided.
        
        Returns:
            bool: True if AI generation can be attempted, False otherwise.
        """
        api_key = cls.get_api_key()
        return bool(GENAI_AVAILABLE and api_key and api_key.strip() and not api_key.startswith('your-'))

    @classmethod
    def _init_genai(cls) -> bool:
        """
        Initializes and configures the Gemini SDK with the active API key.
        
        Returns:
            bool: True if initialization succeeded, False otherwise.
        """
        if not cls.is_available():
            return False
        try:
            genai.configure(api_key=cls.get_api_key())
            return True
        except Exception as e:
            print(f"Warning: Failed to configure Gemini API: {e}")
            return False

    @classmethod
    def generate_daily_coach_message(cls, user_stats: Dict[str, Any], user_habits: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Generates a concise, personalized daily motivation message based on user stats.
        
        Args:
            user_stats: Dictionary containing total habits, completions, streak, consistency score.
            user_habits: List of active habit dictionaries.
            
        Returns:
            dict: Generated message, timestamp, model used, or fallback message.
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        # Dynamic fallback based on real stats
        streak = user_stats.get('combined_streak', 0)
        completions = user_stats.get('total_completions', 0)
        consistency = user_stats.get('consistency_score', 0)

        if streak > 14:
            fallback = f"Incredible consistency! With a {streak}-day combined streak and {consistency}% consistency, your habit loops are deeply ingrained. Keep this powerhouse momentum going today!"
        elif streak > 3:
            fallback = f"You're building solid traction with {streak} consecutive streak days! Focus on executing your key habits today to keep the fire burning."
        elif completions > 0:
            fallback = f"Every day is a fresh opportunity to build upon your {completions} lifetime completions. Pick your most important habit first and conquer it early today!"
        else:
            fallback = "The journey of a thousand miles begins with a single step. Complete just one habit today to ignite your very first streak!"

        if not cls.is_available():
            return {
                'message': fallback,
                'generated_at': now_iso,
                'cached': False,
                'source': 'algorithm'
            }

        try:
            cls._init_genai()
            context = cls._build_user_context(user_stats, user_habits)
            prompt = f"""You are a warm, supportive, and scientifically grounded habit coach.
Analyze the user's current progress:
{context}

Generate a concise, encouraging daily message (2 to 3 sentences maximum):
1. Acknowledge their specific progress or encourage their fresh start.
2. Provide ONE actionable behavioral tip (e.g. habit stacking, 2-minute rule, or implementation intention).
3. Keep the tone inspiring, direct, and human. Avoid clichés and generic platitudes."""

            model = genai.GenerativeModel(cls.DEFAULT_MODEL)
            response = model.generate_content(prompt)
            message = response.text.strip() if response and response.text else fallback

            return {
                'message': message,
                'generated_at': now_iso,
                'cached': False,
                'source': 'gemini'
            }
        except Exception as e:
            print(f"Gemini API Error (daily): {e}")
            return {
                'message': fallback,
                'generated_at': now_iso,
                'cached': False,
                'source': 'fallback',
                'error': str(e)
            }

    @classmethod
    def generate_weekly_summary(cls, user_stats: Dict[str, Any], user_habits: List[Dict[str, Any]],
                                weekly_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Generates a comprehensive weekly performance review analyzing consistency,
        identifying strongest days, and offering tactical behavioral advice.
        
        Args:
            user_stats: Summary user statistics.
            user_habits: Active habits list.
            weekly_data: Day-by-day weekly breakdown from analytics.
            
        Returns:
            dict: Summary text, timestamp, and source.
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        # Dynamic fallback review
        total_completions = sum(d.get('completed', 0) for d in weekly_data)
        best_day = max(weekly_data, key=lambda d: d.get('completed', 0)) if weekly_data else None
        best_day_str = best_day.get('day', 'midweek') if best_day else 'midweek'

        fallback = (
            f"Weekly Performance Review: You recorded {total_completions} completions this past week, "
            f"with {best_day_str} standing out as your strongest day. "
            "To sustain this momentum next week, prepare your environment the night before and anchor your hardest habit to your morning routine."
        )

        if not cls.is_available():
            return {
                'summary': fallback,
                'generated_at': now_iso,
                'source': 'algorithm'
            }

        try:
            cls._init_genai()
            user_ctx = cls._build_user_context(user_stats, user_habits)
            weekly_ctx = cls._build_weekly_context(weekly_data)

            prompt = f"""You are a behavioral psychologist reviewing a client's weekly habit performance.
User Profile:
{user_ctx}

Weekly Log Breakdown:
{weekly_ctx}

Write a structured weekly review (3-4 sentences):
1. Highlight positive achievements and pattern recognition (e.g. peak days).
2. Offer one specific behavioral tweak (e.g. temptation bundling, friction reduction).
3. Conclude with an empowering forward-looking reflection for the week ahead."""

            model = genai.GenerativeModel(cls.DEFAULT_MODEL)
            response = model.generate_content(prompt)
            summary = response.text.strip() if response and response.text else fallback

            return {
                'summary': summary,
                'generated_at': now_iso,
                'source': 'gemini'
            }
        except Exception as e:
            print(f"Gemini API Error (weekly): {e}")
            return {
                'summary': fallback,
                'generated_at': now_iso,
                'source': 'fallback',
                'error': str(e)
            }

    @classmethod
    def generate_habit_recommendations(cls, user_goal: str, user_stats: Dict[str, Any],
                                       existing_habits: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Generates 3 actionable micro-habits tailored to the user's stated goal
        (e.g., 'better focus', 'deep sleep', 'stress reduction', 'fitness').
        
        Args:
            user_goal: User's goal text.
            user_stats: Current user statistics.
            existing_habits: Current active habits.
            
        Returns:
            dict: List of recommended habit objects with title, category, icon, frequency, and rationale.
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        # Goal-based curated fallback library
        goal_lower = user_goal.lower() if user_goal else "productivity"
        fallback_library = {
            'sleep': [
                {'title': 'Screen Off 30m Before Bed', 'category': 'health', 'icon': '🌙', 'frequency': ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'], 'why': 'Reduces blue light exposure to promote natural melatonin production.', 'duration': '30 mins'},
                {'title': '5-Minute Bedroom Reset', 'category': 'health', 'icon': '🛏️', 'frequency': ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'], 'why': 'An uncluttered sleeping space lowers cognitive arousal before sleep.', 'duration': '5 mins'},
                {'title': 'Nighttime Chamomile Tea', 'category': 'health', 'icon': '🍵', 'frequency': ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'], 'why': 'Creates a consistent sensory cue signaling your nervous system to unwind.', 'duration': '10 mins'}
            ],
            'focus': [
                {'title': 'Pomodoro Session (25 min)', 'category': 'productivity', 'icon': '⏱️', 'frequency': ['monday', 'tuesday', 'wednesday', 'thursday', 'friday'], 'why': 'Structured intervals minimize cognitive fatigue and prevent context switching.', 'duration': '25 mins'},
                {'title': 'Morning Top 3 Tasks List', 'category': 'productivity', 'icon': '📝', 'frequency': ['monday', 'tuesday', 'wednesday', 'thursday', 'friday'], 'why': 'Identifies highest-leverage priorities before email and messages create reactive bias.', 'duration': '5 mins'},
                {'title': '5-Minute Mindful Breathing', 'category': 'health', 'icon': '🧘', 'frequency': ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'], 'why': 'Activates the parasympathetic nervous system to improve executive attention.', 'duration': '5 mins'}
            ],
            'fitness': [
                {'title': '15-Minute Morning Mobility', 'category': 'fitness', 'icon': '🤸', 'frequency': ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'], 'why': 'Increases synovial fluid circulation and primes motor neural pathways.', 'duration': '15 mins'},
                {'title': 'Hydrate: 500ml Water on Waking', 'category': 'health', 'icon': '💧', 'frequency': ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'], 'why': 'Replaces nighttime fluid loss and jumpstarts metabolic cellular function.', 'duration': '1 min'},
                {'title': '10-Minute Post-Lunch Walk', 'category': 'fitness', 'icon': '🚶', 'frequency': ['monday', 'tuesday', 'wednesday', 'thursday', 'friday'], 'why': 'Blunts postprandial glucose spikes and prevents afternoon fatigue slumps.', 'duration': '10 mins'}
            ]
        }

        # Select closest matching fallback
        matched_key = 'productivity'
        for key in fallback_library:
            if key in goal_lower:
                matched_key = key
                break
        fallback_recommendations = fallback_library.get(matched_key, fallback_library['focus'])

        if not cls.is_available():
            return {
                'recommendations': fallback_recommendations,
                'goal': user_goal,
                'generated_at': now_iso,
                'source': 'library'
            }

        try:
            cls._init_genai()
            context = cls._build_user_context(user_stats, existing_habits)
            prompt = f"""You are an elite habit formation specialist.
User Goal: {user_goal}
User Profile:
{context}

Recommend EXACTLY 3 micro-habits specifically tailored to this goal.
Rules:
- Each habit must take less than 15 minutes.
- Provide output strictly as a JSON array of 3 objects with keys:
  "title" (string), "category" ("health", "fitness", "learning", "productivity", "general"),
  "icon" (single emoji), "frequency" (list of weekday names in lowercase),
  "why" (1 concise sentence explaining the psychological benefit),
  "duration" (string, e.g. "5 mins").

Return ONLY valid raw JSON with no markdown wrapping or additional text."""

            model = genai.GenerativeModel(cls.DEFAULT_MODEL)
            response = model.generate_content(prompt)
            raw_text = response.text.strip() if response and response.text else ""

            # Extract JSON block
            if "```json" in raw_text:
                raw_text = raw_text.split("```json")[1].split("```")[0]
            elif "```" in raw_text:
                raw_text = raw_text.split("```")[1].split("```")[0]

            recommendations = json.loads(raw_text.strip())
            if not isinstance(recommendations, list) or len(recommendations) == 0:
                recommendations = fallback_recommendations

            return {
                'recommendations': recommendations,
                'goal': user_goal,
                'generated_at': now_iso,
                'source': 'gemini'
            }
        except Exception as e:
            print(f"Gemini API Error (recommendations): {e}")
            return {
                'recommendations': fallback_recommendations,
                'goal': user_goal,
                'generated_at': now_iso,
                'source': 'fallback',
                'error': str(e)
            }

    @classmethod
    def analyze_mood_habit_correlation(cls, user_moods: List[Dict[str, Any]], completion_rate: int) -> Dict[str, Any]:
        """
        Translates raw mood tracking data and completion statistics into an emotionally
        intelligent, supportive behavioral insight.
        
        Args:
            user_moods: List of recent mood check-in dictionaries.
            completion_rate: Overall habit completion percentage.
            
        Returns:
            dict: Insight text, happy percentage, and source.
        """
        now_iso = datetime.now(timezone.utc).isoformat()

        happy_count = sum(1 for m in user_moods if m.get('mood') == 'happy')
        total_moods = len(user_moods)
        happy_pct = int((happy_count / total_moods) * 100) if total_moods > 0 else 50

        fallback = (
            f"You have felt positive on {happy_pct}% of tracked days. "
            "Data demonstrates that regular habits stabilize mood, while small positive rituals build emotional resilience."
        )

        if not cls.is_available():
            return {
                'insight': fallback,
                'happy_percent': happy_pct,
                'generated_at': now_iso,
                'source': 'algorithm'
            }

        try:
            cls._init_genai()
            prompt = f"""You are an emotional wellbeing coach.
The user tracked {total_moods} mood days: {happy_count} happy ({happy_pct}%).
Their current habit completion rate is {completion_rate}%.

Write an insightful, validating 2-sentence observation connecting their emotional states
with daily habit practice. Conclude with a compassionate takeaway."""

            model = genai.GenerativeModel(cls.DEFAULT_MODEL)
            response = model.generate_content(prompt)
            insight = response.text.strip() if response and response.text else fallback

            return {
                'insight': insight,
                'happy_percent': happy_pct,
                'generated_at': now_iso,
                'source': 'gemini'
            }
        except Exception as e:
            print(f"Gemini API Error (mood): {e}")
            return {
                'insight': fallback,
                'happy_percent': happy_pct,
                'generated_at': now_iso,
                'source': 'fallback',
                'error': str(e)
            }

    @staticmethod
    def _build_user_context(stats: Dict[str, Any], habits: List[Dict[str, Any]]) -> str:
        """Formats statistics and habits into structured prompt context."""
        lines = [
            f"- Active Habits Count: {stats.get('total_habits', 0)}",
            f"- Combined Streaks: {stats.get('combined_streak', 0)} days",
            f"- Lifetime Completions: {stats.get('total_completions', 0)}",
            f"- 30-Day Consistency Score: {stats.get('consistency_score', 0)}%",
            f"- User Level: {stats.get('level', 1)}"
        ]
        if habits:
            titles = [h.get('title', 'Habit') for h in habits[:5]]
            lines.append(f"- Sample Habits: {', '.join(titles)}")
        return "\n".join(lines)

    @staticmethod
    def _build_weekly_context(weekly_data: List[Dict[str, Any]]) -> str:
        """Formats weekly breakdown into structured prompt context."""
        lines = []
        for day_item in weekly_data:
            day_name = day_item.get('day', 'Day')
            completed = day_item.get('completed', 0)
            rate = day_item.get('rate', 0)
            lines.append(f"- {day_name}: {completed} completed ({rate}% rate)")
        return "\n".join(lines)

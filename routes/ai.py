"""
HabitFlow AI Coaching Routes
============================
This module exposes REST API endpoints for AI-driven coaching features:
- GET  /api/ai/daily-message: Daily personalized behavioral motivational guidance.
- GET  /api/ai/weekly-summary: Comprehensive weekly review and pattern recognition.
- POST /api/ai/habit-recommendations: Smart micro-habit recommendations based on personal goals.
- GET  /api/ai/mood-insights: Emotional intelligence analysis correlating mood and habits.
- GET  /api/ai/health: Diagnostic status of the AI coaching service and model availability.
"""

from datetime import date, datetime, timedelta, timezone
from flask import Blueprint, request, jsonify
from models import User, AIMessage, Habit, db
from routes.auth import token_required
from services.ai_coach import AICoachService
from services.streak_engine import StreakEngine

ai_bp = Blueprint('ai', __name__, url_prefix='/api/ai')


@ai_bp.route('/daily-message', methods=['GET'])
@token_required
def get_daily_message(current_user: User):
    """
    Retrieves or generates today's personalized daily habit coaching message.
    Checks the database cache first to conserve external API quota and minimize latency.
    Pass `?refresh=true` to force a new message generation.
    
    Args:
        current_user: Authenticated User object.
        
    Returns:
        JSON response with the coaching message, cached status, and generation metadata.
    """
    today = date.today()
    force_refresh = request.args.get('refresh', '').lower() in ('true', '1', 'yes')

    # Check database cache unless refresh was explicitly requested
    if not force_refresh:
        cached = AIMessage.query.filter_by(
            user_id=current_user.id,
            message_type='daily',
            date=today
        ).first()

        if cached:
            return jsonify({
                'message': cached.content,
                'cached': True,
                'generated_at': cached.generated_at.isoformat(),
                'source': 'cache'
            }), 200

    # Aggregate current user statistics and active habits for context
    stats = StreakEngine.calculate_stats_for_user(current_user.id)
    active_habits = [h.to_dict() for h in current_user.habits.filter_by(active=True).all()]

    # Generate coaching message (Gemini or algorithmic fallback)
    result = AICoachService.generate_daily_coach_message(stats, active_habits)
    message_text = result.get('message', AICoachService.FALLBACK_MESSAGES['daily'])

    # Save or update cache in database
    existing_record = AIMessage.query.filter_by(
        user_id=current_user.id,
        message_type='daily',
        date=today
    ).first()

    if existing_record:
        existing_record.content = message_text
        existing_record.generated_at = datetime.now(timezone.utc)
    else:
        new_record = AIMessage(
            user_id=current_user.id,
            message_type='daily',
            content=message_text,
            date=today,
            cached=True
        )
        db.session.add(new_record)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Warning: Failed to cache daily AI message: {e}")

    return jsonify({
        'message': message_text,
        'cached': False,
        'generated_at': result.get('generated_at', datetime.now(timezone.utc).isoformat()),
        'source': result.get('source', 'generated'),
        'error': result.get('error', None)
    }), 200


@ai_bp.route('/weekly-summary', methods=['GET'])
@token_required
def get_weekly_summary(current_user: User):
    """
    Retrieves or generates a weekly habit performance review.
    Analyzes completions across days of the week, highlights peak consistency,
    and offers behavioral psychology recommendations.
    
    Args:
        current_user: Authenticated User object.
        
    Returns:
        JSON response with the weekly summary review.
    """
    from routes.analytics import get_weekly_completion_data

    today = date.today()
    force_refresh = request.args.get('refresh', '').lower() in ('true', '1', 'yes')

    # Check cache for today
    if not force_refresh:
        cached = AIMessage.query.filter_by(
            user_id=current_user.id,
            message_type='weekly',
            date=today
        ).first()

        if cached:
            return jsonify({
                'summary': cached.content,
                'cached': True,
                'generated_at': cached.generated_at.isoformat(),
                'source': 'cache'
            }), 200

    # Collect stats and weekly breakdown
    stats = StreakEngine.calculate_stats_for_user(current_user.id)
    active_habits = [h.to_dict() for h in current_user.habits.filter_by(active=True).all()]
    weekly_data = get_weekly_completion_data(current_user.id)

    # Generate review
    result = AICoachService.generate_weekly_summary(stats, active_habits, weekly_data)
    summary_text = result.get('summary', AICoachService.FALLBACK_MESSAGES['weekly'])

    # Cache handling with unique constraint protection
    existing_record = AIMessage.query.filter_by(
        user_id=current_user.id,
        message_type='weekly',
        date=today
    ).first()

    if existing_record:
        existing_record.content = summary_text
        existing_record.generated_at = datetime.now(timezone.utc)
    else:
        new_record = AIMessage(
            user_id=current_user.id,
            message_type='weekly',
            content=summary_text,
            date=today,
            cached=True
        )
        db.session.add(new_record)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Warning: Failed to cache weekly AI summary: {e}")

    return jsonify({
        'summary': summary_text,
        'cached': False,
        'generated_at': result.get('generated_at', datetime.now(timezone.utc).isoformat()),
        'source': result.get('source', 'generated'),
        'error': result.get('error', None)
    }), 200


@ai_bp.route('/habit-recommendations', methods=['POST'])
@token_required
def get_habit_recommendations(current_user: User):
    """
    Recommends 3 small micro-habits based on a user's stated goal
    (e.g., 'better sleep', 'deep work focus', 'strength training', 'mindfulness').
    
    Expected JSON Body:
        { "goal": "better sleep" }
        
    Returns:
        JSON response with 3 recommended micro-habits and rationale.
    """
    data = request.get_json(silent=True) or {}
    user_goal = data.get('goal', 'better focus and productivity').strip()

    stats = StreakEngine.calculate_stats_for_user(current_user.id)
    existing_habits = [h.to_dict() for h in current_user.habits.filter_by(active=True).all()]

    result = AICoachService.generate_habit_recommendations(user_goal, stats, existing_habits)

    return jsonify({
        'goal': user_goal,
        'recommendations': result.get('recommendations', []),
        'generated_at': result.get('generated_at', datetime.now(timezone.utc).isoformat()),
        'source': result.get('source', 'library'),
        'error': result.get('error', None)
    }), 200


@ai_bp.route('/mood-insights', methods=['GET'])
@token_required
def get_mood_insights(current_user: User):
    """
    Analyzes the correlation between the user's logged emotional wellbeing
    and their habit completion consistency over the past 30 days.
    
    Args:
        current_user: Authenticated User object.
        
    Returns:
        JSON response with emotional correlation insights.
    """
    thirty_days_ago = date.today() - timedelta(days=30)
    from models import Mood
    recent_moods = Mood.query.filter(
        Mood.user_id == current_user.id,
        Mood.date >= thirty_days_ago
    ).all()

    if not recent_moods:
        return jsonify({
            'insight': 'Log your daily mood alongside your habits to unlock personalized emotional wellness insights!',
            'happy_percent': None,
            'source': 'default',
            'error': 'No mood data recorded yet'
        }), 200

    mood_dicts = [m.to_dict() for m in recent_moods]
    stats = StreakEngine.calculate_stats_for_user(current_user.id)
    completion_rate = stats.get('consistency_score', 0)

    result = AICoachService.analyze_mood_habit_correlation(mood_dicts, completion_rate)

    return jsonify({
        'insight': result.get('insight', 'Habits and mood reinforce each other.'),
        'happy_percent': result.get('happy_percent', 0),
        'generated_at': result.get('generated_at', datetime.now(timezone.utc).isoformat()),
        'source': result.get('source', 'algorithm'),
        'error': result.get('error', None)
    }), 200


@ai_bp.route('/health', methods=['GET'])
def ai_health_check():
    """
    Public health check endpoint inspecting the status of the AI coaching service,
    verifying SDK installation, API key configuration, and fallback readiness.
    
    Returns:
        JSON response with diagnostic parameters.
    """
    available = AICoachService.is_available()
    api_key_configured = AICoachService.get_api_key() is not None

    return jsonify({
        'status': 'healthy',
        'ai_available': available,
        'api_key_configured': api_key_configured,
        'model': AICoachService.DEFAULT_MODEL if available else None,
        'fallback_ready': True,
        'service_mode': 'gemini_generative' if available else 'algorithmic_fallback'
    }), 200

"""
HabitFlow Coaching Routes
============================
This module exposes API endpoints for local, rule-based coaching features:
- GET  /api/ai/daily-message: Daily message based on habit activity.
- GET  /api/ai/weekly-summary: Weekly review of completion patterns.
- POST /api/ai/habit-recommendations: Habit ideas based on a supplied goal.
- GET  /api/ai/mood-insights: Descriptive comparisons of logged moods and habits.
- GET  /api/ai/health: Status of the coaching service.
"""

from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify, current_app
from date_utils import current_date
from models import User, AIMessage, Habit, HabitLog, Mood, db
from routes.auth import token_required
from services.ai_coach import AICoachService
from services.streak_engine import StreakEngine

ai_bp = Blueprint('ai', __name__, url_prefix='/api/ai')


@ai_bp.route('/daily-message', methods=['GET'])
@token_required
def get_daily_message(current_user: User):
    """
    Retrieves or generates today's personalized daily habit coaching message.
    Checks the database cache first to avoid repeating the same daily calculation.
    Pass `?refresh=true` to force a new message generation.

    Args:
        current_user: Authenticated User object.

    Returns:
        JSON response with the coaching message, cached status, and generation metadata.
    """
    today = current_date()
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

    # Generate a deterministic coaching message from local activity data.
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
        current_app.logger.warning(f"Failed to cache daily coaching message: {e}")

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

    today = current_date()
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
    weekly_data = get_weekly_completion_data(current_user.id, days=7)

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
        current_app.logger.warning(f"Failed to cache weekly AI summary: {e}")

    return jsonify({
        'summary': summary_text,
        'cached': False,
        'generated_at': result.get('generated_at', datetime.now(timezone.utc).isoformat()),
        'source': result.get('source', 'generated'),
        'error': result.get('error', None)
    }), 200


@ai_bp.route('/habit-recommendations', methods=['POST'])
@ai_bp.route('/recommend-habits', methods=['POST'])
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
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return jsonify({'message': 'Request payload must be a JSON object.'}), 400
    goal_value = data.get('goal', 'better focus and productivity') or ''
    if not isinstance(goal_value, str):
        return jsonify({'message': 'Goal must be a text value.'}), 400
    user_goal = goal_value.strip() or 'better focus and productivity'
    if len(user_goal) > 300:
        user_goal = user_goal[:300]

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
    today = current_date()
    thirty_days_ago = today - timedelta(days=29)
    recent_moods = Mood.query.filter(
        Mood.user_id == current_user.id,
        Mood.date >= thirty_days_ago,
        Mood.date <= today
    ).all()

    if not recent_moods:
        return jsonify({
            'insight': 'Log your daily mood alongside your habits to unlock personalized emotional wellness insights!',
            'happy_percent': None,
            'source': 'default',
            'error': None
        }), 200

    habits = [
        habit for habit in Habit.query.filter_by(user_id=current_user.id).all()
        if (habit.created_date is None or habit.created_date <= today)
        and (habit.archived_date is None or habit.archived_date >= thirty_days_ago)
    ]
    habit_by_id = {habit.id: habit for habit in habits}
    completed_by_date = {}
    if habit_by_id:
        logs = HabitLog.query.filter(
            HabitLog.user_id == current_user.id,
            HabitLog.habit_id.in_(list(habit_by_id.keys())),
            HabitLog.date >= thirty_days_ago,
            HabitLog.date <= today,
            HabitLog.status == 'completed'
        ).all()
        for log in logs:
            if (
                log.date >= (habit_by_id[log.habit_id].created_date or log.date)
                and (
                    habit_by_id[log.habit_id].archived_date is None
                    or log.date <= habit_by_id[log.habit_id].archived_date
                )
                and habit_by_id[log.habit_id].is_scheduled_for_date(log.date)
            ):
                completed_by_date[log.date] = completed_by_date.get(log.date, 0) + 1

    daily_records = []
    for mood in recent_moods:
        scheduled = sum(
            mood.date >= (habit.created_date or mood.date)
            and (habit.archived_date is None or mood.date <= habit.archived_date)
            and habit.is_scheduled_for_date(mood.date)
            for habit in habits
        )
        if scheduled:
            daily_records.append({
                'mood': mood.mood,
                'scheduled': scheduled,
                'completed': completed_by_date.get(mood.date, 0),
            })

    result = AICoachService.analyze_mood_habit_correlation(daily_records)

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
    Public health check endpoint inspecting the status of the behavioral coaching engine.

    Returns:
        JSON response with diagnostic parameters.
    """
    return jsonify({
        'status': 'healthy',
        'engine': AICoachService.ENGINE_NAME,
        'version': AICoachService.ENGINE_VERSION,
        'service_mode': 'native_behavioral_engine',
        'fallback_ready': True,
        'ready': True
    }), 200

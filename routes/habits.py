"""
HabitFlow Habit Management Routes
=================================
This module provides RESTful CRUD endpoints for managing user habits and logging
daily statuses:
- GET    /api/habits: List all active habits with live streaks and today's status.
- POST   /api/habits: Create a new custom habit with category, icon, color, frequency.
- GET    /api/habits/<id>: Retrieve single habit with statistics.
- PUT    /api/habits/<id>: Update habit attributes.
- DELETE /api/habits/<id>: Soft delete (or permanent purge) a habit.
- POST   /api/habits/<id>/complete: Log completion, award XP, evaluate badges.
- POST   /api/habits/<id>/skip: Excuse habit for today, preserving active streak.
- POST   /api/habits/<id>/miss: Mark habit as missed, triggering streak reset.
- GET    /api/habits/<id>/history: Retrieve continuous activity history for calendar heatmaps.
"""

from datetime import date, time, timedelta
import json
from typing import Optional, Tuple
from flask import Blueprint, request, jsonify, current_app
from sqlalchemy.exc import IntegrityError
from date_utils import current_date
from models import Habit, HabitLog, User, db
from routes.auth import token_required
from services.streak_engine import StreakEngine
from services.gamification import GamificationEngine
from services.coach_engine import CoachEngine

habits_bp = Blueprint('habits', __name__, url_prefix='/api/habits')

# Standard weekday set for validation
WEEKDAY_ORDER = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
VALID_WEEKDAYS = set(WEEKDAY_ORDER)


def parse_target_date(data: dict) -> Tuple[Optional[date], Optional[str]]:
    """
    Extracts optional 'date' field from request payload (formatted as 'YYYY-MM-DD').
    Enforces that target date is not in the future and not older than 7 days.

    Args:
        data: Request JSON dictionary.

    Returns:
        tuple[date, error_message]: Validated calendar date or error string.
    """
    date_str = data.get('date') if data else None
    today = current_date()
    if date_str:
        try:
            target_date = date.fromisoformat(date_str)
        except (ValueError, TypeError):
            return None, "Invalid date format. Expected YYYY-MM-DD."
        if target_date > today:
            return None, "Cannot log habit completion for future dates."
        if target_date < today - timedelta(days=7):
            return None, "Cannot log habit status older than 7 days."
        return target_date, None
    return today, None


def _read_json_object():
    """Read an optional JSON object, rejecting arrays and scalar payloads."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError('Request payload must be a JSON object.')
    return data


def _has_finalized_reward(log: HabitLog) -> bool:
    """Return whether a status change would leave an already-paid reward behind."""
    return bool(log and (log.xp_awarded or 0) != 0)


def _save_log_status(log: HabitLog, habit_id: int, user_id: int, target_date: date,
                     status: str) -> Optional[HabitLog]:
    """Persist a status transition with compare-and-set protection."""
    if log.id is None:
        try:
            db.session.add(log)
            db.session.commit()
            return log
        except IntegrityError:
            db.session.rollback()
            existing = HabitLog.query.filter_by(
                habit_id=habit_id, user_id=user_id, date=target_date
            ).first()
            if not existing:
                raise
            log = existing

    if log.status == status:
        return log

    reward_marker = log.xp_awarded or 0
    is_reward_upgrade = log.status == 'skipped' and status == 'completed' and reward_marker > 0
    if _has_finalized_reward(log) and not is_reward_upgrade:
        return None

    result = db.session.execute(
        HabitLog.__table__.update()
        .where(
            HabitLog.id == log.id,
            HabitLog.habit_id == habit_id,
            HabitLog.user_id == user_id,
            HabitLog.date == target_date,
            HabitLog.status == log.status,
            HabitLog.xp_awarded == reward_marker,
        )
        .values(status=status)
    )
    if result.rowcount != 1:
        db.session.rollback()
        current_log = HabitLog.query.filter_by(
            habit_id=habit_id, user_id=user_id, date=target_date
        ).first()
        return current_log if current_log and current_log.status == status else None

    db.session.commit()
    return HabitLog.query.filter_by(
        habit_id=habit_id, user_id=user_id, date=target_date
    ).first()


def _clean_frequency(value, *, default_all=False):
    if value is None and default_all:
        return WEEKDAY_ORDER.copy(), None
    if not isinstance(value, list):
        return None, 'Frequency must be a list of weekday names.'
    cleaned = []
    for item in value:
        if not isinstance(item, str) or item.strip().lower() not in VALID_WEEKDAYS:
            return None, 'Frequency may contain only weekday names.'
        day = item.strip().lower()
        if day not in cleaned:
            cleaned.append(day)
    if not cleaned:
        return None, 'Select at least one scheduled weekday.'
    return cleaned, None


def _parse_reminder_time(value):
    if value is None or value == '':
        return None, None
    if not isinstance(value, str):
        return None, 'Reminder time must be text in HH:MM format.'
    try:
        parsed = time.fromisoformat(value)
        if parsed.tzinfo is not None:
            raise ValueError
        return parsed, None
    except ValueError:
        return None, 'Reminder time must be a valid HH:MM or HH:MM:SS value.'


@habits_bp.route('', methods=['GET'])
@token_required
def get_habits(current_user: User):
    """
    Retrieves all active habits belonging to the authenticated user, enriched
    with real-time streak calculations, completion totals, consistency scores,
    and today's log status.

    Args:
        current_user: Authenticated User object.

    Returns:
        JSON response with list of enriched habits and total count.
    """
    habits = Habit.query.filter_by(user_id=current_user.id, active=True).order_by(Habit.created_at.asc()).all()
    today = current_date()
    today_logs_map = {
        log.habit_id: log.status
        for log in HabitLog.query.filter_by(user_id=current_user.id, date=today).all()
    }

    habits_data = []
    for habit in habits:
        h_dict = habit.to_dict()
        h_dict['current_streak'] = StreakEngine.calculate_current_streak(habit.id, current_user.id)
        h_dict['longest_streak'] = StreakEngine.calculate_longest_streak(habit.id, current_user.id)
        h_dict['total_completions'] = StreakEngine.get_total_completions(habit.id, current_user.id)
        h_dict['consistency_score'] = StreakEngine.get_consistency_score(habit.id, current_user.id, days=30)
        h_dict['completion_rate'] = StreakEngine.get_completion_rate(habit.id, current_user.id, days=30)
        h_dict['is_scheduled_today'] = habit.is_scheduled_for_date(today)
        h_dict['today_status'] = today_logs_map.get(habit.id, None)
        habits_data.append(h_dict)

    return jsonify({
        'habits': habits_data,
        'count': len(habits_data)
    }), 200


@habits_bp.route('', methods=['POST'])
@token_required
def create_habit(current_user: User):
    """
    Creates a new custom habit for the user with specified frequency schedule.

    Expected JSON Body:
        {
            "title": "Drink 2L Water",
            "category": "health",
            "icon": "drop",
            "color": "primary",
            "frequency": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"],
            "reminder_time": "08:30"
        }

    Returns:
        JSON response with created habit data and HTTP 201 status.
    """
    try:
        data = _read_json_object()
    except ValueError as error:
        return jsonify({'message': str(error)}), 400
    if not isinstance(data.get('title'), str) or not data.get('title').strip():
        return jsonify({'message': 'Habit title is required.'}), 400

    active_count = Habit.query.filter_by(user_id=current_user.id, active=True).count()
    if active_count >= 50:
        return jsonify({
            'message': 'Active habit limit reached (maximum 50 habits). Please archive unused habits.'
        }), 400

    title = data['title'].strip()
    if len(title) < 2 or len(title) > 255:
        return jsonify({'message': 'Habit title must be between 2 and 255 characters.'}), 400

    category_value = data.get('category', 'general')
    icon_value = data.get('icon', 'star')
    color_value = data.get('color', 'primary')
    if not isinstance(category_value, str) or not isinstance(icon_value, str) or not isinstance(color_value, str):
        return jsonify({'message': 'Category, icon, and color must be text values.'}), 400
    category = category_value.strip().lower()
    icon = icon_value.strip()[:50]
    color = color_value.strip().lower()
    if not category or len(category) > 100 or not color or len(color) > 20:
        return jsonify({'message': 'Category and color must be valid non-empty values.'}), 400

    # Clean and validate frequency
    cleaned_frequency, frequency_error = _clean_frequency(
        data.get('frequency'), default_all='frequency' not in data
    )
    if frequency_error:
        return jsonify({'message': frequency_error}), 400

    # Parse reminder time if provided
    reminder_parsed, reminder_error = _parse_reminder_time(data.get('reminder_time'))
    if reminder_error:
        return jsonify({'message': reminder_error}), 400

    new_habit = Habit(
        user_id=current_user.id,
        title=title,
        category=category,
        icon=icon,
        color=color,
        frequency=cleaned_frequency,
        reminder_time=reminder_parsed,
        active=True
    )

    try:
        db.session.add(new_habit)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to create habit: {e}")
        return jsonify({'message': 'Failed to create habit due to an internal server error.'}), 500

    habit_dict = new_habit.to_dict()
    habit_dict['current_streak'] = 0
    habit_dict['longest_streak'] = 0
    habit_dict['total_completions'] = 0
    habit_dict['consistency_score'] = 0
    habit_dict['completion_rate'] = 0
    habit_dict['today_status'] = None
    habit_dict['is_scheduled_today'] = new_habit.is_scheduled_for_date(current_date())

    return jsonify({
        'message': 'Habit created successfully!',
        'habit': habit_dict
    }), 201


@habits_bp.route('/<int:habit_id>', methods=['GET'])
@token_required
def get_habit(current_user: User, habit_id: int):
    """
    Retrieves full details and analytics metrics for a specific habit.

    Args:
        current_user: Authenticated User object.
        habit_id: Target habit identifier.

    Returns:
        JSON response with detailed habit payload.
    """
    habit = Habit.query.filter_by(id=habit_id, user_id=current_user.id).first()
    if not habit:
        return jsonify({'message': 'Habit not found'}), 404

    habit_dict = habit.to_dict()
    habit_dict['current_streak'] = StreakEngine.calculate_current_streak(habit.id, current_user.id)
    habit_dict['longest_streak'] = StreakEngine.calculate_longest_streak(habit.id, current_user.id)
    habit_dict['total_completions'] = StreakEngine.get_total_completions(habit.id, current_user.id)
    habit_dict['consistency_score'] = StreakEngine.get_consistency_score(habit.id, current_user.id, days=30)
    habit_dict['completion_rate'] = StreakEngine.get_completion_rate(habit.id, current_user.id, days=30)

    today_log = HabitLog.query.filter_by(
        habit_id=habit.id,
        user_id=current_user.id,
        date=current_date()
    ).first()
    habit_dict['today_status'] = today_log.status if today_log else None

    return jsonify({'habit': habit_dict}), 200


def _apply_habit_updates(habit: Habit, data: dict):
    """Validates and applies supported patch fields; returns an error if invalid."""
    text_fields = {
        'title': (2, 255),
        'category': (1, 100),
        'icon': (0, 50),
        'color': (1, 20),
    }
    for field, (minimum, maximum) in text_fields.items():
        if field not in data:
            continue
        value = data[field]
        if not isinstance(value, str):
            return f'{field.capitalize()} must be a text value.'
        value = value.strip()
        if len(value) < minimum or len(value) > maximum:
            return f'{field.capitalize()} must be between {minimum} and {maximum} characters.'
        setattr(habit, field, value.lower() if field in ('category', 'color') else value)

    if 'frequency' in data:
        cleaned_frequency, error = _clean_frequency(data['frequency'])
        if error:
            return error
        current_frequency = habit.frequency
        if isinstance(current_frequency, str):
            try:
                current_frequency = json.loads(current_frequency)
            except (TypeError, ValueError):
                current_frequency = []
        if habit.logs.count() and set(cleaned_frequency) != set(current_frequency or []):
            return (
                'Frequency cannot be changed after the habit has logs. '
                'Create a new habit to preserve past analytics.'
            )
        habit.frequency = cleaned_frequency

    if 'active' in data:
        if not isinstance(data['active'], bool):
            return 'Active must be a boolean value.'
        if habit.active and not data['active']:
            habit.archived_date = current_date()
        elif not habit.active and data['active']:
            if habit.logs.count():
                return (
                    'An archived habit with history cannot be reactivated. '
                    'Create a new habit to start another schedule.'
                )
            habit.created_date = current_date()
            habit.archived_date = None
        habit.active = data['active']

    if 'reminder_time' in data:
        reminder_parsed, error = _parse_reminder_time(data['reminder_time'])
        if error:
            return error
        habit.reminder_time = reminder_parsed

    return None


@habits_bp.route('/<int:habit_id>', methods=['PUT'])
@token_required
def update_habit(current_user: User, habit_id: int):
    """
    Updates configuration attributes of an existing habit.

    Args:
        current_user: Authenticated User object.
        habit_id: Target habit identifier.

    Returns:
        JSON response with updated habit attributes.
    """
    habit = Habit.query.filter_by(id=habit_id, user_id=current_user.id).first()
    if not habit:
        return jsonify({'message': 'Habit not found'}), 404

    try:
        data = _read_json_object()
    except ValueError as error:
        return jsonify({'message': str(error)}), 400
    validation_error = _apply_habit_updates(habit, data)
    if validation_error:
        return jsonify({'message': validation_error}), 400

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to update habit: {e}")
        return jsonify({'message': 'Failed to update habit due to an internal server error.'}), 500

    return jsonify({
        'message': 'Habit updated successfully!',
        'habit': habit.to_dict()
    }), 200


@habits_bp.route('/<int:habit_id>', methods=['DELETE'])
@token_required
def delete_habit(current_user: User, habit_id: int):
    """
    Deletes a habit. By default performs a soft delete (marking `active=False`)
    to preserve historical analytics. Pass `?permanent=true` to permanently purge.

    Args:
        current_user: Authenticated User object.
        habit_id: Target habit identifier.

    Returns:
        JSON confirmation response.
    """
    habit = Habit.query.filter_by(id=habit_id, user_id=current_user.id).first()
    if not habit:
        return jsonify({'message': 'Habit not found'}), 404

    permanent = request.args.get('permanent', '').lower() in ('true', '1', 'yes')

    try:
        if permanent:
            db.session.delete(habit)
        else:
            if habit.active:
                habit.archived_date = current_date()
            habit.active = False
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to delete habit: {e}")
        return jsonify({'message': 'Failed to delete habit due to an internal server error.'}), 500

    return jsonify({'message': 'Habit deleted successfully!'}), 200


@habits_bp.route('/<int:habit_id>/complete', methods=['POST'])
@token_required
def complete_habit(current_user: User, habit_id: int):
    """
    Logs completion of a habit for today (or specified calendar date).
    Calculates updated streak, awards XP, evaluates badge milestones,
    and returns celebratory feedback.

    Args:
        current_user: Authenticated User object.
        habit_id: Target habit identifier.

    Returns:
        JSON response with completion metrics, XP earned, and milestone messages.
    """
    habit = Habit.query.filter_by(id=habit_id, user_id=current_user.id).first()
    if not habit:
        return jsonify({'message': 'Habit not found'}), 404

    if not habit.active:
        return jsonify({'message': 'Habit is archived and cannot be logged.'}), 400
    try:
        data = _read_json_object()
    except ValueError as error:
        return jsonify({'message': str(error)}), 400
    target_date, date_err = parse_target_date(data)
    if date_err:
        return jsonify({'message': date_err}), 400
    if habit.created_date and target_date < habit.created_date:
        return jsonify({'message': 'Cannot log this habit before it was created.'}), 400
    if not habit.is_scheduled_for_date(target_date):
        return jsonify({'message': 'This habit is not scheduled for that date.'}), 400

    # Locate existing log or initialize a new one
    log = HabitLog.query.filter_by(
        habit_id=habit.id,
        user_id=current_user.id,
        date=target_date
    ).first()

    if not log:
        log = HabitLog(
            habit_id=habit.id,
            user_id=current_user.id,
            date=target_date,
            status='completed'
        )
        db.session.add(log)

    try:
        log = _save_log_status(log, habit.id, current_user.id, target_date, 'completed')
        if log is None:
            return jsonify({'message': 'This log already has a reward and cannot be changed.'}), 409
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to save completion: {e}")
        return jsonify({'message': 'Failed to save completion due to an internal server error.'}), 500

    # Calculate the streak at the logged date for XP milestones, plus the
    # current streak for the dashboard response when this is a backfill.
    streak_at_target = StreakEngine.calculate_current_streak(
        habit.id, current_user.id, as_of=target_date
    )
    current_streak = StreakEngine.calculate_current_streak(habit.id, current_user.id)

    # The log stores its granted reward, making retries safe if XP persistence
    # fails after the status record has been committed.
    gamification_result = GamificationEngine.process_completion_xp(
        current_user.id, habit.id, streak_at_target, log
    )
    if gamification_result['xp_result'] is None:
        latest_log = db.session.get(HabitLog, log.id)
        if latest_log and latest_log.status != 'completed':
            return jsonify({
                'message': 'This habit log changed during another request. Refresh and try again.'
            }), 409
        return jsonify({
            'message': 'Completion was saved but XP could not be recorded. Retry this action to reconcile it.'
        }), 500

    # Generate milestone celebration message
    streak_msg = CoachEngine.get_streak_milestone_message(habit.id, current_user.id, streak_at_target)

    return jsonify({
        'message': 'Habit completed! Well done!',
        'status': 'completed',
        'current_streak': current_streak,
        'xp_earned': gamification_result['xp_earned'],
        'xp_result': gamification_result['xp_result'],
        'badges_unlocked': gamification_result['badges_unlocked'],
        'streak_message': streak_msg
    }), 200


@habits_bp.route('/<int:habit_id>/skip', methods=['POST'])
@token_required
def skip_habit(current_user: User, habit_id: int):
    """
    Excuses a habit for today (or specified calendar date), marking it as 'skipped'.
    Preserves active streak without triggering a broken streak penalty.

    Args:
        current_user: Authenticated User object.
        habit_id: Target habit identifier.

    Returns:
        JSON response with updated streak count.
    """
    habit = Habit.query.filter_by(id=habit_id, user_id=current_user.id).first()
    if not habit:
        return jsonify({'message': 'Habit not found'}), 404

    if not habit.active:
        return jsonify({'message': 'Habit is archived and cannot be logged.'}), 400
    try:
        data = _read_json_object()
    except ValueError as error:
        return jsonify({'message': str(error)}), 400
    target_date, date_err = parse_target_date(data)
    if date_err:
        return jsonify({'message': date_err}), 400
    if habit.created_date and target_date < habit.created_date:
        return jsonify({'message': 'Cannot log this habit before it was created.'}), 400
    if not habit.is_scheduled_for_date(target_date):
        return jsonify({'message': 'This habit is not scheduled for that date.'}), 400

    log = HabitLog.query.filter_by(
        habit_id=habit.id,
        user_id=current_user.id,
        date=target_date
    ).first()

    if log and log.status != 'skipped' and _has_finalized_reward(log):
        return jsonify({
            'message': 'This log already has XP rewards. Its status cannot be changed to skipped.'
        }), 409

    if not log:
        log = HabitLog(
            habit_id=habit.id,
            user_id=current_user.id,
            date=target_date,
            status='skipped'
        )
        db.session.add(log)

    try:
        log = _save_log_status(log, habit.id, current_user.id, target_date, 'skipped')
        if log is None:
            return jsonify({'message': 'This log already has a reward and cannot be changed to skipped.'}), 409
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to skip habit: {e}")
        return jsonify({'message': 'Failed to skip habit due to an internal server error.'}), 500

    current_streak = StreakEngine.calculate_current_streak(habit.id, current_user.id)
    reward = GamificationEngine.process_skip_xp(current_user.id, log)
    if reward['xp_result'] is None:
        latest_log = db.session.get(HabitLog, log.id)
        if latest_log and latest_log.status != 'skipped':
            return jsonify({
                'message': 'This habit log changed during another request. Refresh and try again.'
            }), 409
        return jsonify({
            'message': 'Skip was saved but XP could not be recorded. Retry this action to reconcile it.'
        }), 500

    return jsonify({
        'message': 'Habit skipped. Your streak is preserved!',
        'status': 'skipped',
        'current_streak': current_streak,
        'xp_earned': reward['xp_earned'],
        'xp_result': reward['xp_result'],
    }), 200


@habits_bp.route('/<int:habit_id>/miss', methods=['POST'])
@token_required
def miss_habit(current_user: User, habit_id: int):
    """
    Marks a habit as missed for today (or specified calendar date), resetting active streak.
    Returns supportive guidance for starting fresh.

    Args:
        current_user: Authenticated User object.
        habit_id: Target habit identifier.

    Returns:
        JSON response with reset streak and encouraging guidance.
    """
    habit = Habit.query.filter_by(id=habit_id, user_id=current_user.id).first()
    if not habit:
        return jsonify({'message': 'Habit not found'}), 404

    if not habit.active:
        return jsonify({'message': 'Habit is archived and cannot be logged.'}), 400
    try:
        data = _read_json_object()
    except ValueError as error:
        return jsonify({'message': str(error)}), 400
    target_date, date_err = parse_target_date(data)
    if date_err:
        return jsonify({'message': date_err}), 400
    if habit.created_date and target_date < habit.created_date:
        return jsonify({'message': 'Cannot log this habit before it was created.'}), 400
    if not habit.is_scheduled_for_date(target_date):
        return jsonify({'message': 'This habit is not scheduled for that date.'}), 400

    log = HabitLog.query.filter_by(
        habit_id=habit.id,
        user_id=current_user.id,
        date=target_date
    ).first()

    if log and log.status != 'missed' and _has_finalized_reward(log):
        return jsonify({
            'message': 'This log already has XP rewards. Its status cannot be changed to missed.'
        }), 409

    if not log:
        log = HabitLog(
            habit_id=habit.id,
            user_id=current_user.id,
            date=target_date,
            status='missed'
        )
        db.session.add(log)

    try:
        log = _save_log_status(log, habit.id, current_user.id, target_date, 'missed')
        if log is None:
            return jsonify({'message': 'This log already has a reward and cannot be changed to missed.'}), 409
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to mark habit missed: {e}")
        return jsonify({'message': 'Failed to mark habit missed due to an internal server error.'}), 500

    current_streak = StreakEngine.calculate_current_streak(habit.id, current_user.id)

    return jsonify({
        'message': 'Marked as missed. Consistency is about getting back up!',
        'status': 'missed',
        'current_streak': current_streak,
        'comeback_message': 'Never miss twice. Tomorrow is your opportunity to rebuild momentum.'
    }), 200


@habits_bp.route('/<int:habit_id>/history', methods=['GET'])
@token_required
def get_habit_history(current_user: User, habit_id: int):
    """
    Returns calendar activity history over the last N days (default 30).

    Args:
        current_user: Authenticated User object.
        habit_id: Target habit identifier.

    Returns:
        JSON response with continuous historical days array.
    """
    habit = Habit.query.filter_by(id=habit_id, user_id=current_user.id).first()
    if not habit:
        return jsonify({'message': 'Habit not found'}), 404

    days = request.args.get('days', 30, type=int)
    days = max(7, min(365, days))
    history_end = current_date()
    if not habit.active and habit.archived_date:
        history_end = min(history_end, habit.archived_date)
    history = StreakEngine.get_habit_history(
        habit.id, current_user.id, days=days, as_of=history_end
    )

    return jsonify({
        'habit_id': habit.id,
        'days': days,
        'history': history
    }), 200

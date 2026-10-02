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

from datetime import date, time, datetime
from typing import List, Optional
from flask import Blueprint, request, jsonify
from models import Habit, HabitLog, User, db
from routes.auth import token_required
from services.streak_engine import StreakEngine
from services.gamification import GamificationEngine
from services.coach_engine import CoachEngine

habits_bp = Blueprint('habits', __name__, url_prefix='/api/habits')

# Standard weekday set for validation
VALID_WEEKDAYS = {'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'}


def parse_target_date(data: dict) -> date:
    """
    Extracts optional 'date' field from request payload (formatted as 'YYYY-MM-DD').
    Defaults to today if absent or invalid.
    
    Args:
        data: Request JSON dictionary.
        
    Returns:
        date: Validated calendar date.
    """
    date_str = data.get('date') if data else None
    if date_str:
        try:
            return date.fromisoformat(date_str)
        except ValueError:
            pass
    return date.today()


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
    today = date.today()

    habits_data = []
    for habit in habits:
        h_dict = habit.to_dict()
        h_dict['current_streak'] = StreakEngine.calculate_current_streak(habit.id, current_user.id)
        h_dict['longest_streak'] = StreakEngine.calculate_longest_streak(habit.id, current_user.id)
        h_dict['total_completions'] = StreakEngine.get_total_completions(habit.id, current_user.id)
        h_dict['consistency_score'] = StreakEngine.get_consistency_score(habit.id, current_user.id, days=30)
        h_dict['completion_rate'] = StreakEngine.get_completion_rate(habit.id, current_user.id, days=30)
        h_dict['is_scheduled_today'] = habit.is_scheduled_for_date(today)

        # Inspect status for today
        today_log = HabitLog.query.filter_by(
            habit_id=habit.id,
            user_id=current_user.id,
            date=today
        ).first()
        h_dict['today_status'] = today_log.status if today_log else None

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
            "icon": "💧",
            "color": "primary",
            "frequency": ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"],
            "reminder_time": "08:30"
        }
        
    Returns:
        JSON response with created habit data and HTTP 201 status.
    """
    data = request.get_json(silent=True)
    if not data or not data.get('title'):
        return jsonify({'message': 'Habit title is required.'}), 400

    title = data.get('title', '').strip()
    if len(title) < 2 or len(title) > 255:
        return jsonify({'message': 'Habit title must be between 2 and 255 characters.'}), 400

    category = data.get('category', 'general').strip().lower()
    icon = data.get('icon', '✨').strip()[:10]
    color = data.get('color', 'primary').strip().lower()

    # Clean and validate frequency
    raw_frequency = data.get('frequency', [])
    if isinstance(raw_frequency, list) and len(raw_frequency) > 0:
        cleaned_frequency = [str(day).strip().lower() for day in raw_frequency if str(day).strip().lower() in VALID_WEEKDAYS]
    else:
        cleaned_frequency = list(VALID_WEEKDAYS)

    if not cleaned_frequency:
        cleaned_frequency = list(VALID_WEEKDAYS)

    # Parse reminder time if provided
    reminder_parsed = None
    if data.get('reminder_time'):
        try:
            time_str = data['reminder_time'].strip()
            # Handle HH:MM or HH:MM:SS
            parts = time_str.split(':')
            if len(parts) >= 2:
                reminder_parsed = time(int(parts[0]), int(parts[1]))
        except Exception:
            reminder_parsed = None

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
        return jsonify({'message': f'Failed to create habit: {str(e)}'}), 500

    habit_dict = new_habit.to_dict()
    habit_dict['current_streak'] = 0
    habit_dict['longest_streak'] = 0
    habit_dict['total_completions'] = 0
    habit_dict['consistency_score'] = 0
    habit_dict['completion_rate'] = 0
    habit_dict['today_status'] = None
    habit_dict['is_scheduled_today'] = new_habit.is_scheduled_for_date(date.today())

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
        date=date.today()
    ).first()
    habit_dict['today_status'] = today_log.status if today_log else None

    return jsonify({'habit': habit_dict}), 200


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

    data = request.get_json(silent=True) or {}

    if 'title' in data:
        new_title = data['title'].strip()
        if len(new_title) >= 2:
            habit.title = new_title

    if 'category' in data:
        habit.category = data['category'].strip().lower()

    if 'icon' in data:
        habit.icon = data['icon'].strip()[:10]

    if 'color' in data:
        habit.color = data['color'].strip().lower()

    if 'frequency' in data and isinstance(data['frequency'], list):
        cleaned_freq = [str(d).strip().lower() for d in data['frequency'] if str(d).strip().lower() in VALID_WEEKDAYS]
        if cleaned_freq:
            habit.frequency = cleaned_freq

    if 'active' in data:
        habit.active = bool(data['active'])

    if 'reminder_time' in data:
        if data['reminder_time'] is None:
            habit.reminder_time = None
        else:
            try:
                parts = data['reminder_time'].strip().split(':')
                if len(parts) >= 2:
                    habit.reminder_time = time(int(parts[0]), int(parts[1]))
            except Exception:
                pass

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': f'Failed to update habit: {str(e)}'}), 500

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
            habit.active = False
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': f'Failed to delete habit: {str(e)}'}), 500

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

    data = request.get_json(silent=True) or {}
    target_date = parse_target_date(data)

    # Locate existing log or initialize a new one
    log = HabitLog.query.filter_by(
        habit_id=habit.id,
        user_id=current_user.id,
        date=target_date
    ).first()

    already_completed = log and log.status == 'completed'

    if not log:
        log = HabitLog(
            habit_id=habit.id,
            user_id=current_user.id,
            date=target_date,
            status='completed'
        )
        db.session.add(log)
    else:
        log.status = 'completed'

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': f'Failed to save completion: {str(e)}'}), 500

    # Calculate updated streak
    current_streak = StreakEngine.calculate_current_streak(habit.id, current_user.id)

    # Award XP and evaluate badges only if not already completed today
    if not already_completed:
        gamification_result = GamificationEngine.process_completion_xp(current_user.id, habit.id, current_streak)
    else:
        gamification_result = {
            'xp_earned': 0,
            'xp_result': {'xp': current_user.xp_points, 'level': current_user.level, 'level_up': False},
            'badges_unlocked': []
        }

    # Generate milestone celebration message
    streak_msg = CoachEngine.get_streak_milestone_message(habit.id, current_user.id, current_streak)

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

    data = request.get_json(silent=True) or {}
    target_date = parse_target_date(data)

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
            status='skipped'
        )
        db.session.add(log)
    else:
        log.status = 'skipped'

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': f'Failed to skip habit: {str(e)}'}), 500

    current_streak = StreakEngine.calculate_current_streak(habit.id, current_user.id)

    return jsonify({
        'message': 'Habit skipped. Your streak is preserved!',
        'status': 'skipped',
        'current_streak': current_streak
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

    data = request.get_json(silent=True) or {}
    target_date = parse_target_date(data)

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
            status='missed'
        )
        db.session.add(log)
    else:
        log.status = 'missed'

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': f'Failed to mark habit missed: {str(e)}'}), 500

    current_streak = StreakEngine.calculate_current_streak(habit.id, current_user.id)

    return jsonify({
        'message': 'Marked as missed. Consistency is about getting back up!',
        'status': 'missed',
        'current_streak': current_streak,
        'comeback_message': 'Never miss twice — tomorrow is your opportunity to rebuild momentum!'
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
    history = StreakEngine.get_habit_history(habit.id, current_user.id, days=days)

    return jsonify({
        'habit_id': habit.id,
        'days': days,
        'history': history
    }), 200

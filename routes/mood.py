"""
HabitFlow Mood Tracking Routes
==============================
This module handles emotional wellbeing check-ins, mood history, and emotional analytics:
- POST /api/mood: Record or update today's mood ('happy', 'neutral', 'sad') and reflective note.
- GET  /api/mood/today: Retrieve today's recorded mood check-in.
- GET  /api/mood/history: Retrieve mood records over the past N days.
- GET  /api/mood/analytics: Aggregate mood distribution, happy day streaks, and habit correlations.
- GET  /api/mood/stats: Retrieve 7-day, 30-day, and 90-day comparative mood percentages.
"""

from datetime import date, timedelta
from flask import Blueprint, request, jsonify, current_app
from sqlalchemy.exc import IntegrityError
from date_utils import current_date
from models import Mood, User, db
from routes.auth import token_required
from services.coach_engine import CoachEngine

mood_bp = Blueprint('mood', __name__, url_prefix='/api/mood')

MOOD_LABELS = {
    'happy': 'Happy',
    'neutral': 'Neutral',
    'sad': 'Sad'
}
MOOD_EMOJIS = {
    'happy': '😊',
    'neutral': '😐',
    'sad': '😔'
}


def _get_active_happy_streak(user_id: int, through_date: date) -> int:
    """Count the contiguous happy-day run ending at ``through_date``."""
    streak = 0
    expected_date = through_date
    batch_size = 370

    while True:
        batch_start = expected_date - timedelta(days=batch_size - 1)
        records = Mood.query.filter(
            Mood.user_id == user_id,
            Mood.date >= batch_start,
            Mood.date <= expected_date
        ).order_by(Mood.date.desc()).all()
        if not records:
            break

        interrupted = False
        for record in records:
            if record.date != expected_date or record.mood != 'happy':
                interrupted = True
                break
            streak += 1
            expected_date -= timedelta(days=1)

        if interrupted or len(records) < batch_size or expected_date >= batch_start:
            break

    return streak


@mood_bp.route('', methods=['POST'])
@token_required
def log_mood(current_user: User):
    """
    Records or updates the user's emotional state for today (or specified calendar date).

    Expected JSON Body:
        {
            "mood": "happy",       // 'happy', 'neutral', or 'sad'
            "note": "Felt great after finishing morning run!",  // optional text (max 1000 chars)
            "date": "2026-10-02"   // optional ISO date, defaults to today
        }

    Returns:
        JSON response with the logged mood, label, and confirmation message.
    """
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    elif not isinstance(data, dict):
        return jsonify({'message': 'Request payload must be a JSON object.'}), 400
    raw_mood = data.get('mood', '')
    if not isinstance(raw_mood, str):
        return jsonify({'message': 'Mood must be a text value.'}), 400
    mood_value = raw_mood.strip().lower()

    if mood_value not in MOOD_EMOJIS:
        return jsonify({
            'message': f"Invalid mood. Allowed options are: {', '.join(MOOD_EMOJIS.keys())}."
        }), 400

    today = current_date()
    target_date = today
    if data.get('date'):
        try:
            parsed_d = date.fromisoformat(data['date'])
            if parsed_d > today:
                return jsonify({'message': 'Cannot record mood for future dates.'}), 400
            target_date = parsed_d
        except (ValueError, TypeError):
            return jsonify({'message': 'Invalid date format. Expected YYYY-MM-DD.'}), 400

    raw_note = data.get('note')
    if raw_note is not None and not isinstance(raw_note, str):
        return jsonify({'message': 'Mood note must be a text value.'}), 400
    note = raw_note.strip() if raw_note else None
    if note and len(note) > 1000:
        return jsonify({'message': 'Mood reflection note cannot exceed 1,000 characters.'}), 400

    # Retrieve existing check-in or instantiate a new record
    existing = Mood.query.filter_by(
        user_id=current_user.id,
        date=target_date
    ).first()

    if existing:
        existing.mood = mood_value
        existing.note = note
    else:
        new_mood = Mood(
            user_id=current_user.id,
            date=target_date,
            mood=mood_value,
            note=note
        )
        db.session.add(new_mood)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = Mood.query.filter_by(user_id=current_user.id, date=target_date).first()
        if not existing:
            current_app.logger.exception('Mood insert hit an integrity error without a matching daily record')
            return jsonify({'message': 'Failed to record mood due to an internal server error.'}), 500
        existing.mood = mood_value
        existing.note = note
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Failed to update mood after a concurrent insert: {e}")
            return jsonify({'message': 'Failed to record mood due to an internal server error.'}), 500
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to record mood: {e}")
        return jsonify({'message': 'Failed to record mood due to an internal server error.'}), 500

    return jsonify({
        'message': 'Mood logged successfully!',
        'mood': mood_value,
        'label': MOOD_LABELS[mood_value],
        'emoji': MOOD_EMOJIS[mood_value],
        'date': target_date.isoformat(),
        'note': note
    }), 200


@mood_bp.route('/today', methods=['GET'])
@token_required
def get_todays_mood(current_user: User):
    """
    Retrieves the authenticated user's mood record for today.

    Args:
        current_user: Authenticated User object.

    Returns:
        JSON response with today's mood dictionary or {'mood': None}.
    """
    today_record = Mood.query.filter_by(
        user_id=current_user.id,
        date=current_date()
    ).first()

    return jsonify({
        'mood': today_record.to_dict() if today_record else None
    }), 200


@mood_bp.route('/history', methods=['GET'])
@token_required
def get_mood_history(current_user: User):
    """
    Returns historical mood check-in records over the last N days (default 30).

    Args:
        current_user: Authenticated User object.

    Returns:
        JSON response with chronological list of mood entries.
    """
    days = request.args.get('days', 30, type=int)
    days = max(7, min(365, days))
    today = current_date()
    start_date = today - timedelta(days=days - 1)

    moods = Mood.query.filter(
        Mood.user_id == current_user.id,
        Mood.date >= start_date,
        Mood.date <= today
    ).order_by(Mood.date.asc()).all()

    return jsonify({
        'days': days,
        'moods': [m.to_dict() for m in moods]
    }), 200


@mood_bp.route('/analytics', methods=['GET'])
@token_required
def get_mood_analytics(current_user: User):
    """
    Calculates 30-day mood distribution counts, the active happy streak through
    today (or yesterday before today's check-in), the 30-day longest streak,
    and habit completion correlation.

    Args:
        current_user: Authenticated User object.

    Returns:
        JSON response with mood analytics payload.
    """
    today = current_date()
    start_date = today - timedelta(days=29)
    moods = Mood.query.filter(
        Mood.user_id == current_user.id,
        Mood.date >= start_date,
        Mood.date <= today
    ).order_by(Mood.date.asc()).all()

    # Tally counts
    distribution = {'happy': 0, 'neutral': 0, 'sad': 0}
    for m in moods:
        if m.mood in distribution:
            distribution[m.mood] += 1

    # Keep the active streak independent of the 30-day distribution window.
    mood_map = {m.date: m.mood for m in moods}
    check_date = today if today in mood_map else today - timedelta(days=1)
    active_happy_streak = _get_active_happy_streak(current_user.id, check_date)

    # Calculate all-time longest happy streak
    all_moods = Mood.query.filter_by(user_id=current_user.id).order_by(Mood.date.asc()).all()
    longest_happy_streak = 0
    running_happy_streak = 0
    previous_date = None
    for m in all_moods:
        if m.mood == 'happy':
            running_happy_streak = (
                running_happy_streak + 1
                if previous_date == m.date - timedelta(days=1)
                else 1
            )
            longest_happy_streak = max(longest_happy_streak, running_happy_streak)
        else:
            running_happy_streak = 0
        previous_date = m.date
    longest_happy_streak = max(longest_happy_streak, active_happy_streak)

    # Analyze correlation with habits
    correlation = CoachEngine.analyze_mood_habit_correlation(current_user.id)

    return jsonify({
        'mood_distribution': distribution,
        'happy_streak': active_happy_streak,
        'longest_happy_streak': longest_happy_streak,
        'total_logged': len(moods),
        'mood_correlation': correlation
    }), 200


@mood_bp.route('/stats', methods=['GET'])
@token_required
def get_mood_stats(current_user: User):
    """
    Computes comparative mood percentage distributions across 7-day, 30-day,
    and 90-day timeframes.

    Args:
        current_user: Authenticated User object.

    Returns:
        JSON response with timeframe statistics.
    """
    periods = {
        '7d': 7,
        '30d': 30,
        '90d': 90
    }
    stats = {}

    for period_key, day_count in periods.items():
        today = current_date()
        start_date = today - timedelta(days=day_count - 1)
        moods = Mood.query.filter(
            Mood.user_id == current_user.id,
            Mood.date >= start_date,
            Mood.date <= today
        ).all()

        total = len(moods)
        happy_count = sum(1 for m in moods if m.mood == 'happy')
        neutral_count = sum(1 for m in moods if m.mood == 'neutral')
        sad_count = sum(1 for m in moods if m.mood == 'sad')

        stats[period_key] = {
            'total': total,
            'happy': happy_count,
            'neutral': neutral_count,
            'sad': sad_count,
            'happy_percent': int((happy_count / total) * 100) if total > 0 else 0,
            'neutral_percent': int((neutral_count / total) * 100) if total > 0 else 0,
            'sad_percent': int((sad_count / total) * 100) if total > 0 else 0
        }

    return jsonify(stats), 200

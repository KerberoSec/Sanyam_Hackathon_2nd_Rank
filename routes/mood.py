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
from typing import Dict, Any, List
from flask import Blueprint, request, jsonify
from models import Mood, User, db
from routes.auth import token_required
from services.coach_engine import CoachEngine

mood_bp = Blueprint('mood', __name__, url_prefix='/api/mood')

MOOD_EMOJIS = {
    'happy': '😊',
    'neutral': '😐',
    'sad': '😢'
}


@mood_bp.route('', methods=['POST'])
@token_required
def log_mood(current_user: User):
    """
    Records or updates the user's emotional state for today (or specified calendar date).
    
    Expected JSON Body:
        {
            "mood": "happy",       // 'happy', 'neutral', or 'sad'
            "note": "Felt great after finishing morning run!",  // optional text
            "date": "2026-10-02"   // optional ISO date, defaults to today
        }
        
    Returns:
        JSON response with the logged mood, emoji, and confirmation message.
    """
    data = request.get_json(silent=True) or {}
    mood_value = data.get('mood', '').strip().lower()

    if mood_value not in MOOD_EMOJIS:
        return jsonify({
            'message': f"Invalid mood. Allowed options are: {', '.join(MOOD_EMOJIS.keys())}."
        }), 400

    target_date = date.today()
    if data.get('date'):
        try:
            target_date = date.fromisoformat(data['date'])
        except ValueError:
            pass

    note = data.get('note', '').strip() if data.get('note') else None

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
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': f'Failed to record mood: {str(e)}'}), 500

    return jsonify({
        'message': 'Mood logged successfully!',
        'mood': mood_value,
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
        date=date.today()
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
    start_date = date.today() - timedelta(days=days - 1)

    moods = Mood.query.filter(
        Mood.user_id == current_user.id,
        Mood.date >= start_date
    ).order_by(Mood.date.asc()).all()

    return jsonify({
        'days': days,
        'moods': [m.to_dict() for m in moods]
    }), 200


@mood_bp.route('/analytics', methods=['GET'])
@token_required
def get_mood_analytics(current_user: User):
    """
    Calculates 30-day mood distribution counts, active and maximum consecutive
    happy day streaks, and habit completion correlation.
    
    Args:
        current_user: Authenticated User object.
        
    Returns:
        JSON response with mood analytics payload.
    """
    start_date = date.today() - timedelta(days=30)
    moods = Mood.query.filter(
        Mood.user_id == current_user.id,
        Mood.date >= start_date
    ).order_by(Mood.date.asc()).all()

    # Tally counts
    distribution = {'happy': 0, 'neutral': 0, 'sad': 0}
    for m in moods:
        if m.mood in distribution:
            distribution[m.mood] += 1

    # Calculate consecutive happy calendar days
    mood_map = {m.date: m.mood for m in moods}
    active_happy_streak = 0
    today = date.today()

    # Step back from today or yesterday
    check_date = today if today in mood_map else today - timedelta(days=1)
    while check_date in mood_map and mood_map[check_date] == 'happy':
        active_happy_streak += 1
        check_date -= timedelta(days=1)

    # Analyze correlation with habits
    correlation = CoachEngine.analyze_mood_habit_correlation(current_user.id)

    return jsonify({
        'mood_distribution': distribution,
        'happy_streak': active_happy_streak,
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
        start_date = date.today() - timedelta(days=day_count - 1)
        moods = Mood.query.filter(
            Mood.user_id == current_user.id,
            Mood.date >= start_date
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

"""
HabitFlow Analytics Routes
==========================
This module aggregates analytics for dashboards and habit-specific deep dives:
- GET /api/analytics: Overview summary stats, weekly breakdown, monthly trend, and coach insights.
- GET /api/analytics/weekly: Weekday completion breakdown (Monday - Sunday).
- GET /api/analytics/monthly: 12-month completion trend with calendar precision.
- GET /api/analytics/habit/<id>: Granular habit statistics, 12-month trend, best days, and calendar history.
"""

from collections import defaultdict
from datetime import date, timedelta
from typing import List, Dict, Any
from flask import Blueprint, jsonify
from date_utils import current_date
from models import Habit, HabitLog, User
from routes.auth import token_required
from services.streak_engine import StreakEngine
from services.coach_engine import CoachEngine

analytics_bp = Blueprint('analytics', __name__, url_prefix='/api/analytics')


def get_calendar_month_range(year: int, month: int) -> tuple[date, date]:
    """
    Returns the first and last calendar dates for a given year and month.

    Args:
        year: Full year (e.g. 2026).
        month: Month index (1 to 12).

    Returns:
        tuple of (month_start_date, month_end_date).
    """
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = date(year, month + 1, 1) - timedelta(days=1)
    return start_date, end_date


def get_monthly_trend_data(user_id: int, habit_id: int = None,
                           as_of: date = None) -> List[Dict[str, Any]]:
    """
    Calculates monthly completion totals and rates for the last 12 calendar months.
    Uses a single batch query across the 12-month period to eliminate N+1 bottlenecks.

    Args:
        user_id: Identifier of the user.
        habit_id: Optional specific habit identifier.

    Returns:
        list of dicts: Month label, completions, and completion rate for each of 12 months.
    """
    today = as_of or current_date()
    current_year = today.year
    current_month = today.month

    # Calculate earliest month start date (12 months ago)
    earliest_year = current_year
    earliest_month = current_month - 11
    while earliest_month <= 0:
        earliest_month += 12
        earliest_year -= 1
    start_bound, _ = get_calendar_month_range(earliest_year, earliest_month)

    if habit_id is not None:
        habits = Habit.query.filter_by(id=habit_id, user_id=user_id).all()
    else:
        habits = Habit.query.filter_by(user_id=user_id).all()
    habit_ids = [habit.id for habit in habits]
    logs = HabitLog.query.filter(
        HabitLog.user_id == user_id,
        HabitLog.habit_id.in_(habit_ids),
        HabitLog.date >= start_bound,
        HabitLog.date <= today
    ).all() if habit_ids else []
    log_map = {(log.habit_id, log.date): log.status for log in logs}

    # Use scheduled habit-days as the denominator so unlogged days count as
    # missed instead of disappearing from the completion rate.
    month_counts = defaultdict(lambda: {'completed': 0, 'scheduled': 0, 'logged': 0})
    day = start_bound
    while day <= today:
        month_count = month_counts[(day.year, day.month)]
        for habit in habits:
            if habit.created_date and day < habit.created_date:
                continue
            if habit.archived_date and day > habit.archived_date:
                continue
            if not habit.is_scheduled_for_date(day):
                continue
            status = log_map.get((habit.id, day))
            if day == today and status is None:
                continue
            month_count['scheduled'] += 1
            if status is not None:
                month_count['logged'] += 1
            if status == 'completed':
                month_count['completed'] += 1
        day += timedelta(days=1)

    months_data = []
    for offset in range(11, -1, -1):
        target_year = current_year
        target_month = current_month - offset
        while target_month <= 0:
            target_month += 12
            target_year -= 1

        month_start, _ = get_calendar_month_range(target_year, target_month)
        key = (target_year, target_month)
        counts = month_counts[key]
        completions = counts['completed']
        rate = int((completions / counts['scheduled']) * 100) if counts['scheduled'] else 0

        months_data.append({
            'month': month_start.strftime('%b %y'),
            'completions': completions,
            'total_logs': counts['logged'],
            'scheduled_days': counts['scheduled'],
            'rate': rate,
            'year': target_year,
            'month_num': target_month
        })

    return months_data


def get_weekly_completion_data(user_id: int, habit_id: int = None, days: int = 30,
                               as_of: date = None) -> List[Dict[str, Any]]:
    """
    Calculates completion and skip metrics categorized by day of the week (Mon-Sun)
    over the requested number of calendar days (30 by default).

    Args:
        user_id: Identifier of the user.
        habit_id: Optional specific habit identifier.

    Returns:
        list of dicts: Weekday metrics with counts and percentage rates.
    """
    today = as_of or current_date()
    start_date = today - timedelta(days=days - 1)

    if habit_id is not None:
        habits = Habit.query.filter_by(id=habit_id, user_id=user_id).all()
    else:
        habits = Habit.query.filter_by(user_id=user_id).all()
    habit_ids = [habit.id for habit in habits]
    logs = HabitLog.query.filter(
        HabitLog.user_id == user_id,
        HabitLog.habit_id.in_(habit_ids),
        HabitLog.date >= start_date,
        HabitLog.date <= today
    ).all() if habit_ids else []
    log_map = {(log.habit_id, log.date): log.status for log in logs}

    day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    day_counts = {
        name: {'completed': 0, 'skipped': 0, 'missed': 0, 'total': 0, 'logged': 0}
        for name in day_names
    }
    target_day = start_date
    while target_day <= today:
        weekday_name = day_names[target_day.weekday()]
        for habit in habits:
            if habit.created_date and target_day < habit.created_date:
                continue
            if habit.archived_date and target_day > habit.archived_date:
                continue
            if not habit.is_scheduled_for_date(target_day):
                continue
            status = log_map.get((habit.id, target_day))
            if target_day == today and status is None:
                continue
            counts = day_counts[weekday_name]
            counts['total'] += 1
            if status is not None:
                counts['logged'] += 1
            if status == 'completed':
                counts['completed'] += 1
            elif status == 'skipped':
                counts['skipped'] += 1
            else:
                # Explicit misses and past unlogged scheduled days both count
                # as missed opportunities.
                counts['missed'] += 1
        target_day += timedelta(days=1)

    chart_data = []
    for day in day_names:
        completed = day_counts[day]['completed']
        skipped = day_counts[day]['skipped']
        missed = day_counts[day]['missed']
        total = day_counts[day]['total']
        rate = int((completed / total) * 100) if total > 0 else 0

        chart_data.append({
            'day': day,
            'completed': completed,
            'skipped': skipped,
            'missed': missed,
            'total': total,
            'logged': day_counts[day]['logged'],
            'rate': rate
        })

    return chart_data


@analytics_bp.route('', methods=['GET'])
@token_required
def get_analytics(current_user: User):
    """
    Returns full dashboard analytics payload including user summary cards,
    habits breakdown, weekly bar chart, 12-month trend line, and behavioral insights.

    Args:
        current_user: Authenticated User object.

    Returns:
        JSON response with aggregated metrics.
    """
    habits = Habit.query.filter_by(user_id=current_user.id, active=True).all()
    stats = StreakEngine.calculate_stats_for_user(current_user.id)

    habits_data = []
    for h in habits:
        habits_data.append({
            'id': h.id,
            'title': h.title,
            'category': h.category,
            'icon': h.icon,
            'color': h.color,
            'current_streak': StreakEngine.calculate_current_streak(h.id, current_user.id),
            'longest_streak': StreakEngine.calculate_longest_streak(h.id, current_user.id),
            'total_completions': StreakEngine.get_total_completions(h.id, current_user.id),
            'consistency_score': StreakEngine.get_consistency_score(h.id, current_user.id, days=30),
            'completion_rate': StreakEngine.get_completion_rate(h.id, current_user.id, days=30)
        })

    weekly_chart = get_weekly_completion_data(current_user.id)
    monthly_trend = get_monthly_trend_data(current_user.id)
    insights = CoachEngine.get_all_insights(current_user.id)

    return jsonify({
        'summary': {
            'total_habits': stats['total_habits'],
            'total_completions': stats['total_completions'],
            'combined_streak': stats['combined_streak'],
            'consistency_score': stats['consistency_score']
        },
        'habits': habits_data,
        'weekly_chart': weekly_chart,
        'monthly_trend': monthly_trend,
        'insights': insights,
        'user_level': current_user.level,
        'user_xp': current_user.xp_points
    }), 200


@analytics_bp.route('/weekly', methods=['GET'])
@token_required
def get_weekly(current_user: User):
    """Returns weekly completion data breakdown."""
    data = get_weekly_completion_data(current_user.id)
    return jsonify({'weekly': data}), 200


@analytics_bp.route('/monthly', methods=['GET'])
@token_required
def get_monthly(current_user: User):
    """Returns 12-month completion trend data."""
    data = get_monthly_trend_data(current_user.id)
    return jsonify({'monthly': data}), 200


@analytics_bp.route('/habit/<int:habit_id>', methods=['GET'])
@token_required
def get_habit_analytics(current_user: User, habit_id: int):
    """
    Returns deep analytics for a single habit, including streak metrics,
    30-day activity history, 12-month trend, and best performing weekdays.

    Args:
        current_user: Authenticated User object.
        habit_id: Habit identifier.

    Returns:
        JSON response with detailed habit statistics and chart inputs.
    """
    habit = Habit.query.filter_by(id=habit_id, user_id=current_user.id).first()
    if not habit:
        return jsonify({'message': 'Habit not found'}), 404

    analysis_end = current_date()
    if not habit.active and habit.archived_date:
        analysis_end = min(analysis_end, habit.archived_date)
    history = StreakEngine.get_habit_history(
        habit.id, current_user.id, days=30, as_of=analysis_end
    )
    monthly_trend = get_monthly_trend_data(
        current_user.id, habit_id=habit.id, as_of=analysis_end
    )
    weekly_breakdown = get_weekly_completion_data(
        current_user.id, habit_id=habit.id, as_of=analysis_end
    )

    # Format best days for display
    sorted_days = sorted(weekly_breakdown, key=lambda d: d['completed'], reverse=True)
    best_days = [
        {'day': d['day'], 'completed': d['completed'], 'rate': d['rate']}
        for d in sorted_days if d['completed'] > 0
    ]

    habit_data = habit.to_dict()
    today = current_date()
    today_log = HabitLog.query.filter_by(
        habit_id=habit.id,
        user_id=current_user.id,
        date=today,
    ).first()
    habit_data['today_status'] = today_log.status if today_log else None
    habit_data['frequency_editable'] = not HabitLog.query.filter_by(
        habit_id=habit.id,
        user_id=current_user.id,
    ).first()
    habit_data['is_scheduled_today'] = bool(
        habit.active
        and (not habit.created_date or today >= habit.created_date)
        and habit.is_scheduled_for_date(today)
    )

    return jsonify({
        'habit': habit_data,
        'stats': {
            'current_streak': StreakEngine.calculate_current_streak(habit.id, current_user.id),
            'longest_streak': StreakEngine.calculate_longest_streak(habit.id, current_user.id),
            'total_completions': StreakEngine.get_total_completions(habit.id, current_user.id),
            'consistency_score_7d': StreakEngine.get_consistency_score(habit.id, current_user.id, days=7),
            'consistency_score_30d': StreakEngine.get_consistency_score(habit.id, current_user.id, days=30),
            'completion_rate_7d': StreakEngine.get_completion_rate(habit.id, current_user.id, days=7),
            'completion_rate_30d': StreakEngine.get_completion_rate(habit.id, current_user.id, days=30)
        },
        'history': history,
        'monthly_trend': monthly_trend,
        'weekly_breakdown': weekly_breakdown,
        'best_days': best_days
    }), 200

"""
HabitFlow Analytics Routes
==========================
This module aggregates analytics for dashboards and habit-specific deep dives:
- GET /api/analytics: Overview summary stats, weekly breakdown, monthly trend, and coach insights.
- GET /api/analytics/weekly: Weekday completion breakdown (Monday - Sunday).
- GET /api/analytics/monthly: 12-month completion trend with calendar precision.
- GET /api/analytics/habit/<id>: Granular habit statistics, 12-month trend, best days, and calendar history.
"""

from datetime import date, timedelta
from typing import List, Dict, Any
from flask import Blueprint, request, jsonify
from models import Habit, HabitLog, User, db
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


def get_monthly_trend_data(user_id: int, habit_id: int = None) -> List[Dict[str, Any]]:
    """
    Calculates monthly completion totals and rates for the last 12 calendar months.
    Optionally scoped to a specific habit.
    
    Args:
        user_id: Identifier of the user.
        habit_id: Optional specific habit identifier.
        
    Returns:
        list of dicts: Month label, completions, and completion rate for each of 12 months.
    """
    today = date.today()
    current_year = today.year
    current_month = today.month

    months_data = []

    for offset in range(11, -1, -1):
        target_year = current_year
        target_month = current_month - offset

        while target_month <= 0:
            target_month += 12
            target_year -= 1

        month_start, month_end = get_calendar_month_range(target_year, target_month)

        # Base filter
        query_completed = HabitLog.query.filter(
            HabitLog.user_id == user_id,
            HabitLog.status == 'completed',
            HabitLog.date >= month_start,
            HabitLog.date <= month_end
        )
        query_total = HabitLog.query.filter(
            HabitLog.user_id == user_id,
            HabitLog.date >= month_start,
            HabitLog.date <= month_end
        )

        if habit_id is not None:
            query_completed = query_completed.filter(HabitLog.habit_id == habit_id)
            query_total = query_total.filter(HabitLog.habit_id == habit_id)

        completions = query_completed.count()
        total_logs = query_total.count()

        rate = int((completions / total_logs) * 100) if total_logs > 0 else 0

        months_data.append({
            'month': month_start.strftime('%b %y'),
            'completions': completions,
            'total_logs': total_logs,
            'rate': rate,
            'year': target_year,
            'month_num': target_month
        })

    return months_data


def get_weekly_completion_data(user_id: int, habit_id: int = None) -> List[Dict[str, Any]]:
    """
    Calculates completion and skip metrics categorized by day of the week (Mon-Sun)
    over the preceding 30 days.
    
    Args:
        user_id: Identifier of the user.
        habit_id: Optional specific habit identifier.
        
    Returns:
        list of dicts: Weekday metrics with counts and percentage rates.
    """
    start_date = date.today() - timedelta(days=30)

    query = HabitLog.query.filter(
        HabitLog.user_id == user_id,
        HabitLog.date >= start_date
    )
    if habit_id is not None:
        query = query.filter(HabitLog.habit_id == habit_id)

    logs = query.all()

    day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    day_counts = {name: {'completed': 0, 'skipped': 0, 'missed': 0} for name in day_names}

    for log in logs:
        weekday_name = day_names[log.date.weekday()]
        status = log.status if log.status in ('completed', 'skipped', 'missed') else 'completed'
        day_counts[weekday_name][status] += 1

    chart_data = []
    for day in day_names:
        completed = day_counts[day]['completed']
        skipped = day_counts[day]['skipped']
        missed = day_counts[day]['missed']
        total = completed + skipped + missed
        rate = int((completed / total) * 100) if total > 0 else 0

        chart_data.append({
            'day': day,
            'completed': completed,
            'skipped': skipped,
            'missed': missed,
            'total': total,
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

    history = StreakEngine.get_habit_history(habit.id, current_user.id, days=30)
    monthly_trend = get_monthly_trend_data(current_user.id, habit_id=habit.id)
    weekly_breakdown = get_weekly_completion_data(current_user.id, habit_id=habit.id)

    # Format best days for display
    sorted_days = sorted(weekly_breakdown, key=lambda d: d['completed'], reverse=True)
    best_days = [
        {'day': d['day'], 'completed': d['completed'], 'rate': d['rate']}
        for d in sorted_days if d['completed'] > 0
    ]

    return jsonify({
        'habit': habit.to_dict(),
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

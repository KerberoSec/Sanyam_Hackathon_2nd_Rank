"""
HabitFlow Streak Engine
=======================
This service calculates habit streaks, completion rates, consistency scores,
and overall user performance metrics.

Key concepts:
- Scheduled Day: A day where the habit's frequency includes that day of the week.
- Active Streak: A continuous unbroken sequence of scheduled days completed or skipped.
- Grace Period: If today has not been logged yet, yesterday's streak remains intact
  so the user can complete their habit before midnight without losing progress.
- Skipped Days: Treated as excused (streak is preserved without incrementing, consistency credited at 50%).
- Missed or Unlogged Scheduled Days: Streak resets to zero.
"""

from datetime import timedelta, date
from typing import Dict, Any, List
from date_utils import current_date
from models import Habit, HabitLog, User, db


class StreakEngine:
    """Service class encapsulating all streak calculation and analytics logic."""

    @staticmethod
    def calculate_current_streak(habit_id: int, user_id: int, as_of: date = None) -> int:
        """
        Calculates the active, unbroken streak for a given habit.

        Rules:
        1. If today is completed, it increments the streak; if skipped, the existing streak is preserved.
        2. If today is scheduled and logged as 'missed', the streak is broken (0).
        3. If today is scheduled but NOT logged yet, the user has until the end of the day;
           the streak continues from the previous scheduled day.
        4. Non-scheduled days (e.g. weekends for a weekday-only habit) do not break streaks.
        5. Any scheduled past day with status 'missed' or no log at all breaks the streak.

        Args:
            habit_id: Identifier of the habit.
            user_id: Identifier of the owner user.

        Returns:
            int: The current active streak count in days.
        """
        habit = db.session.get(Habit, habit_id)
        if not habit or habit.user_id != user_id:
            return 0
        if not habit.active:
            return 0

        today = as_of or current_date()
        earliest_log = db.session.query(db.func.min(HabitLog.date)).filter_by(
            habit_id=habit_id, user_id=user_id
        ).scalar()
        earliest_date = habit.created_date or earliest_log or today
        chunk_start = max(earliest_date, today - timedelta(days=370))

        def load_logs(start_date, end_date):
            return {
                log.date: log.status
                for log in HabitLog.query.filter(
                    HabitLog.habit_id == habit_id,
                    HabitLog.user_id == user_id,
                    HabitLog.date >= start_date,
                    HabitLog.date <= end_date,
                ).all()
            }

        log_map = load_logs(chunk_start, today)

        current_streak = 0

        # Determine the initial date to evaluate
        if habit.is_scheduled_for_date(today):
            if today in log_map:
                status = log_map[today]
                if status == 'completed':
                    current_streak += 1
                    check_date = today - timedelta(days=1)
                elif status == 'skipped':
                    check_date = today - timedelta(days=1)
                elif status == 'missed':
                    # Explicitly missed today resets streak immediately
                    return 0
                else:
                    check_date = today - timedelta(days=1)
            else:
                # Today not logged yet: grace period allows streak to continue from yesterday
                check_date = today - timedelta(days=1)
        else:
            # Today is not scheduled: start checking from yesterday
            check_date = today - timedelta(days=1)

        while check_date >= earliest_date:
            if check_date < chunk_start:
                chunk_end = chunk_start - timedelta(days=1)
                chunk_start = max(earliest_date, chunk_end - timedelta(days=370))
                log_map.update(load_logs(chunk_start, chunk_end))

            # Only evaluate days that match the habit's frequency
            if habit.is_scheduled_for_date(check_date):
                if check_date in log_map:
                    status = log_map[check_date]
                    if status == 'completed':
                        current_streak += 1
                    elif status == 'skipped':
                        pass
                    else:
                        # Status is 'missed' -> streak is broken
                        break
                else:
                    # Scheduled day has no log -> streak is broken
                    break

            # Move one day further into the past
            check_date -= timedelta(days=1)

        return current_streak

    @staticmethod
    def calculate_longest_streak(habit_id: int, user_id: int) -> int:
        """
        Calculates the all-time longest streak achieved for a habit.
        Iterates chronologically through all days from the earliest log or habit creation
        up to today, evaluating consecutive scheduled days completed or skipped.

        Args:
            habit_id: Identifier of the habit.
            user_id: Identifier of the owner user.

        Returns:
            int: The maximum streak length ever recorded.
        """
        habit = db.session.get(Habit, habit_id)
        if not habit or habit.user_id != user_id:
            return 0

        logs = HabitLog.query.filter_by(habit_id=habit_id, user_id=user_id).all()
        if not logs:
            return 0

        log_map = {log.date: log.status for log in logs}

        # Determine start date: earliest log date or habit creation date
        earliest_log_date = min(log.date for log in logs)
        creation_date = habit.created_date or earliest_log_date
        start_date = min(earliest_log_date, creation_date)
        today = current_date()

        longest_streak = 0
        running_streak = 0
        curr_date = start_date

        while curr_date <= today:
            if habit.is_scheduled_for_date(curr_date):
                if curr_date in log_map:
                    status = log_map[curr_date]
                    if status == 'completed':
                        running_streak += 1
                        if running_streak > longest_streak:
                            longest_streak = running_streak
                    elif status == 'skipped':
                        pass
                    else:
                        # Missed resets the running streak
                        running_streak = 0
                else:
                    # Only reset running streak if the missing date is in the past (before today)
                    if curr_date < today:
                        running_streak = 0
            # Move to next chronological day
            curr_date += timedelta(days=1)

        return longest_streak

    @staticmethod
    def get_total_completions(habit_id: int, user_id: int) -> int:
        """
        Returns the total lifetime count of completed logs for a habit.

        Args:
            habit_id: Identifier of the habit.
            user_id: Identifier of the user.

        Returns:
            int: Total completion count.
        """
        return HabitLog.query.filter(
            HabitLog.habit_id == habit_id,
            HabitLog.user_id == user_id,
            HabitLog.status == 'completed',
            HabitLog.date <= current_date(),
        ).count()

    @staticmethod
    def get_habit_history(habit_id: int, user_id: int, days: int = 30,
                          as_of: date = None) -> List[Dict[str, Any]]:
        """
        Returns habit completion history for the last N calendar days.
        Provides a continuous list including days without logs (marked as 'unlogged' or 'none').

        Args:
            habit_id: Identifier of the habit.
            user_id: Identifier of the user.
            days: Number of past days to include (default 30).

        Returns:
            list of dicts: Date, status, and scheduled flag for each day.
        """
        habit = db.session.get(Habit, habit_id)
        if not habit or habit.user_id != user_id:
            return []

        end_date = as_of or current_date()
        start_date = end_date - timedelta(days=days - 1)
        logs = HabitLog.query.filter(
            HabitLog.habit_id == habit_id,
            HabitLog.user_id == user_id,
            HabitLog.date >= start_date,
            HabitLog.date <= end_date
        ).all()
        log_map = {log.date: log.status for log in logs}

        history = []
        for i in range(days):
            current_day = start_date + timedelta(days=i)
            is_scheduled = (
                (habit.created_date is None or current_day >= habit.created_date)
                and (habit.archived_date is None or current_day <= habit.archived_date)
                and habit.is_scheduled_for_date(current_day)
            )
            status = log_map.get(current_day, 'none') if is_scheduled else 'none'

            history.append({
                'date': current_day.isoformat(),
                'status': status,
                'is_scheduled': is_scheduled,
                'day_name': current_day.strftime('%A')
            })

        return history

    @staticmethod
    def get_consistency_score(habit_id: int, user_id: int, days: int = 30) -> int:
        """
        Calculates the consistency score (0 - 100%) over the past N days.
        Scoring formula:
          - Completed scheduled day = 100%
          - Skipped scheduled day   = 50%
          - Missed or unlogged day  = 0%
          - Non-scheduled days are excluded from the denominator.

        Args:
            habit_id: Identifier of the habit.
            user_id: Identifier of the user.
            days: Lookback window in days (default 30).

        Returns:
            int: Consistency percentage (0 to 100).
        """
        habit = db.session.get(Habit, habit_id)
        if not habit or habit.user_id != user_id:
            return 0

        today = current_date()
        if habit.archived_date:
            today = min(today, habit.archived_date)
        start_date = today - timedelta(days=days - 1)
        logs = HabitLog.query.filter(
            HabitLog.habit_id == habit_id,
            HabitLog.user_id == user_id,
            HabitLog.date >= start_date,
            HabitLog.date <= today
        ).all()
        log_map = {log.date: log.status for log in logs}

        scheduled_count = 0
        total_points = 0.0

        for i in range(days):
            day_to_check = start_date + timedelta(days=i)
            if habit.created_date and day_to_check < habit.created_date:
                continue
            if habit.archived_date and day_to_check > habit.archived_date:
                continue
            # Skip checking today if not logged yet (to avoid unfairly docking score in morning)
            if day_to_check == today and day_to_check not in log_map:
                continue

            if habit.is_scheduled_for_date(day_to_check):
                scheduled_count += 1
                status = log_map.get(day_to_check, None)
                if status == 'completed':
                    total_points += 1.0
                elif status == 'skipped':
                    total_points += 0.5
                # missed or None yields 0.0 points

        if scheduled_count == 0:
            return 0

        score_percent = int((total_points / scheduled_count) * 100)
        return min(100, max(0, score_percent))

    @staticmethod
    def get_completion_rate(habit_id: int, user_id: int, days: int = 30) -> int:
        """
        Calculates the pure completion rate (only 'completed' status counts)
        over scheduled days in the past N days.

        Args:
            habit_id: Identifier of the habit.
            user_id: Identifier of the user.
            days: Lookback window in days (default 30).

        Returns:
            int: Completion percentage (0 to 100).
        """
        habit = db.session.get(Habit, habit_id)
        if not habit or habit.user_id != user_id:
            return 0

        today = current_date()
        if habit.archived_date:
            today = min(today, habit.archived_date)
        start_date = today - timedelta(days=days - 1)
        logs = HabitLog.query.filter(
            HabitLog.habit_id == habit_id,
            HabitLog.user_id == user_id,
            HabitLog.date >= start_date,
            HabitLog.date <= today
        ).all()
        log_map = {log.date: log.status for log in logs}

        scheduled_count = 0
        completed_count = 0

        for i in range(days):
            day_to_check = start_date + timedelta(days=i)
            if habit.created_date and day_to_check < habit.created_date:
                continue
            if habit.archived_date and day_to_check > habit.archived_date:
                continue
            if day_to_check == today and day_to_check not in log_map:
                continue

            if habit.is_scheduled_for_date(day_to_check):
                scheduled_count += 1
                if log_map.get(day_to_check) == 'completed':
                    completed_count += 1

        if scheduled_count == 0:
            return 0

        rate_percent = int((completed_count / scheduled_count) * 100)
        return min(100, max(0, rate_percent))

    @staticmethod
    def calculate_stats_for_user(user_id: int) -> Dict[str, Any]:
        """
        Aggregates high-level summary statistics across all active habits for a user.
        Includes total active habits, cumulative lifetime completions, combined current streak,
        average 30-day consistency score, user level, and total XP.

        Args:
            user_id: Identifier of the user.

        Returns:
            dict: Summary metrics dictionary.
        """
        user = db.session.get(User, user_id)
        if not user:
            return {
                'total_habits': 0,
                'total_completions': 0,
                'combined_streak': 0,
                'consistency_score': 0,
                'level': 1,
                'xp_points': 0
            }

        active_habits = Habit.query.filter_by(user_id=user_id, active=True).all()

        total_streaks = 0
        consistency_scores = []

        for habit in active_habits:
            streak = StreakEngine.calculate_current_streak(habit.id, user_id)
            score = StreakEngine.get_consistency_score(habit.id, user_id, days=30)

            total_streaks += streak
            consistency_scores.append(score)

        total_completions = HabitLog.query.filter(
            HabitLog.user_id == user_id,
            HabitLog.status == 'completed',
            HabitLog.date <= current_date(),
        ).count()

        avg_consistency = int(sum(consistency_scores) / len(consistency_scores)) if consistency_scores else 0

        return {
            'total_habits': len(active_habits),
            'total_completions': total_completions,
            'combined_streak': total_streaks,
            'consistency_score': avg_consistency,
            'level': user.level,
            'xp_points': user.xp_points
        }

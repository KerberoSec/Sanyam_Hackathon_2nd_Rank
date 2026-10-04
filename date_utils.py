"""Date helpers shared by route and domain code.

HabitFlow uses UTC as its single calendar boundary. Taking the date from the
server keeps streaks and XP consistent and prevents callers from choosing a
future "today" through a request header.
"""

from datetime import date, datetime, timezone


def current_date() -> date:
    """Return the current UTC calendar date."""
    return datetime.now(timezone.utc).date()

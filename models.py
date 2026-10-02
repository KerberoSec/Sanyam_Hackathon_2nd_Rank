"""
HabitFlow Database Models
=========================
This module defines the SQLAlchemy ORM models representing the core domain entities:
- User: Account details, authentication credentials, XP, and level.
- Habit: Habit definitions, categories, color themes, and scheduled frequencies.
- HabitLog: Daily status records ('completed', 'skipped', 'missed') for each habit.
- Mood: Daily emotional check-in entries ('happy', 'neutral', 'sad') and notes.
- Badge: Predefined achievement definitions and unlock milestones.
- UserBadge: Many-to-many relationship linking unlocked badges to users with timestamps.
- AIMessage: Cached AI-generated coaching messages, weekly summaries, and insights.
"""

import json
from datetime import datetime, date, timezone
from typing import List, Dict, Any, Optional
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

# Initialize the SQLAlchemy database instance
db = SQLAlchemy()

def utc_now() -> datetime:
    """Returns current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class User(db.Model):
    """
    Represents an application user account.
    Stores authentication credentials, gamification progress (XP and level),
    and maintains relationships to user-specific habits, logs, moods, and badges.
    """
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.Text, nullable=False)
    xp_points = db.Column(db.Integer, default=0, nullable=False)
    level = db.Column(db.Integer, default=1, nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    # Relationships with cascade deletion for data integrity
    habits = db.relationship('Habit', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    habit_logs = db.relationship('HabitLog', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    moods = db.relationship('Mood', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    ai_messages = db.relationship('AIMessage', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    user_badges = db.relationship('UserBadge', backref='user', lazy='dynamic', cascade='all, delete-orphan')

    def set_password(self, password: str) -> None:
        """
        Hashes the provided plain text password using Werkzeug's secure hashing.
        
        Args:
            password: Plain text password to hash.
        """
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """
        Verifies if the provided plain text password matches the stored password hash.
        
        Args:
            password: Plain text password to verify.
            
        Returns:
            bool: True if password matches hash, False otherwise.
        """
        return check_password_hash(self.password_hash, password)

    def to_dict(self) -> Dict[str, Any]:
        """
        Serializes user model data into a dictionary suitable for JSON responses.
        Excludes sensitive information such as password hash.
        
        Returns:
            dict: User data summary.
        """
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'xp_points': self.xp_points,
            'level': self.level,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Habit(db.Model):
    """
    Represents a personal habit defined by a user.
    Tracks title, category, display icon, color styling, active state,
    and weekly scheduled frequency (e.g., ['monday', 'wednesday', 'friday']).
    """
    __tablename__ = 'habits'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(100), default='general', nullable=False)
    icon = db.Column(db.String(50), default='✨', nullable=False)
    color = db.Column(db.String(20), default='primary', nullable=False)
    frequency = db.Column(
        db.JSON,
        default=lambda: ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'],
        nullable=False
    )
    reminder_time = db.Column(db.Time, nullable=True)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    # Relationship to habit logs
    logs = db.relationship('HabitLog', backref='habit', lazy='dynamic', cascade='all, delete-orphan')

    def is_scheduled_for_date(self, target_date: date) -> bool:
        """
        Determines whether this habit is scheduled to be performed on the given date
        based on the days specified in its frequency list.
        
        Args:
            target_date: The date to check against habit frequency.
            
        Returns:
            bool: True if the habit is scheduled for this weekday, False otherwise.
        """
        weekday_names = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        day_name = weekday_names[target_date.weekday()]

        freq = self.frequency
        if isinstance(freq, str):
            try:
                freq = json.loads(freq)
            except Exception:
                freq = []

        if not freq or not isinstance(freq, list):
            # Default to everyday if frequency is unspecified or malformed
            return True

        freq_lower = [str(d).strip().lower() for d in freq]
        return day_name in freq_lower

    def to_dict(self) -> Dict[str, Any]:
        """
        Serializes habit attributes into a JSON-friendly dictionary.
        
        Returns:
            dict: Habit metadata.
        """
        freq = self.frequency
        if isinstance(freq, str):
            try:
                freq = json.loads(freq)
            except Exception:
                freq = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

        return {
            'id': self.id,
            'user_id': self.user_id,
            'title': self.title,
            'category': self.category,
            'icon': self.icon,
            'color': self.color,
            'frequency': freq,
            'reminder_time': self.reminder_time.strftime('%H:%M') if self.reminder_time else None,
            'active': self.active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class HabitLog(db.Model):
    """
    Represents an entry logging the status of a specific habit on a specific date.
    Valid status values:
      - 'completed': User performed and finished the habit.
      - 'skipped': User excused the habit (streak preserved, half XP/consistency).
      - 'missed': User failed or neglected to perform the habit (streak reset).
    """
    __tablename__ = 'habit_logs'

    id = db.Column(db.Integer, primary_key=True)
    habit_id = db.Column(db.Integer, db.ForeignKey('habits.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(20), default='completed', nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    # Unique constraint ensuring only one log per habit per calendar day
    __table_args__ = (
        db.UniqueConstraint('habit_id', 'date', name='uq_habit_date'),
    )

    def to_dict(self) -> Dict[str, Any]:
        """
        Serializes habit log into dictionary format.
        
        Returns:
            dict: Log details.
        """
        return {
            'id': self.id,
            'habit_id': self.habit_id,
            'user_id': self.user_id,
            'date': self.date.isoformat() if self.date else None,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Mood(db.Model):
    """
    Represents a daily emotional wellbeing check-in record.
    Tracks emotional state ('happy', 'neutral', 'sad') along with an optional reflective note.
    """
    __tablename__ = 'moods'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    mood = db.Column(db.String(20), nullable=False)  # 'happy', 'neutral', 'sad'
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    # Unique constraint ensuring at most one primary mood log per user per day
    __table_args__ = (
        db.UniqueConstraint('user_id', 'date', name='uq_mood_date'),
    )

    def to_dict(self) -> Dict[str, Any]:
        """
        Serializes mood check-in data into a JSON dictionary.
        
        Returns:
            dict: Mood log summary.
        """
        return {
            'id': self.id,
            'user_id': self.user_id,
            'date': self.date.isoformat() if self.date else None,
            'mood': self.mood,
            'note': self.note,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Badge(db.Model):
    """
    Defines an achievement badge that users can unlock by meeting streak,
    completion, or consistency milestones.
    """
    __tablename__ = 'badges'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=False)
    icon = db.Column(db.String(50), nullable=False)
    category = db.Column(db.String(50), default='streak', nullable=False)  # 'streak', 'completion', 'special'

    # Relationship to user unlocks
    user_badges = db.relationship('UserBadge', backref='badge', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self) -> Dict[str, Any]:
        """
        Serializes badge definition into dictionary format.
        
        Returns:
            dict: Badge details.
        """
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'icon': self.icon,
            'category': self.category
        }


class UserBadge(db.Model):
    """
    Junction table recording which badges have been unlocked by each user,
    together with the exact timestamp of achievement.
    """
    __tablename__ = 'user_badges'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    badge_id = db.Column(db.Integer, db.ForeignKey('badges.id', ondelete='CASCADE'), nullable=False, index=True)
    earned_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    # Unique constraint ensuring users cannot be awarded the same badge multiple times
    __table_args__ = (
        db.UniqueConstraint('user_id', 'badge_id', name='uq_user_badge'),
    )

    def to_dict(self) -> Dict[str, Any]:
        """
        Serializes user badge achievement into dictionary format.
        
        Returns:
            dict: Badge achievement record with badge details.
        """
        badge_info = self.badge.to_dict() if self.badge else None
        return {
            'id': self.id,
            'user_id': self.user_id,
            'badge_id': self.badge_id,
            'earned_at': self.earned_at.isoformat() if self.earned_at else None,
            'badge': badge_info
        }


class AIMessage(db.Model):
    """
    Stores AI-generated coaching messages, performance reviews, and behavioral insights.
    Caches outputs by date and message type to minimize external API costs and latency.
    """
    __tablename__ = 'ai_messages'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    message_type = db.Column(db.String(50), nullable=False)  # 'daily', 'weekly', 'recommendation', 'mood_insight'
    content = db.Column(db.Text, nullable=False)
    date = db.Column(db.Date, default=date.today, nullable=False, index=True)
    generated_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    cached = db.Column(db.Boolean, default=True, nullable=False)

    # Constraint to prevent duplicate cached messages of the same type on the same day
    __table_args__ = (
        db.UniqueConstraint('user_id', 'message_type', 'date', name='uq_user_message_date'),
    )

    def to_dict(self) -> Dict[str, Any]:
        """
        Serializes AI message into dictionary format.
        
        Returns:
            dict: AI coaching message metadata.
        """
        return {
            'id': self.id,
            'user_id': self.user_id,
            'message_type': self.message_type,
            'content': self.content,
            'date': self.date.isoformat() if self.date else None,
            'generated_at': self.generated_at.isoformat() if self.generated_at else None,
            'cached': self.cached
        }


def seed_default_badges() -> None:
    """
    Initializes standard achievement badges in the database if they do not yet exist.
    Called on application startup.
    """
    default_badges = [
        # Streak-based badges
        {
            'name': 'First Week',
            'description': 'Complete a habit for 7 days straight',
            'icon': '🔥',
            'category': 'streak'
        },
        {
            'name': 'Two Weeks Strong',
            'description': 'Complete a habit for 14 days straight',
            'icon': '💪',
            'category': 'streak'
        },
        {
            'name': 'Monthly Master',
            'description': 'Complete a habit for 30 days straight',
            'icon': '👑',
            'category': 'streak'
        },
        # Completion-based badges
        {
            'name': 'Getting Started',
            'description': 'Log 10 habit completions',
            'icon': '🚀',
            'category': 'completion'
        },
        {
            'name': 'Habit Builder',
            'description': 'Log 50 habit completions',
            'icon': '🏗️',
            'category': 'completion'
        },
        {
            'name': 'Centennial',
            'description': 'Log 100 habit completions',
            'icon': '💯',
            'category': 'completion'
        },
        {
            'name': 'Consistency King',
            'description': 'Log 200 habit completions',
            'icon': '👑',
            'category': 'completion'
        },
        {
            'name': 'Yearly Champion',
            'description': 'Log 365 habit completions',
            'icon': '🎯',
            'category': 'completion'
        }
    ]

    for badge_data in default_badges:
        existing = Badge.query.filter_by(name=badge_data['name']).first()
        if not existing:
            badge = Badge(
                name=badge_data['name'],
                description=badge_data['description'],
                icon=badge_data['icon'],
                category=badge_data['category']
            )
            db.session.add(badge)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Warning: Failed to seed default badges: {e}")

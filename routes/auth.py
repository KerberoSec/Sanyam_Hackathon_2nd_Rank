"""
HabitFlow Authentication Routes
================================
This module handles user registration, JWT login authentication, token verification,
current session inspection, and user profile management.
"""

import os
import re
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Callable, Any

import jwt
from flask import Blueprint, request, jsonify, session, current_app
from models import User, Badge, UserBadge, db

# Create auth blueprint with standard URL prefix
auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

# Regular expression pattern for email validation
EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$')


def get_jwt_secret() -> str:
    """
    Retrieves the JWT secret key from Flask current application configuration.
    Falls back to environment variable or secure default.
    
    Returns:
        str: Secret key used to sign and verify JWT tokens.
    """
    return current_app.config.get(
        'JWT_SECRET_KEY',
        os.environ.get('JWT_SECRET_KEY', 'jwt-secret-key-change-in-production-habitflow')
    )


def token_required(f: Callable) -> Callable:
    """
    Decorator for API endpoints that require authentication.
    Extracts the Bearer token from the HTTP Authorization header, verifies signature
    and expiration, and injects the authenticated User instance as the first argument.
    
    Args:
        f: The route handler function to decorate.
        
    Returns:
        Callable: Wrapped route handler checking credentials before execution.
    """
    @wraps(f)
    def decorated(*args: Any, **kwargs: Any):
        token = None

        # Check for Authorization header
        auth_header = request.headers.get('Authorization', None)
        if auth_header:
            parts = auth_header.strip().split()
            if len(parts) == 2 and parts[0].lower() == 'bearer':
                token = parts[1]
            elif len(parts) == 1:
                token = parts[0]
            else:
                return jsonify({'message': 'Invalid Authorization header format. Expected "Bearer <token>"'}), 401

        # Check query parameters as secondary fallback (useful for downloads or websockets)
        if not token and 'token' in request.args:
            token = request.args.get('token')

        if not token:
            return jsonify({'message': 'Authentication token is missing. Please log in.'}), 401

        try:
            secret = get_jwt_secret()
            payload = jwt.decode(token, secret, algorithms=['HS256'])
            user_id = payload.get('user_id')

            if not user_id:
                return jsonify({'message': 'Token payload missing user identifier'}), 401

            # Fetch user from database
            current_user = db.session.get(User, user_id)
            if not current_user:
                return jsonify({'message': 'User associated with this token no longer exists'}), 401

        except jwt.ExpiredSignatureError:
            return jsonify({'message': 'Authentication token has expired. Please log in again.'}), 401
        except jwt.InvalidTokenError as e:
            return jsonify({'message': f'Invalid authentication token: {str(e)}'}), 401
        except Exception as e:
            return jsonify({'message': f'Authentication failure: {str(e)}'}), 401

        # Pass authenticated user object to the wrapped route
        return f(current_user, *args, **kwargs)

    return decorated


@auth_bp.route('/register', methods=['POST'])
def register():
    """
    Registers a new user account with name, email, and password.
    Validates input fields, checks for duplicate email, securely hashes password,
    creates the user record, and seeds default badges if needed.
    
    Returns:
        JSON response with user details and HTTP 201 on success, or error message.
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'message': 'Request payload must be valid JSON'}), 400

    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    # Validate presence of required fields
    if not name or not email or not password:
        return jsonify({'message': 'Name, email, and password are all required fields.'}), 400

    # Validate name length
    if len(name) < 2 or len(name) > 100:
        return jsonify({'message': 'Name must be between 2 and 100 characters.'}), 400

    # Validate email format
    if not EMAIL_REGEX.match(email):
        return jsonify({'message': 'Please provide a valid email address.'}), 400

    # Validate password complexity
    if len(password) < 6:
        return jsonify({'message': 'Password must be at least 6 characters long.'}), 400

    # Check for duplicate registration
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        return jsonify({'message': 'An account with this email address already exists.'}), 400

    try:
        # Create new user instance
        user = User(
            name=name,
            email=email,
            xp_points=0,
            level=1
        )
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        # Generate JWT token for immediate access
        secret = get_jwt_secret()
        expires_delta = current_app.config.get('JWT_ACCESS_TOKEN_EXPIRES', timedelta(days=30))
        now = datetime.now(timezone.utc)
        payload = {
            'user_id': user.id,
            'email': user.email,
            'iat': now,
            'exp': now + expires_delta
        }
        token = jwt.encode(payload, secret, algorithm='HS256')

        # Synchronize Flask session
        session['user_id'] = user.id
        session['user_name'] = user.name

        return jsonify({
            'message': 'Account registered successfully!',
            'token': token,
            'user': user.to_dict()
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'message': f'Registration failed due to a server error: {str(e)}'}), 500


@auth_bp.route('/login', methods=['POST'])
def login():
    """
    Authenticates user credentials and issues a signed JWT token.
    Updates server session and returns user profile details.
    
    Returns:
        JSON response containing JWT token, user info, and HTTP 200 on success.
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'message': 'Request payload must be valid JSON'}), 400

    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'message': 'Please provide both email and password.'}), 400

    user = User.query.filter_by(email=email).first()

    if not user or not user.check_password(password):
        return jsonify({'message': 'Invalid email or password combination.'}), 401

    # Issue signed JWT token with expiration timestamp
    secret = get_jwt_secret()
    expires_delta = current_app.config.get('JWT_ACCESS_TOKEN_EXPIRES', timedelta(days=30))
    now = datetime.now(timezone.utc)
    payload = {
        'user_id': user.id,
        'email': user.email,
        'iat': now,
        'exp': now + expires_delta
    }
    token = jwt.encode(payload, secret, algorithm='HS256')

    # Maintain session state for server-rendered components
    session['user_id'] = user.id
    session['user_name'] = user.name

    return jsonify({
        'message': 'Login successful',
        'token': token,
        'user': user.to_dict()
    }), 200


@auth_bp.route('/me', methods=['GET'])
@token_required
def get_current_user(current_user: User):
    """
    Returns full profile details and gamification statistics for the authenticated user.
    
    Args:
        current_user: The authenticated User object injected by @token_required.
        
    Returns:
        JSON response with user profile, level, XP, and badge counts.
    """
    earned_badges_count = current_user.user_badges.count()
    total_habits_count = current_user.habits.filter_by(active=True).count()

    user_data = current_user.to_dict()
    user_data['badges_count'] = earned_badges_count
    user_data['habits_count'] = total_habits_count

    return jsonify({
        'user': user_data
    }), 200


@auth_bp.route('/profile', methods=['PUT'])
@token_required
def update_profile(current_user: User):
    """
    Updates profile details such as name and/or password for the authenticated user.
    
    Args:
        current_user: The authenticated User object.
        
    Returns:
        JSON response with updated user profile.
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'message': 'Request payload must be valid JSON'}), 400

    name = data.get('name')
    if name is not None:
        name = name.strip()
        if len(name) < 2 or len(name) > 100:
            return jsonify({'message': 'Name must be between 2 and 100 characters.'}), 400
        current_user.name = name
        session['user_name'] = name

    # Optional password change
    old_password = data.get('old_password')
    new_password = data.get('new_password')
    if new_password:
        if not old_password:
            return jsonify({'message': 'Current password is required to set a new password.'}), 400
        if not current_user.check_password(old_password):
            return jsonify({'message': 'Current password is incorrect.'}), 400
        if len(new_password) < 6:
            return jsonify({'message': 'New password must be at least 6 characters long.'}), 400
        current_user.set_password(new_password)

    try:
        db.session.commit()
        return jsonify({
            'message': 'Profile updated successfully',
            'user': current_user.to_dict()
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': f'Failed to update profile: {str(e)}'}), 500


@auth_bp.route('/badges', methods=['GET'])
@token_required
def get_user_badges(current_user: User):
    """
    Returns list of all available badges in the system, indicating which ones
    have been unlocked by the current user and when.
    
    Args:
        current_user: The authenticated User object.
        
    Returns:
        JSON response with badges list including unlocked status.
    """
    from services.gamification import GamificationEngine
    badges = GamificationEngine.get_all_badges_with_user_status(current_user.id)
    return jsonify({'badges': badges}), 200


@auth_bp.route('/logout', methods=['POST'])
def logout():
    """
    Logs out user by clearing server session cookies.
    Client-side code removes the stored JWT token from localStorage.
    
    Returns:
        JSON response confirming logout.
    """
    session.pop('user_id', None)
    session.pop('user_name', None)
    session.clear()
    return jsonify({'message': 'Logout successful. Token invalidated client-side.'}), 200

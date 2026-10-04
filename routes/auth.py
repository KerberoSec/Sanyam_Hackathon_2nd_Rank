"""
HabitFlow Authentication Routes
================================
This module handles user registration, JWT login authentication, token verification,
rate-limited endpoints, current session inspection, profile management, and secure password recovery.
"""

import os
import re
import smtplib
import time
import hashlib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from functools import wraps
from typing import Callable, Any, Optional
from urllib.parse import quote

import jwt
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from flask import Blueprint, request, jsonify, session, current_app
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from models import User, RateLimitBucket, db
from werkzeug.security import generate_password_hash

# Create auth blueprint with standard URL prefix
auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

# Regular expression pattern for email validation
EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$')

# Pre-computed dummy password hash to prevent side-channel timing attacks on login
DUMMY_PASSWORD_HASH = (
    "scrypt:32768:8:1$N2VlM2RmMjU3Mzg$90f38bbf37efabf88126b7c2514101168128228df77227d8cecc83c1624c6e94"
    "ef3381fa6cae43b17173e449c2dd9427b0c80c2f82ba40fec7d8122c92e927c3"
)


def rate_limit(max_requests: int = 15, window_seconds: int = 60):
    """
    Database-backed fixed-window rate limiter shared by all application workers.

    Args:
        max_requests: Maximum allowed calls in the given window.
        window_seconds: Size of sliding window in seconds.
    """
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def wrapped(*args: Any, **kwargs: Any):
            # Bypass rate limiter during automated testing
            if current_app.config.get('TESTING'):
                return f(*args, **kwargs)

            # Trust the socket peer. X-Forwarded-For is attacker-controlled unless
            # a specifically configured trusted proxy middleware sanitizes it.
            ip = request.remote_addr or '127.0.0.1'
            now = time.time()
            window_start = int(now // window_seconds) * window_seconds
            expires_at = window_start + (window_seconds * 2)
            raw_key = f'{f.__module__}:{f.__name__}:{ip}:{window_start}'
            bucket_key = hashlib.sha256(raw_key.encode('utf-8')).hexdigest()
            bucket_table = RateLimitBucket.__table__

            try:
                db.session.execute(
                    delete(bucket_table).where(bucket_table.c.expires_at < int(now))
                )
                values = {'bucket_key': bucket_key, 'attempts': 1, 'expires_at': expires_at}
                dialect = db.engine.dialect.name
                if dialect == 'sqlite':
                    statement = sqlite_insert(bucket_table).values(**values).on_conflict_do_update(
                        index_elements=[bucket_table.c.bucket_key],
                        set_={'attempts': bucket_table.c.attempts + 1},
                    )
                    db.session.execute(statement)
                    attempts = db.session.execute(
                        select(bucket_table.c.attempts).where(bucket_table.c.bucket_key == bucket_key)
                    ).scalar_one()
                elif dialect == 'postgresql':
                    statement = postgresql_insert(bucket_table).values(**values).on_conflict_do_update(
                        index_elements=[bucket_table.c.bucket_key],
                        set_={'attempts': bucket_table.c.attempts + 1},
                    ).returning(bucket_table.c.attempts)
                    attempts = db.session.execute(statement).scalar_one()
                elif dialect == 'mysql':
                    statement = mysql_insert(bucket_table).values(**values).on_duplicate_key_update(
                        attempts=bucket_table.c.attempts + 1,
                    )
                    db.session.execute(statement)
                    attempts = db.session.execute(
                        select(bucket_table.c.attempts).where(bucket_table.c.bucket_key == bucket_key)
                    ).scalar_one()
                else:
                    try:
                        db.session.execute(bucket_table.insert().values(**values))
                        attempts = 1
                    except Exception:
                        db.session.rollback()
                        db.session.execute(
                            bucket_table.update()
                            .where(bucket_table.c.bucket_key == bucket_key)
                            .values(attempts=bucket_table.c.attempts + 1)
                        )
                        attempts = db.session.execute(
                            select(bucket_table.c.attempts).where(bucket_table.c.bucket_key == bucket_key)
                        ).scalar_one()
                db.session.commit()
            except Exception:
                db.session.rollback()
                current_app.logger.exception('Shared authentication rate limiter is unavailable')
                return jsonify({'message': 'Authentication is temporarily unavailable. Please try again.'}), 503

            if attempts > max_requests:
                return jsonify({'message': 'Too many requests. Please wait a minute and try again.'}), 429
            return f(*args, **kwargs)
        return wrapped
    return decorator


def get_jwt_secret() -> str:
    """
    Retrieves the JWT secret key from Flask current application configuration.
    Falls back to environment variable or default.

    Returns:
        str: Secret key used to sign and verify JWT tokens.
    """
    return current_app.config.get(
        'JWT_SECRET_KEY',
        os.environ.get('JWT_SECRET_KEY', 'jwt-secret-key-change-in-production-habitflow')
    )


def get_serializer() -> URLSafeTimedSerializer:
    """
    Initializes a timed serializer for secure one-time password reset tokens.

    Returns:
        URLSafeTimedSerializer: Configured serializer instance.
    """
    secret = current_app.config.get('SECRET_KEY', 'dev-secret-key-change-in-production-habitflow')
    return URLSafeTimedSerializer(secret)


def _send_password_reset_email(user: User, reset_token: str) -> None:
    """Send a timed reset link through the configured SMTP server."""
    mail_server = current_app.config.get('MAIL_SERVER')
    sender = current_app.config.get('MAIL_DEFAULT_SENDER')
    if not mail_server or not sender:
        raise RuntimeError('Password reset email is not configured.')

    frontend_url = current_app.config.get('FRONTEND_URL', '').rstrip('/')
    reset_url = f"{frontend_url}/login?reset_token={quote(reset_token)}"
    message = EmailMessage()
    message['Subject'] = 'Reset your HabitFlow password'
    message['From'] = sender
    message['To'] = user.email
    message.set_content(
        'Use this one-time link to reset your HabitFlow password. '
        f'The link expires in one hour.\n\n{reset_url}\n'
    )

    mail_port = current_app.config.get('MAIL_PORT', 587)
    uses_implicit_tls = mail_port == 465
    smtp_client = smtplib.SMTP_SSL if uses_implicit_tls else smtplib.SMTP
    with smtp_client(mail_server, mail_port, timeout=10) as smtp:
        if current_app.config.get('MAIL_USE_TLS', True) and not uses_implicit_tls:
            smtp.starttls()
        username = current_app.config.get('MAIL_USERNAME')
        password = current_app.config.get('MAIL_PASSWORD')
        if username:
            smtp.login(username, password or '')
        smtp.send_message(message)


def generate_token(user: User, remember: bool = True) -> str:
    """
    Generates a cryptographically signed JWT access token embedded with user ID and token version.

    Args:
        user: Target User instance.
        remember: Whether to extend token validity (30 days vs 1 day).

    Returns:
        str: Encoded JWT token.
    """
    secret = get_jwt_secret()
    if remember:
        expires_delta = current_app.config.get('JWT_ACCESS_TOKEN_EXPIRES', timedelta(days=30))
    else:
        expires_delta = timedelta(days=1)

    now = datetime.now(timezone.utc)
    payload = {
        'user_id': user.id,
        'email': user.email,
        'token_version': user.token_version,
        'iat': now,
        'exp': now + expires_delta
    }
    return jwt.encode(payload, secret, algorithm='HS256')


def get_authenticated_user_from_request() -> Optional[User]:
    """
    Extracts and verifies the current authenticated user from:
    1. Authorization: Bearer <token> header
    2. auth_token HTTP cookie
    3. Flask session['user_id']

    Verifies JWT token signature, expiration, and database token_version.
    Returns User instance if authenticated and valid, else None.
    """
    token = None
    auth_header = request.headers.get('Authorization', None)
    if auth_header:
        parts = auth_header.strip().split()
        if len(parts) == 2 and parts[0].lower() == 'bearer':
            token = parts[1]

    if not token and 'auth_token' in request.cookies:
        token = request.cookies.get('auth_token')

    if token:
        try:
            secret = get_jwt_secret()
            payload = jwt.decode(token, secret, algorithms=['HS256'])
            user_id = payload.get('user_id')
            if not user_id:
                return None
            user = db.session.get(User, user_id)
            if not user:
                return None
            token_version = payload.get('token_version', 1)
            if token_version != user.token_version:
                return None
            return user
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, Exception):
            return None

    # Fallback to session only if no token was presented
    user_id = session.get('user_id')
    if user_id:
        user = db.session.get(User, user_id)
        if user:
            return user

    return None


def token_required(f: Callable) -> Callable:
    """
    Decorator for API endpoints that require authentication.
    Extracts the Bearer token from the HTTP Authorization header or auth_token cookie,
    verifies signature, expiration, and token_version, and injects the authenticated User instance.

    Args:
        f: The route handler function to decorate.

    Returns:
        Callable: Wrapped route handler checking credentials before execution.
    """
    @wraps(f)
    def decorated(*args: Any, **kwargs: Any):
        token = None

        # Check for standard Authorization: Bearer <token> header
        auth_header = request.headers.get('Authorization', None)
        if auth_header:
            parts = auth_header.strip().split()
            if len(parts) == 2 and parts[0].lower() == 'bearer':
                token = parts[1]
            else:
                return jsonify({'message': 'Invalid Authorization header format. Expected "Bearer <token>"'}), 401
        elif 'auth_token' in request.cookies:
            token = request.cookies.get('auth_token')

        if not token:
            return jsonify({'message': 'Authentication token is missing. Please log in.'}), 401

        try:
            secret = get_jwt_secret()
            payload = jwt.decode(token, secret, algorithms=['HS256'])
            user_id = payload.get('user_id')

            if not user_id:
                return jsonify({'message': 'Token payload missing user identifier'}), 401

            current_user = db.session.get(User, user_id)
            if not current_user:
                return jsonify({'message': 'User associated with this token no longer exists'}), 401

            token_version = payload.get('token_version', 1)
            if token_version != current_user.token_version:
                return jsonify({'message': 'Authentication token has been revoked. Please log in again.'}), 401

        except jwt.ExpiredSignatureError:
            return jsonify({'message': 'Authentication token has expired. Please log in again.'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'message': 'Invalid authentication token.'}), 401
        except Exception as e:
            current_app.logger.warning(f"Authentication failure: {e}")
            return jsonify({'message': 'Authentication failure. Please authenticate again.'}), 401

        return f(current_user, *args, **kwargs)

    return decorated


@auth_bp.route('/register', methods=['POST'])
@rate_limit(max_requests=10, window_seconds=60)
def register():
    """
    Registers a new user account with name, email, and password.
    Validates input fields, checks for duplicate email, securely hashes password,
    creates the user record, and seeds default badges if needed.

    Returns:
        JSON response with user details and HTTP 201 on success, or error message.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'message': 'Request payload must be valid JSON'}), 400

    raw_name = data.get('name') or data.get('username') or ''
    raw_email = data.get('email', '')
    password = data.get('password', '')
    if not isinstance(raw_name, str) or not isinstance(raw_email, str) or not isinstance(password, str):
        return jsonify({'message': 'Name, email, and password must be text values.'}), 400
    name = raw_name.strip()
    email = raw_email.strip().lower()

    if not name or not email or not password:
        return jsonify({'message': 'Name, email, and password are all required fields.'}), 400

    if len(name) < 2 or len(name) > 100:
        return jsonify({'message': 'Name must be between 2 and 100 characters.'}), 400

    if not EMAIL_REGEX.match(email):
        return jsonify({'message': 'Please provide a valid email address.'}), 400
    if len(email) > 120:
        return jsonify({'message': 'Email address must not exceed 120 characters.'}), 400

    if len(password) < 8:
        return jsonify({'message': 'Password must be at least 8 characters long.'}), 400
    if len(password) > 1024:
        return jsonify({'message': 'Password must not exceed 1,024 characters.'}), 400

    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        return jsonify({'message': 'An account with this email address already exists.'}), 400

    try:
        user = User(
            name=name,
            email=email,
            xp_points=0,
            level=1,
            token_version=1
        )
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        token = generate_token(user, remember=True)

        session['user_id'] = user.id
        session['user_name'] = user.name

        resp = jsonify({
            'message': 'Account registered successfully!',
            'token': token,
            'user': user.to_dict()
        })
        resp.set_cookie(
            'auth_token',
            token,
            httponly=True,
            samesite='Lax',
            secure=current_app.config.get('SESSION_COOKIE_SECURE', False),
            max_age=30 * 86400
        )
        return resp, 201

    except IntegrityError:
        db.session.rollback()
        # A concurrent request may have inserted the same email after the
        # preflight check. Keep that race on the same client-error path.
        return jsonify({'message': 'An account with this email address already exists.'}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Registration failure: {e}")
        return jsonify({'message': 'Registration failed due to a server error. Please try again later.'}), 500


@auth_bp.route('/login', methods=['POST'])
@rate_limit(max_requests=15, window_seconds=60)
def login():
    """
    Authenticates user credentials and issues a signed JWT token.
    Updates server session and returns user profile details.
    Uses constant-time verification to prevent timing attack enumeration.

    Returns:
        JSON response containing JWT token, user info, and HTTP 200 on success.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'message': 'Request payload must be valid JSON'}), 400

    identifier_value = data.get('email') or data.get('username') or ''
    password = data.get('password', '')
    remember = data.get('remember', True)
    if not isinstance(identifier_value, str) or not isinstance(password, str) or not isinstance(remember, bool):
        return jsonify({'message': 'Email, password, and remember values have invalid types.'}), 400
    identifier = identifier_value.strip().lower()

    if not identifier or not password:
        return jsonify({'message': 'Please provide both email (or username) and password.'}), 400
    if len(password) > 1024:
        return jsonify({'message': 'Password must not exceed 1,024 characters.'}), 400

    user = User.query.filter_by(email=identifier).first()
    if not user:
        # Display names are not unique. Accept them only when the lookup is
        # unambiguous, and cap the query so password hashing stays bounded.
        matching_names = User.query.filter(db.func.lower(User.name) == identifier).limit(2).all()
        if len(matching_names) == 1:
            user = matching_names[0]
        else:
            from werkzeug.security import check_password_hash
            check_password_hash(DUMMY_PASSWORD_HASH, password)
            return jsonify({'message': 'Invalid credentials provided.'}), 401

    if not user.check_password(password):
        return jsonify({'message': 'Invalid credentials provided.'}), 401

    token = generate_token(user, remember=remember)

    session['user_id'] = user.id
    session['user_name'] = user.name

    resp = jsonify({
        'message': 'Login successful',
        'token': token,
        'user': user.to_dict()
    })
    max_age = (30 * 86400) if remember else 86400
    resp.set_cookie(
        'auth_token',
        token,
        httponly=True,
        samesite='Lax',
        secure=current_app.config.get('SESSION_COOKIE_SECURE', False),
        max_age=max_age
    )
    return resp, 200


@auth_bp.route('/me', methods=['GET'])
@auth_bp.route('/profile', methods=['GET'])
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
    If password is changed, invalidates prior tokens by incrementing token_version.

    Args:
        current_user: The authenticated User object.

    Returns:
        JSON response with updated user profile and a fresh token if password was changed.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'message': 'Request payload must be valid JSON'}), 400

    name = data.get('name')
    if name is not None:
        if not isinstance(name, str):
            return jsonify({'message': 'Name must be a text value.'}), 400
        name = name.strip()
        if len(name) < 2 or len(name) > 100:
            return jsonify({'message': 'Name must be between 2 and 100 characters.'}), 400
        current_user.name = name
        session['user_name'] = name

    new_token = None
    old_password = data.get('old_password')
    new_password = data.get('new_password')
    if old_password is not None and not isinstance(old_password, str):
        return jsonify({'message': 'Current password must be a text value.'}), 400
    if new_password is not None and not isinstance(new_password, str):
        return jsonify({'message': 'New password must be a text value.'}), 400
    if new_password:
        if not old_password:
            return jsonify({'message': 'Current password is required to set a new password.'}), 400
        if not current_user.check_password(old_password):
            return jsonify({'message': 'Current password is incorrect.'}), 400
        if len(new_password) < 8:
            return jsonify({'message': 'New password must be at least 8 characters long.'}), 400
        if len(new_password) > 1024:
            return jsonify({'message': 'New password must not exceed 1,024 characters.'}), 400
        current_user.set_password(new_password)
        current_user.token_version += 1
        new_token = generate_token(current_user)

    try:
        db.session.commit()
        response_data = {
            'message': 'Profile updated successfully',
            'user': current_user.to_dict()
        }
        if new_token:
            response_data['token'] = new_token
        resp = jsonify(response_data)
        if new_token:
            resp.set_cookie(
                'auth_token',
                new_token,
                httponly=True,
                samesite='Lax',
                secure=current_app.config.get('SESSION_COOKIE_SECURE', False),
                max_age=30 * 86400
            )
        return resp, 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Profile update failure: {e}")
        return jsonify({'message': 'Failed to update profile due to an internal server error.'}), 500


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
@rate_limit(max_requests=30, window_seconds=60)
@token_required
def logout(current_user: User):
    """
    Logs out user by clearing server session cookies and invalidating tokens server-side
    by advancing user token_version when an Authorization header is provided.

    Returns:
        JSON response confirming logout.
    """
    session.clear()
    current_user.token_version += 1
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Logout token revocation failed')
        return jsonify({'message': 'Could not complete logout. Please try again.'}), 500
    resp = jsonify({'message': 'Logout successful. Token invalidated.'})
    resp = jsonify({'message': 'Logout successful. Token invalidated.'})
    resp.delete_cookie('auth_token')
    return resp, 200

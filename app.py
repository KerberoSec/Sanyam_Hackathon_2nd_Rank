"""
HabitFlow Main Application Factory
==================================
This module initializes the Flask WSGI application, registers blueprints,
configures CORS and database bindings, registers custom error handlers,
and provisions default achievement badges upon startup.
"""

import os
from datetime import datetime, timezone
from flask import Flask, render_template, jsonify, request, current_app, redirect, url_for
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from sqlalchemy import event
from sqlalchemy import inspect, text

from config import config
from models import db, seed_default_badges
from routes.auth import auth_bp, get_authenticated_user_from_request
from routes.habits import habits_bp
from routes.analytics import analytics_bp
from routes.mood import mood_bp
from routes.ai import ai_bp


def _configure_sqlite_pragma(app: Flask):
    """Enforces SQLite foreign key referential integrity on database connect."""

    with app.app_context():
        engine = db.engine
        if engine.dialect.name != 'sqlite':
            return

    def set_sqlite_pragma(dbapi_connection, connection_record):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
        except Exception as error:
            app.logger.warning("Could not enable SQLite foreign keys: %s", error)

    # Attach to this app's engine so repeated app-factory calls do not add
    # duplicate listeners to SQLAlchemy's global Engine class.
    event.listen(engine, "connect", set_sqlite_pragma)


def _configure_security_headers(app: Flask):
    """Configures modern HTTP security headers and Content Security Policy."""
    @app.after_request
    def set_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'geolocation=(), camera=(), microphone=()'
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net "
            "https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
            "font-src 'self' https://cdnjs.cloudflare.com https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self';"
        )
        response.headers['Content-Security-Policy'] = csp
        return response


def _register_blueprints(app: Flask):
    """Registers API blueprints."""
    app.register_blueprint(auth_bp)
    app.register_blueprint(habits_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(mood_bp)
    app.register_blueprint(ai_bp)


def _register_page_routes(app: Flask, config_name: str):
    """Registers public HTML frontend and health check routes."""
    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/dashboard')
    def dashboard():
        current_user = get_authenticated_user_from_request()
        if not current_user:
            return redirect('/login?next=/dashboard')
        return render_template('dashboard.html')

    @app.route('/login')
    def login():
        current_user = get_authenticated_user_from_request()
        if current_user:
            return redirect('/dashboard')
        return render_template('login.html')

    @app.route('/register')
    def register():
        current_user = get_authenticated_user_from_request()
        if current_user:
            return redirect('/dashboard')
        return render_template('register.html')

    @app.route('/habit/<int:habit_id>')
    def habit_detail(habit_id: int):
        current_user = get_authenticated_user_from_request()
        if not current_user:
            return redirect(f'/login?next=/habit/{habit_id}')
        return render_template('habit_detail.html', habit_id=habit_id)

    @app.route('/about')
    def about():
        return render_template('about.html')

    @app.route('/privacy')
    def privacy():
        return render_template('privacy.html')

    @app.route('/terms')
    def terms():
        return render_template('terms.html')

    @app.route('/health')
    @app.route('/api/health')
    def health_check():
        if not current_app.extensions.get('habitflow_database_ready', False):
            return jsonify({'status': 'unhealthy', 'app': 'HabitFlow'}), 503
        try:
            with db.engine.connect() as connection:
                connection.execute(text('SELECT 1'))
        except Exception:
            current_app.logger.exception("Database readiness check failed")
            return jsonify({'status': 'unhealthy', 'app': 'HabitFlow'}), 503

        return jsonify({
            'status': 'healthy',
            'app': 'HabitFlow',
            'version': '3.0.3',
            'environment': config_name,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }), 200


def _register_error_handlers(app: Flask):
    """Registers uniform error handlers returning JSON for API requests and HTML for browsers."""
    @app.errorhandler(400)
    def bad_request(error):
        if request.path.startswith('/api/'):
            return jsonify({'message': getattr(error, 'description', 'Bad Request')}), 400
        return render_template('index.html'), 400

    @app.errorhandler(401)
    def unauthorized(error):
        if request.path.startswith('/api/'):
            return jsonify({'message': 'Authentication required. Please log in.'}), 401
        return render_template('login.html'), 401

    @app.errorhandler(404)
    def not_found(error):
        if request.path.startswith('/api/'):
            return jsonify({'message': 'The requested resource was not found on this server.'}), 404
        return render_template('index.html'), 404

    @app.errorhandler(405)
    def method_not_allowed(error):
        if request.path.startswith('/api/'):
            return jsonify({'message': 'HTTP method not allowed for this endpoint.'}), 405
        return render_template('index.html'), 405

    @app.errorhandler(429)
    def rate_limit_exceeded(error):
        if request.path.startswith('/api/'):
            return jsonify({'message': 'Too many requests. Please wait a minute and try again.'}), 429
        return render_template('index.html'), 429

    @app.errorhandler(413)
    def request_too_large(error):
        if request.path.startswith('/api/'):
            return jsonify({'message': 'Request payload is too large.'}), 413
        return render_template('index.html'), 413

    @app.errorhandler(500)
    def server_error(error):
        if request.path.startswith('/api/'):
            return jsonify({'message': 'An internal server error occurred. Please try again later.'}), 500
        return render_template('index.html'), 500


def _apply_compatibility_migrations(engine):
    """Apply the small in-place schema upgrades used by existing installs."""
    def migrate(connection):
        user_columns = {column['name'] for column in inspect(connection).get_columns('users')}
        if 'token_version' not in user_columns:
            connection.execute(text(
                'ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 1'
            ))

        log_columns = {column['name'] for column in inspect(connection).get_columns('habit_logs')}
        if 'xp_awarded' not in log_columns:
            connection.execute(text(
                'ALTER TABLE habit_logs ADD COLUMN xp_awarded INTEGER NOT NULL DEFAULT 0'
            ))
            # Completed logs from older versions may already have paid XP but
            # did not store a per-log reward marker. Keep them finalized so an
            # API retry after upgrade cannot pay them a second time.
            connection.execute(text(
                "UPDATE habit_logs SET xp_awarded = -1 WHERE status = 'completed'"
            ))

        habit_columns = {column['name'] for column in inspect(connection).get_columns('habits')}
        if 'created_date' not in habit_columns:
            connection.execute(text('ALTER TABLE habits ADD COLUMN created_date DATE'))
        # Keep these backfills idempotent and outside the add-column branches:
        # MySQL commits DDL separately, so a restart can occur after ALTER TABLE
        # but before its data backfill.
        connection.execute(text(
            'UPDATE habits SET created_date = DATE(created_at) WHERE created_date IS NULL'
        ))

        habit_columns = {column['name'] for column in inspect(connection).get_columns('habits')}
        if 'archived_date' not in habit_columns:
            connection.execute(text('ALTER TABLE habits ADD COLUMN archived_date DATE'))
        # Legacy archives have no exact timestamp. Use their last recorded
        # activity as a conservative end date for historical denominators.
        connection.execute(text(
            """UPDATE habits
               SET archived_date = COALESCE(
                   (SELECT MAX(habit_logs.date) FROM habit_logs WHERE habit_logs.habit_id = habits.id),
                   created_date
               )
               WHERE NOT active AND archived_date IS NULL"""
        ))

    if engine.dialect.name == 'sqlite':
        # Serialize concurrent Gunicorn worker startups while they create or
        # upgrade an SQLite schema.
        with engine.connect() as connection:
            try:
                connection.exec_driver_sql('BEGIN IMMEDIATE')
                db.metadata.create_all(bind=connection)
                migrate(connection)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
    elif engine.dialect.name == 'postgresql':
        # Advisory locks serialize application workers while they create or
        # upgrade the shared schema during a rolling startup.
        lock_id = 4815162342
        with engine.connect() as connection:
            connection.execute(text('SELECT pg_advisory_lock(:lock_id)'), {'lock_id': lock_id})
            connection.commit()
            try:
                with connection.begin():
                    db.metadata.create_all(bind=connection)
                    migrate(connection)
            finally:
                connection.execute(text('SELECT pg_advisory_unlock(:lock_id)'), {'lock_id': lock_id})
                connection.commit()
    elif engine.dialect.name == 'mysql':
        with engine.connect() as connection:
            lock_acquired = connection.execute(
                text("SELECT GET_LOCK('habitflow_schema_migration', 30)")
            ).scalar()
            connection.commit()
            if lock_acquired != 1:
                raise RuntimeError('Could not acquire the database schema migration lock.')
            try:
                db.metadata.create_all(bind=connection)
                migrate(connection)
            finally:
                connection.execute(text("SELECT RELEASE_LOCK('habitflow_schema_migration')"))
                connection.commit()
    else:
        with engine.begin() as connection:
            db.metadata.create_all(bind=connection)
            migrate(connection)


def create_app(config_name: str = None) -> Flask:
    """
    Application factory constructing a fully configured Flask instance.

    Args:
        config_name: Configuration profile name ('development', 'testing', 'production').

    Returns:
        Flask: Configured application instance.
    """
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    if config_name not in {'development', 'testing', 'production'}:
        raise ValueError(f"Unknown FLASK_ENV '{config_name}'. Choose development, testing, or production.")

    app = Flask(
        __name__,
        static_folder='static',
        static_url_path='/static',
        template_folder='templates'
    )

    cfg = config.get(config_name, config['default'])
    app.config.from_object(cfg)
    app.extensions['habitflow_database_ready'] = False

    trusted_proxy_count = app.config.get('TRUSTED_PROXY_COUNT', 0)
    if trusted_proxy_count:
        # Trust forwarded client IPs only when the deployment explicitly
        # configures how many reverse proxies sanitize and append the header.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=trusted_proxy_count)

    if hasattr(cfg, 'validate_secrets'):
        cfg.validate_secrets()

    db.init_app(app)

    if config_name == 'development':
        allowed_origins = '*'
    else:
        allowed_origins = [app.config.get('FRONTEND_URL', 'http://localhost:5000')]
    CORS(app, resources={r"/api/*": {"origins": allowed_origins}})

    _configure_sqlite_pragma(app)
    _configure_security_headers(app)
    _register_blueprints(app)
    _register_page_routes(app, config_name)
    _register_error_handlers(app)

    with app.app_context():
        try:
            _apply_compatibility_migrations(db.engine)
            seed_default_badges()
            app.extensions['habitflow_database_ready'] = True
        except Exception as e:
            app.logger.exception("Database initialization failed: %s", e)
            raise

    return app


if __name__ == '__main__':
    # Construct the development app only when this file is run directly. WSGI
    # deployments and imports use the app factory without creating a second app.
    _app_environment = os.environ.get('FLASK_ENV', 'development')
    app = create_app(_app_environment)
    port = int(os.environ.get('PORT', 5000))
    print(f"HabitFlow server starting on http://0.0.0.0:{port} ({_app_environment})")
    app.run(debug=app.config.get('DEBUG', False), host='0.0.0.0', port=port)

"""
HabitFlow Main Application Factory
==================================
This module initializes the Flask WSGI application, registers blueprints,
configures CORS and database bindings, registers custom error handlers,
and provisions default achievement badges upon startup.
"""

import os
from datetime import datetime, timezone
from dotenv import load_dotenv
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS

# Load environment configuration
load_dotenv()

from config import config
from models import db, seed_default_badges
from routes.auth import auth_bp
from routes.habits import habits_bp
from routes.analytics import analytics_bp
from routes.mood import mood_bp
from routes.ai import ai_bp


def create_app(config_name: str = None) -> Flask:
    """
    Application factory constructing a fully configured Flask instance.
    
    Args:
        config_name: Configuration profile name ('development', 'testing', 'production').
                     Defaults to the FLASK_ENV environment variable or 'development'.
                     
    Returns:
        Flask: Configured application instance.
    """
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    app = Flask(
        __name__,
        static_folder='static',
        static_url_path='/static',
        template_folder='templates'
    )

    # Load configuration
    cfg = config.get(config_name, config['default'])
    app.config.from_object(cfg)

    # Initialize extensions
    db.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Register API blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(habits_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(mood_bp)
    app.register_blueprint(ai_bp)

    # ---------------------------------------------------------
    # Frontend Page Routes
    # ---------------------------------------------------------

    @app.route('/')
    def index():
        """Public landing page showcasing features and hero CTA."""
        return render_template('index.html')

    @app.route('/dashboard')
    def dashboard():
        """Main habit tracking dashboard and analytics view."""
        return render_template('dashboard.html')

    @app.route('/login')
    def login():
        """User authentication sign-in page."""
        return render_template('login.html')

    @app.route('/register')
    def register():
        """User account registration page."""
        return render_template('register.html')

    @app.route('/habit/<int:habit_id>')
    def habit_detail(habit_id: int):
        """Granular habit analytics, 30-day heatmap, and trend charts."""
        return render_template('habit_detail.html', habit_id=habit_id)

    # ---------------------------------------------------------
    # Health & Diagnostic Endpoints
    # ---------------------------------------------------------

    @app.route('/health')
    @app.route('/api/health')
    def health_check():
        """Service health check endpoint used by Docker and uptime monitors."""
        return jsonify({
            'status': 'healthy',
            'app': 'HabitFlow',
            'environment': config_name,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }), 200

    # ---------------------------------------------------------
    # Error Handlers
    # ---------------------------------------------------------

    @app.errorhandler(400)
    def bad_request(error):
        """Handler for 400 Bad Request errors."""
        if request.path.startswith('/api/'):
            return jsonify({'message': getattr(error, 'description', 'Bad Request')}), 400
        return render_template('index.html'), 400

    @app.errorhandler(401)
    def unauthorized(error):
        """Handler for 401 Unauthorized errors."""
        if request.path.startswith('/api/'):
            return jsonify({'message': 'Authentication required. Please log in.'}), 401
        return render_template('login.html'), 401

    @app.errorhandler(404)
    def not_found(error):
        """Handler for 404 Resource Not Found errors."""
        if request.path.startswith('/api/'):
            return jsonify({'message': 'The requested resource was not found on this server.'}), 404
        return render_template('index.html'), 404

    @app.errorhandler(405)
    def method_not_allowed(error):
        """Handler for 405 Method Not Allowed errors."""
        if request.path.startswith('/api/'):
            return jsonify({'message': 'HTTP method not allowed for this endpoint.'}), 405
        return render_template('index.html'), 405

    @app.errorhandler(500)
    def server_error(error):
        """Handler for 500 Internal Server errors."""
        if request.path.startswith('/api/'):
            return jsonify({'message': 'An internal server error occurred. Please try again later.'}), 500
        return render_template('index.html'), 500

    # Initialize database tables and seed default achievement badges
    with app.app_context():
        try:
            db.create_all()
            seed_default_badges()
        except Exception as e:
            print(f"Warning: Database initialization error: {e}")

    return app


# Application entry point when run directly
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    flask_env = os.environ.get('FLASK_ENV', 'development')
    app = create_app(flask_env)
    print(f"🔥 HabitFlow server starting on http://0.0.0.0:{port} ({flask_env})")
    app.run(debug=(flask_env == 'development'), host='0.0.0.0', port=port)

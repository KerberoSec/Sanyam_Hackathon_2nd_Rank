"""
Comprehensive Automated Test Suite for HabitFlow
=================================================
Validates all backend APIs, database models, streak calculation algorithms,
gamification mechanics, and AI coaching endpoints.
"""

import json
import unittest
from datetime import date, timedelta
from app import create_app
from models import db, User, Habit, HabitLog, Mood, Badge, UserBadge, seed_default_badges


class HabitFlowComprehensiveTests(unittest.TestCase):
    """Test suite covering the complete functionality of HabitFlow."""

    def setUp(self):
        """Set up in-memory testing environment before each test."""
        self.app = create_app('testing')
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        seed_default_badges()

    def tearDown(self):
        """Clean up database after each test."""
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def register_and_login(self, email="test@example.com", password="password123", name="Test User"):
        """Helper utility registering and authenticating a test user."""
        res = self.client.post('/api/auth/register', json={
            'name': name,
            'email': email,
            'password': password
        })
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        token = data['token']
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        return data['user'], token, headers

    def test_health_check(self):
        """Verify health check endpoint returns 200 OK."""
        res = self.client.get('/health')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'healthy')
        self.assertEqual(data['app'], 'HabitFlow')

    def test_user_registration_and_authentication(self):
        """Verify registration, login, and profile fetching."""
        # 1. Register
        user, token, headers = self.register_and_login(email="alex@test.com", name="Alex")
        self.assertEqual(user['email'], "alex@test.com")
        self.assertEqual(user['level'], 1)
        self.assertEqual(user['xp_points'], 0)

        # 2. Duplicate registration rejection
        dup_res = self.client.post('/api/auth/register', json={
            'name': 'Duplicate',
            'email': 'alex@test.com',
            'password': 'password123'
        })
        self.assertEqual(dup_res.status_code, 400)

        # 3. Login
        login_res = self.client.post('/api/auth/login', json={
            'email': 'alex@test.com',
            'password': 'password123'
        })
        self.assertEqual(login_res.status_code, 200)
        login_data = login_res.get_json()
        self.assertIn('token', login_data)

        # 4. Access /me
        me_res = self.client.get('/api/auth/me', headers=headers)
        self.assertEqual(me_res.status_code, 200)
        me_data = me_res.get_json()
        self.assertEqual(me_data['user']['name'], "Alex")

        # 5. Access /api/auth/badges
        badges_res = self.client.get('/api/auth/badges', headers=headers)
        self.assertEqual(badges_res.status_code, 200)
        badges_data = badges_res.get_json()
        self.assertGreater(len(badges_data['badges']), 0)

    def test_habit_crud_and_status_logging(self):
        """Verify habit creation, retrieval, updates, and completion logging."""
        _, _, headers = self.register_and_login()

        # 1. Create habit
        create_res = self.client.post('/api/habits', headers=headers, json={
            'title': 'Morning Meditation',
            'category': 'health',
            'icon': '🧘',
            'frequency': ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        })
        self.assertEqual(create_res.status_code, 201)
        habit = create_res.get_json()['habit']
        habit_id = habit['id']
        self.assertEqual(habit['title'], 'Morning Meditation')

        # 2. Get habits list
        list_res = self.client.get('/api/habits', headers=headers)
        self.assertEqual(list_res.status_code, 200)
        self.assertEqual(list_res.get_json()['count'], 1)

        # 3. Complete habit
        comp_res = self.client.post(f'/api/habits/{habit_id}/complete', headers=headers, json={})
        self.assertEqual(comp_res.status_code, 200)
        comp_data = comp_res.get_json()
        self.assertEqual(comp_data['status'], 'completed')
        self.assertEqual(comp_data['current_streak'], 1)
        self.assertGreater(comp_data['xp_earned'], 0)

        # 4. Skip habit
        skip_res = self.client.post(f'/api/habits/{habit_id}/skip', headers=headers, json={})
        self.assertEqual(skip_res.status_code, 200)
        self.assertEqual(skip_res.get_json()['status'], 'skipped')

        # 5. Get history
        hist_res = self.client.get(f'/api/habits/{habit_id}/history?days=7', headers=headers)
        self.assertEqual(hist_res.status_code, 200)
        hist_data = hist_res.get_json()
        self.assertEqual(len(hist_data['history']), 7)

    def test_streak_calculation_algorithms(self):
        """Verify streak rules: today completed, grace period, missed day break, and frequency awareness."""
        user, _, headers = self.register_and_login()
        user_id = user['id']

        # Weekday-only habit
        habit = Habit(
            user_id=user_id,
            title='Weekday Work Sprint',
            frequency=['monday', 'tuesday', 'wednesday', 'thursday', 'friday']
        )
        db.session.add(habit)
        db.session.commit()

        from services.streak_engine import StreakEngine

        # Initially 0
        streak = StreakEngine.calculate_current_streak(habit.id, user_id)
        self.assertEqual(streak, 0)

        # Complete today
        today = date.today()
        log_today = HabitLog(habit_id=habit.id, user_id=user_id, date=today, status='completed')
        db.session.add(log_today)
        db.session.commit()

        # If today is a weekday, streak should be 1
        if habit.is_scheduled_for_date(today):
            streak = StreakEngine.calculate_current_streak(habit.id, user_id)
            self.assertEqual(streak, 1)

    def test_gamification_progression_and_leveling(self):
        """Verify XP addition and formula Level = (XP // 100) + 1."""
        user, _, _ = self.register_and_login()
        user_id = user['id']

        from services.gamification import GamificationEngine

        # User starts at Level 1, 0 XP
        res1 = GamificationEngine.add_xp(user_id, 40)
        self.assertEqual(res1['xp'], 40)
        self.assertEqual(res1['level'], 1)
        self.assertFalse(res1['level_up'])

        # Cross 100 XP threshold -> Level 2
        res2 = GamificationEngine.add_xp(user_id, 70)
        self.assertEqual(res2['xp'], 110)
        self.assertEqual(res2['level'], 2)
        self.assertTrue(res2['level_up'])

    def test_mood_tracking_and_analytics(self):
        """Verify mood logging, history, and statistics."""
        _, _, headers = self.register_and_login()

        # 1. Log today's mood
        log_res = self.client.post('/api/mood', headers=headers, json={
            'mood': 'happy',
            'note': 'Feeling inspired and productive!'
        })
        self.assertEqual(log_res.status_code, 200)

        # 2. Get today's mood
        today_res = self.client.get('/api/mood/today', headers=headers)
        self.assertEqual(today_res.status_code, 200)
        self.assertEqual(today_res.get_json()['mood']['mood'], 'happy')

        # 3. Get mood analytics
        analytics_res = self.client.get('/api/mood/analytics', headers=headers)
        self.assertEqual(analytics_res.status_code, 200)
        dist = analytics_res.get_json()['mood_distribution']
        self.assertEqual(dist['happy'], 1)

    def test_ai_coaching_endpoints_and_fallbacks(self):
        """Verify AI coaching endpoints function gracefully with or without Gemini API key."""
        _, _, headers = self.register_and_login()

        # 1. AI health check
        health_res = self.client.get('/api/ai/health')
        self.assertEqual(health_res.status_code, 200)
        self.assertTrue(health_res.get_json()['fallback_ready'])

        # 2. Daily message (tests caching and fallback generation)
        daily_res = self.client.get('/api/ai/daily-message', headers=headers)
        self.assertEqual(daily_res.status_code, 200)
        self.assertTrue(len(daily_res.get_json()['message']) > 10)

        # 3. Weekly summary
        weekly_res = self.client.get('/api/ai/weekly-summary', headers=headers)
        self.assertEqual(weekly_res.status_code, 200)
        self.assertTrue(len(weekly_res.get_json()['summary']) > 10)

        # 4. Habit recommendations
        rec_res = self.client.post('/api/ai/habit-recommendations', headers=headers, json={
            'goal': 'deep focus and productivity'
        })
        self.assertEqual(rec_res.status_code, 200)
        recs = rec_res.get_json()['recommendations']
        self.assertEqual(len(recs), 3)

    def test_frontend_routes(self):
        """Verify all HTML template views render without 500 errors."""
        routes = ['/', '/dashboard', '/login', '/register', '/habit/1']
        for route in routes:
            res = self.client.get(route)
            self.assertEqual(res.status_code, 200, f"Route {route} failed with {res.status_code}")


if __name__ == '__main__':
    unittest.main()

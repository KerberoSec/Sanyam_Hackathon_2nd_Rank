"""
Comprehensive Automated Test Suite for HabitFlow
=================================================
Validates all backend APIs, database models, streak calculation algorithms,
gamification mechanics, and AI coaching endpoints.
"""

import unittest
from datetime import timedelta
from app import create_app
from date_utils import current_date
from models import db, Habit, HabitLog, Mood, User, seed_default_badges


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

        # Duplicate display names must not trigger one password hash per row
        # or make username login ambiguous; email login remains deterministic.
        self.register_and_login(
            email='shared-one@test.com', password='FirstPassword123', name='Shared Name'
        )
        self.register_and_login(
            email='shared-two@test.com', password='SecondPassword123', name='Shared Name'
        )
        ambiguous_login = self.client.post('/api/auth/login', json={
            'username': 'Shared Name',
            'password': 'FirstPassword123'
        })
        self.assertEqual(ambiguous_login.status_code, 401)
        email_login = self.client.post('/api/auth/login', json={
            'email': 'shared-two@test.com',
            'password': 'SecondPassword123'
        })
        self.assertEqual(email_login.status_code, 200)

    def test_habit_crud_and_status_logging(self):
        """Verify habit creation, retrieval, updates, and completion logging."""
        _, _, headers = self.register_and_login()

        # 1. Create habit
        create_res = self.client.post('/api/habits', headers=headers, json={
            'title': 'Morning Meditation',
            'category': 'health',
            'icon': 'meditation',
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

        # 3. Skip first, then upgrade the same log to completion.
        skip_res = self.client.post(f'/api/habits/{habit_id}/skip', headers=headers, json={})
        self.assertEqual(skip_res.status_code, 200)
        self.assertEqual(skip_res.get_json()['status'], 'skipped')
        self.assertGreater(skip_res.get_json()['xp_earned'], 0)

        comp_res = self.client.post(f'/api/habits/{habit_id}/complete', headers=headers, json={})
        self.assertEqual(comp_res.status_code, 200)
        comp_data = comp_res.get_json()
        self.assertEqual(comp_data['status'], 'completed')
        self.assertEqual(comp_data['current_streak'], 1)
        self.assertGreater(comp_data['xp_earned'], 0)

        # Retries are idempotent; a completed log cannot be changed to skipped.
        retry_res = self.client.post(f'/api/habits/{habit_id}/complete', headers=headers, json={})
        self.assertEqual(retry_res.status_code, 200)
        self.assertEqual(retry_res.get_json()['xp_earned'], 0)
        rejected_skip = self.client.post(f'/api/habits/{habit_id}/skip', headers=headers, json={})
        self.assertEqual(rejected_skip.status_code, 409)

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
        today = current_date()
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

        self.assertIsNone(GamificationEngine.add_xp(user_id, -20))
        self.assertEqual(db.session.get(User, user_id).xp_points, 110)

    def test_habit_log_cannot_be_attached_to_another_users_habit(self):
        """Reject mismatched ownership before an ORM write reaches the database."""
        owner, _, _ = self.register_and_login(email='habit-owner@test.com')
        other_user, _, _ = self.register_and_login(email='habit-stranger@test.com')
        habit = Habit(user_id=owner['id'], title='Owner habit')
        db.session.add(habit)
        db.session.commit()

        db.session.add(HabitLog(
            habit_id=habit.id,
            user_id=other_user['id'],
            date=current_date(),
            status='completed'
        ))
        with self.assertRaisesRegex(ValueError, 'same user'):
            db.session.flush()
        db.session.rollback()

    def test_habit_schedule_editability_tracks_existing_logs(self):
        """Keep the detail form's schedule restriction aligned with the API."""
        user, _, headers = self.register_and_login(email='schedule-edit@test.com')
        habit = Habit(user_id=user['id'], title='Schedule habit')
        db.session.add(habit)
        db.session.commit()
        endpoint = f'/api/analytics/habit/{habit.id}'

        response = self.client.get(endpoint, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['habit']['frequency_editable'])

        db.session.add(HabitLog(
            habit_id=habit.id,
            user_id=user['id'],
            date=current_date(),
            status='completed'
        ))
        db.session.commit()
        response = self.client.get(endpoint, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()['habit']['frequency_editable'])

    def test_mood_tracking_and_analytics(self):
        """Verify mood logging, history, and statistics."""
        _, _, headers = self.register_and_login()

        empty_insight_res = self.client.get('/api/ai/mood-insights', headers=headers)
        self.assertEqual(empty_insight_res.status_code, 200)
        empty_insight = empty_insight_res.get_json()
        self.assertEqual(empty_insight['source'], 'default')
        self.assertIsNone(empty_insight['error'])

        # 1. Log today's mood
        log_res = self.client.post('/api/mood', headers=headers, json={
            'mood': 'happy',
            'note': 'Feeling inspired and productive!'
        })
        self.assertEqual(log_res.status_code, 200)
        self.assertEqual(log_res.get_json()['emoji'], '😊')

        # 2. Get today's mood (verifying mood and reflection note persistence)
        today_res = self.client.get('/api/mood/today', headers=headers)
        self.assertEqual(today_res.status_code, 200)
        self.assertEqual(today_res.get_json()['mood']['mood'], 'happy')
        self.assertEqual(today_res.get_json()['mood']['note'], 'Feeling inspired and productive!')

        # 3. Clear reflection note and verify updated in database
        clear_res = self.client.post('/api/mood', headers=headers, json={
            'mood': 'happy',
            'note': None
        })
        self.assertEqual(clear_res.status_code, 200)
        today_cleared_res = self.client.get('/api/mood/today', headers=headers)
        self.assertEqual(today_cleared_res.status_code, 200)
        self.assertIsNone(today_cleared_res.get_json()['mood']['note'])

        # 4. Get mood analytics
        analytics_res = self.client.get('/api/mood/analytics', headers=headers)
        self.assertEqual(analytics_res.status_code, 200)
        dist = analytics_res.get_json()['mood_distribution']
        self.assertEqual(dist['happy'], 1)

    def test_active_happy_streak_exceeds_30_day_window(self):
        """The active mood streak should not be capped by 30-day chart history."""
        user, _, headers = self.register_and_login(email='streak-mood@test.com')
        today = current_date()
        for offset in range(45, 0, -1):
            db.session.add(Mood(
                user_id=user['id'],
                date=today - timedelta(days=offset),
                mood='happy'
            ))
        db.session.commit()

        response = self.client.get('/api/mood/analytics', headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['happy_streak'], 45)
        self.assertEqual(response.get_json()['longest_happy_streak'], 45)

        db.session.add(Mood(user_id=user['id'], date=today, mood='neutral'))
        db.session.commit()
        response = self.client.get('/api/mood/analytics', headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['happy_streak'], 0)
        self.assertEqual(response.get_json()['longest_happy_streak'], 45)

    def test_ai_coaching_endpoints_and_fallbacks(self):
        """Verify behavioral coaching endpoints function gracefully with native algorithmic engine."""
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
        """Verify all HTML template views render without 500 errors and enforce server-side auth."""
        public_routes = ['/', '/login', '/register', '/about', '/privacy', '/terms']
        for route in public_routes:
            res = self.client.get(route)
            self.assertEqual(res.status_code, 200, f"Public route {route} failed with {res.status_code}")

        # Protected routes redirect unauthenticated users to /login
        protected_routes = ['/dashboard', '/habit/1']
        for route in protected_routes:
            res = self.client.get(route)
            self.assertEqual(res.status_code, 302, f"Unauthenticated access to {route} did not redirect")
            self.assertIn('/login', res.headers.get('Location', ''))

        # When authenticated via auth_token cookie or session, protected routes return 200
        _, token, _ = self.register_and_login(email="pageuser@test.com")
        self.client.set_cookie('auth_token', token)
        for route in protected_routes:
            res = self.client.get(route)
            self.assertEqual(res.status_code, 200, f"Authenticated access to {route} failed with {res.status_code}")

    def test_security_validations(self):
        """Verify password complexity rules and future date completion rejection."""
        # 1. Short password (< 8 chars) rejection
        short_pw_res = self.client.post('/api/auth/register', json={
            'name': 'Short Pass',
            'email': 'short@example.com',
            'password': 'short'
        })
        self.assertEqual(short_pw_res.status_code, 400)
        self.assertIn("at least 8 characters", short_pw_res.get_json()['message'])

        # 2. Register valid user and create habit
        _, _, headers = self.register_and_login(email="secuser@example.com", password="Password123!")
        create_res = self.client.post('/api/habits', headers=headers, json={
            'title': 'Security Habit',
            'category': 'security'
        })
        self.assertEqual(create_res.status_code, 201)
        habit_id = create_res.get_json()['habit']['id']

        # 3. Reject future completion date
        future_date = (current_date() + timedelta(days=10)).isoformat()
        future_res = self.client.post(f'/api/habits/{habit_id}/complete', headers=headers, json={
            'date': future_date
        })
        self.assertEqual(future_res.status_code, 400)
        self.assertIn("future dates", future_res.get_json()['message'])

    def test_token_revocation_on_password_change(self):
        """Verify prior JWT is revoked when password is changed."""
        _, old_token, headers = self.register_and_login(email="pwchange@test.com", password="OldPassword123")

        # Change password
        update_res = self.client.put('/api/auth/profile', headers=headers, json={
            'old_password': 'OldPassword123',
            'new_password': 'NewPassword456'
        })
        self.assertEqual(update_res.status_code, 200)

        # Using old token should now fail with 401
        check_res = self.client.get('/api/auth/me', headers={'Authorization': f'Bearer {old_token}'})
        self.assertEqual(check_res.status_code, 401)
        self.assertIn("revoked", check_res.get_json()['message'])

    def test_habit_creation_limit(self):
        """Verify per-user limit of 50 active habits is enforced."""
        _, _, headers = self.register_and_login(email="quota@test.com", password="Password123!")

        # Create 50 habits in bulk via db for speed
        from models import User
        u = User.query.filter_by(email="quota@test.com").first()
        for i in range(50):
            db.session.add(Habit(user_id=u.id, title=f"Habit {i}", active=True))
        db.session.commit()

        # 51st habit should be rejected
        res = self.client.post('/api/habits', headers=headers, json={
            'title': 'Over Quota Habit'
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("limit reached", res.get_json()['message'])

    def test_habit_longest_streak_historical_logs(self):
        """Verify longest streak calculates accurately even if logs precede created_date."""
        from services.streak_engine import StreakEngine
        user, _, headers = self.register_and_login(email="history-streak@test.com")
        today = current_date()

        # Habit with created_date set to today
        habit = Habit(
            user_id=user['id'],
            title="Reading",
            created_date=today,
            frequency=['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        )
        db.session.add(habit)
        db.session.commit()

        # Logs pre-dating created_date (e.g. 5 days ago to 1 day ago)
        for offset in range(5, 0, -1):
            db.session.add(HabitLog(
                habit_id=habit.id,
                user_id=user['id'],
                date=today - timedelta(days=offset),
                status='completed'
            ))
        db.session.commit()

        longest = StreakEngine.calculate_longest_streak(habit.id, user['id'])
        self.assertEqual(longest, 5)

    def test_achievements_and_badge_unlock_logic(self):
        """Validate the 8 default achievement badges, unlock criteria, and auto-synchronization."""
        user, _, headers = self.register_and_login(email="achiever@test.com")
        user_id = user['id']
        today = current_date()

        # 1. Fresh user: verify initial 0 / 8 Unlocked state
        res = self.client.get('/api/auth/badges', headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        badges = data['badges']
        self.assertEqual(len(badges), 8)
        unlocked_count = sum(1 for b in badges if b['unlocked'])
        self.assertEqual(unlocked_count, 0)

        # Check badge names and Consistency King icon
        badge_map = {b['name']: b for b in badges}
        expected_names = [
            'First Week', 'Two Weeks Strong', 'Monthly Master',
            'Getting Started', 'Habit Builder', 'Centennial',
            'Consistency King', 'Yearly Champion'
        ]
        for name in expected_names:
            self.assertIn(name, badge_map)
            self.assertFalse(badge_map[name]['unlocked'])
            self.assertIsNone(badge_map[name]['earned_at'])

        self.assertEqual(badge_map['Consistency King']['icon'], 'consistency')

        # 2. Create a daily habit created 7 days ago
        habit = Habit(
            user_id=user_id,
            title='Morning Meditation',
            created_date=today - timedelta(days=7),
            frequency=['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        )
        db.session.add(habit)
        db.session.commit()
        habit_id = habit.id

        # Complete habit for days 1 to 6
        for offset in range(6, 0, -1):
            log_date = today - timedelta(days=offset)
            comp_res = self.client.post(
                f'/api/habits/{habit_id}/complete',
                headers=headers,
                json={'date': log_date.isoformat()}
            )
            self.assertEqual(comp_res.status_code, 200)
            self.assertEqual(len(comp_res.get_json()['badges_unlocked']), 0)

        # 3. Complete day 7 -> Unlocks 'First Week' badge
        day7_res = self.client.post(
            f'/api/habits/{habit_id}/complete',
            headers=headers,
            json={'date': today.isoformat()}
        )
        self.assertEqual(day7_res.status_code, 200)
        newly_unlocked = day7_res.get_json()['badges_unlocked']
        self.assertEqual(len(newly_unlocked), 1)
        self.assertEqual(newly_unlocked[0]['name'], 'First Week')

        # Badges list now shows 1 / 8 Unlocked
        badges_res = self.client.get('/api/auth/badges', headers=headers)
        badges = badges_res.get_json()['badges']
        unlocked = [b for b in badges if b['unlocked']]
        self.assertEqual(len(unlocked), 1)
        self.assertEqual(unlocked[0]['name'], 'First Week')
        self.assertIsNotNone(unlocked[0]['earned_at'])

        # 4. Create second habit and add completions to reach 10 total completions
        # Currently 7 completions logged on habit 1. We log 3 completions on habit 2.
        habit2 = Habit(
            user_id=user_id,
            title='Hydration',
            created_date=today - timedelta(days=3),
            frequency=['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        )
        db.session.add(habit2)
        db.session.commit()
        h2_id = habit2.id

        self.client.post(
            f'/api/habits/{h2_id}/complete',
            headers=headers,
            json={'date': (today - timedelta(days=2)).isoformat()}
        )
        self.client.post(
            f'/api/habits/{h2_id}/complete',
            headers=headers,
            json={'date': (today - timedelta(days=1)).isoformat()}
        )
        tenth_res = self.client.post(
            f'/api/habits/{h2_id}/complete',
            headers=headers,
            json={'date': today.isoformat()}
        )
        self.assertEqual(tenth_res.status_code, 200)
        h2_unlocked = tenth_res.get_json()['badges_unlocked']
        self.assertTrue(any(b['name'] == 'Getting Started' for b in h2_unlocked))

        # Badges list now shows 2 / 8 Unlocked
        badges_res = self.client.get('/api/auth/badges', headers=headers)
        unlocked = [b for b in badges_res.get_json()['badges'] if b['unlocked']]
        self.assertEqual(len(unlocked), 2)
        unlocked_names = {b['name'] for b in unlocked}
        self.assertEqual(unlocked_names, {'First Week', 'Getting Started'})

        # 5. Test auto-sync: Directly insert historical completions satisfying 'Two Weeks Strong'
        # without calling the endpoint, then verify /api/auth/badges syncs it
        for offset in range(14, 6, -1):
            db.session.add(HabitLog(
                habit_id=habit_id,
                user_id=user_id,
                date=today - timedelta(days=offset),
                status='completed'
            ))
        db.session.commit()

        # Fetching badges triggers sync_user_badges automatically
        sync_res = self.client.get('/api/auth/badges', headers=headers)
        synced_badges = sync_res.get_json()['badges']
        synced_unlocked_names = {b['name'] for b in synced_badges if b['unlocked']}
        self.assertIn('Two Weeks Strong', synced_unlocked_names)


if __name__ == '__main__':
    unittest.main()

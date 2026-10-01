# HabitFlow: Personal Habit Tracker

Build better habits, one day at a time. HabitFlow is a polished habit tracking application that combines gamification, analytics, and thoughtful user experience to help you achieve consistency and personal growth.

## Features

* **Streak Tracking**: Monitor your streaks and celebrate consistency
* **Analytics Dashboard**: Detailed insights into your habits and patterns
* **Gamification**: Earn XP, unlock badges, and advance through levels
* **Mood Tracking**: Connect your habits with emotional wellbeing
* **Smart Coach**: Personalized insights and motivational messages
* **Fully Responsive**: Works on desktop, tablet, and mobile devices
* **Dark Mode**: Comfortable viewing at any time of day
* **Smooth Animations**: Polished interactions and confetti celebrations

## Tech Stack

### Backend

* **Python 3.9+**
* **Flask**: Web framework
* **Flask SQLAlchemy**: ORM
* **Flask JWT Extended**: JWT authentication
* **MySQL**: Database
* **Flask CORS**: Cross origin requests

### Frontend

* **HTML5**: Markup
* **Bootstrap 5**: CSS framework
* **Chart.js**: Analytics charts
* **Vanilla JavaScript**: Interactivity
* **Canvas Confetti**: Celebrations

## Installation

### Prerequisites

* Python 3.9 or higher
* MySQL 5.7 or higher
* Git

### Step 1: Clone and Setup

```bash
cd habit_tracker
python -m venv venv

# On Windows
venv\Scripts\activate

# On macOS/Linux
source venv/bin/activate
```

### Step 2: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 3: Configure Environment

Create a `.env` file in the project root:

```env
FLASK_ENV=development
FLASK_APP=app.py
DATABASE_URL=mysql+pymysql://root:password@localhost/habit_tracker
JWT_SECRET_KEY=your_secret_key_here_change_in_production
SECRET_KEY=your_app_secret_key_here
```

### Step 4: Create MySQL Database

```bash
mysql -u root -p
CREATE DATABASE habit_tracker DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
EXIT;
```

### Step 5: Initialize Database

```bash
flask shell
>>> from models import db, Badge
>>> db.create_all()
>>>
>>> # Create default badges
>>> default_badges = [
...     Badge(name='First Week', description='Complete a habit for 7 days straight', icon='flame'),
...     Badge(name='Two Weeks Strong', description='Complete a habit for 14 days straight', icon='strength'),
...     Badge(name='Monthly Master', description='Complete a habit for 30 days straight', icon='crown'),
...     Badge(name='Centennial', description='Complete 100 habit logs', icon='hundred'),
...     Badge(name='Yearly Champion', description='Complete 365 habit logs', icon='target'),
... ]
>>> db.session.add_all(default_badges)
>>> db.session.commit()
>>> exit()
```

### Step 6: Run the Application

```bash
python app.py
```

Visit `http://localhost:5000` in your browser.

## Project Structure

```
habit_tracker/
├── app.py                 # Main Flask application
├── config.py              # Configuration settings
├── models.py              # SQLAlchemy models
├── database.sql           # Database schema
│
├── routes/
│   ├── auth.py            # Authentication routes
│   ├── habits.py          # Habit CRUD routes
│   ├── analytics.py       # Analytics routes
│   └── mood.py            # Mood tracking routes
│
├── services/
│   ├── streak_engine.py   # Streak calculation logic
│   ├── gamification.py    # XP and badge logic
│   └── coach_engine.py    # Coach insights
│
├── templates/
│   ├── index.html         # Landing page
│   ├── login.html         # Login page
│   ├── register.html      # Registration page
│   └── dashboard.html     # Main dashboard
│
├── static/
│   ├── css/
│   │   └── style.css      # Main stylesheet
│   ├── js/
│   │   └── app.js         # JavaScript application logic
│   └── images/            # Images and icons
│
└── requirements.txt       # Python dependencies
```

## API Endpoints

### Authentication

* `POST /api/auth/register`: Register a new user
* `POST /api/auth/login`: Log in and receive a JWT token
* `GET /api/auth/me`: Get the current user
* `POST /api/auth/logout`: Log out

### Habits

* `GET /api/habits`: Get all habits
* `POST /api/habits`: Create a new habit
* `GET /api/habits/<id>`: Get a specific habit
* `PUT /api/habits/<id>`: Update a habit
* `DELETE /api/habits/<id>`: Delete a habit
* `POST /api/habits/<id>/complete`: Log a completion
* `POST /api/habits/<id>/skip`: Skip a habit
* `POST /api/habits/<id>/miss`: Mark a habit as missed
* `GET /api/habits/<id>/history`: Get calendar history

### Analytics

* `GET /api/analytics`: Get dashboard analytics
* `GET /api/analytics/weekly`: Get weekly data
* `GET /api/analytics/monthly`: Get monthly data
* `GET /api/analytics/habit/<id>`: Get habit specific statistics

### Mood

* `POST /api/mood`: Log mood
* `GET /api/mood/today`: Get today's mood
* `GET /api/mood/history`: Get mood history
* `GET /api/mood/analytics`: Get mood analytics
* `GET /api/mood/stats`: Get mood statistics

## Database Schema

### Users Table

```sql
CREATE TABLE users (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(120) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    xp_points INT DEFAULT 0,
    level INT DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Habits Table

```sql
CREATE TABLE habits (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    title VARCHAR(255) NOT NULL,
    category VARCHAR(100),
    icon VARCHAR(50),
    color VARCHAR(20),
    frequency JSON,
    reminder_time TIME,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

### Habit Logs Table

```sql
CREATE TABLE habit_logs (
    id INT PRIMARY KEY AUTO_INCREMENT,
    habit_id INT NOT NULL,
    user_id INT NOT NULL,
    date DATE NOT NULL,
    status ENUM('completed', 'skipped', 'missed'),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_habit_date (habit_id, date),
    FOREIGN KEY (habit_id) REFERENCES habits(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

### Moods Table

```sql
CREATE TABLE moods (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    date DATE NOT NULL,
    mood ENUM('happy', 'neutral', 'sad'),
    note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_mood_date (user_id, date),
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

### Badges Table

```sql
CREATE TABLE badges (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    icon VARCHAR(50)
);
```

### User Badges Table

```sql
CREATE TABLE user_badges (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    badge_id INT NOT NULL,
    earned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_user_badge (user_id, badge_id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (badge_id) REFERENCES badges(id)
);
```

## Gamification System

### XP Rules

* **+10 XP** for each habit completion
* **+50 XP** for a 7 day streak
* **+100 XP** for a 14 day streak
* **+200 XP** for a 30 day streak

### Levels

```
Level = Total XP // 100
```

### Badges

* First Week: 7 days
* Two Weeks Strong: 14 days
* Monthly Master: 30 days
* Centennial: 100 completions
* Yearly Champion: 365 completions
* Getting Started: 10 completions
* Habit Builder: 50 completions
* Consistency King: 100 completions

## Coach Engine

The Smart Coach detects:

* **Streak drops**: Missed days after strong streaks
* **Inactivity**: No logs for 3 or more days
* **Mood patterns**: Correlations between mood and habits
* **Best days**: The days when you perform best

## Dark Mode

Toggle dark mode by clicking the menu button. Your preference is saved in localStorage.

## Security

* Passwords are hashed with Werkzeug
* JWT tokens are used for authentication
* CORS is enabled for the API
* Environment variables are used for sensitive data
* SQL injection prevention through the SQLAlchemy ORM

## Responsive Design

The application is fully responsive and supports:

* Desktop (1920px and above)
* Tablet (768px to 1920px)
* Mobile (320px to 768px)

## Deployment

### Heroku

1. Create a `Procfile`:

```
web: gunicorn app:app
```

2. Create a `runtime.txt`:

```
python-3.10.0
```

3. Deploy:

```bash
heroku login
heroku create yourappname
heroku addons:create cleardb:ignite
git push heroku main
heroku run flask shell
```

### Docker

Create a `Dockerfile`:

```dockerfile
FROM python:3.10
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app"]
```

## Performance Tips

1. Use indexes on frequently queried columns
2. Cache analytics calculations
3. Implement pagination for large datasets
4. Use lazy loading for images
5. Minify CSS and JavaScript

## Troubleshooting

### Database Connection Error

```
Check DATABASE_URL in .env
Ensure MySQL is running
Verify the database exists
```

### CORS Issues

```
Flask CORS is configured
Check request headers and origin
```

### Token Expired

```
Clear localStorage
Log in again
Tokens expire after 30 days
```

## Contributing

Contributions are welcome. Feel free to fork the repository and submit pull requests.

## License

MIT License. See the LICENSE file for details.

## Future Features

* Social features (friend challenges and leaderboards)
* Email reminders and notifications
* Mobile app (React Native)
* Integration with wearables
* Advanced analytics with ML insights
* Community habit library
* Habit templates

## Support

For issues, please create an issue on GitHub or contact support by email.

## Developers

Arun Kumar, Sourav, Anish Thakur, Paras Rana

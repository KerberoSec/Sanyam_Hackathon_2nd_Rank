#!/bin/bash
# ==============================================================================
# HabitFlow Quick Setup Script
# Automatically initializes virtual environment, installs dependencies,
# and configures the environment file.
# ==============================================================================

set -e

echo "🚀 HabitFlow - Habit Tracker Setup"
echo "=================================="
echo ""

# 1. Create virtual environment if not present
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment in ./venv..."
    python3 -m venv venv
else
    echo "📦 Virtual environment already exists in ./venv."
fi

# 2. Activate virtual environment
echo "✅ Activating virtual environment..."
source venv/bin/activate || . venv/bin/activate

# 3. Install/upgrade dependencies
echo "📥 Installing dependencies from requirements.txt..."
pip install --upgrade pip
pip install -r requirements.txt

# 4. Create .env file from .env.example if missing
if [ ! -f ".env" ]; then
    echo "⚙️  Creating default .env configuration file..."
    cp .env.example .env
else
    echo "⚙️  Existing .env detected, leaving intact."
fi

echo ""
echo "🎉 Setup complete!"
echo ""
echo "Ready to run:"
echo "1. Activate environment: source venv/bin/activate"
echo "2. Run test suite:       python3 test_suite.py"
echo "3. Start web server:     python3 app.py"
echo "4. Open in browser:      http://localhost:5000"
echo ""
echo "Happy habit tracking! 🔥"

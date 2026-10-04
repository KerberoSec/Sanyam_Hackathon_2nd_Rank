# Use official Python runtime as base image
FROM python:3.11-slim

# Set working directory in container
WORKDIR /app

# Set environment variables
ENV FLASK_APP=app.py
ENV FLASK_ENV=development
ENV PYTHONUNBUFFERED=1
ENV DATABASE_URL=sqlite:////app/instance/habit_tracker.db

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Create unprivileged application user
RUN useradd -m -u 1001 -s /bin/bash habitflow

# Copy entire application and set ownership
COPY . .
RUN mkdir -p /app/instance && \
    chown -R habitflow:habitflow /app && \
    chmod 770 /app/instance

# Expose port
EXPOSE 5000

# Run container as unprivileged user
USER habitflow

# Health check
HEALTHCHECK --interval=20s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:5000/api/health || exit 1

# Run the application with production WSGI server
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "--access-logfile", "-", "app:create_app()"]

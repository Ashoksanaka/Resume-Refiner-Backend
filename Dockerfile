# Backend Dockerfile for Resume AI Platform
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Create a non-root user
RUN addgroup --system django && adduser --system --ingroup django django

# Install system dependencies (gosu drops privileges after fixing volume ownership)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY --chown=django:django . .

# Start scripts (Gunicorn uses $PORT, default 8000)
RUN chmod +x \
    /app/scripts/docker-entrypoint.sh \
    /app/scripts/start-web.sh \
    /app/scripts/start-dev.sh \
    /app/scripts/start-migrate.sh

# Create directories for generated content and set permissions
RUN mkdir -p /app/generated/pdfs /app/templates/resumes /app/staticfiles /app/media && \
    chown -R django:django /app

# Default process identity is non-root. Compose may override with user: "0:0"
# so the entrypoint can chown named volumes, then gosu → django.
USER django

ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]

# Expose Gunicorn port (Nginx publishes 80 in docker-compose.prod.yml)
EXPOSE 8000

# Default: web server (Compose / workers override the command)
CMD ["/app/scripts/start-web.sh"]

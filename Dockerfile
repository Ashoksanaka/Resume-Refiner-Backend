# Backend Dockerfile for Resume AI Platform
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Create a non-root user
RUN addgroup --system django && adduser --system --ingroup django django

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY --chown=django:django . .

# Web start scripts (uses $PORT for Render/Railway)
RUN chmod +x /app/scripts/start-web.sh /app/scripts/start-render-free.sh

# Create directories for generated content and set permissions
RUN mkdir -p /app/generated/pdfs /app/templates/resumes && \
    chown -R django:django /app

# Switch to non-root user
USER django

# Expose port (Render sets PORT at runtime; 8000 is local default)
EXPOSE 8000

# Default: web server (workers override start command on Render)
CMD ["/app/scripts/start-web.sh"]
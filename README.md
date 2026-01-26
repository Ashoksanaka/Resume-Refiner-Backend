# Resume Refiner Backend

Django REST API backend for the Resume Refiner platform. Provides authentication, user profile management, and resume generation services.

## Architecture

- **Framework**: Django 4.2+ with Django REST Framework
- **Database**: PostgreSQL 15+
- **Task Queue**: Celery with Redis broker
- **API**: RESTful API with OpenAPI/Swagger documentation
- **Authentication**: Session-based authentication with email verification
- **Microservices**: AI Agent and LaTeX services for resume generation

## Prerequisites

- Python 3.11+
- PostgreSQL 15+
- Redis 7+
- Docker and Docker Compose (recommended)

## Quick Start

### Using Docker Compose (Recommended)

1. **Create environment file**:
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

2. **Start services**:
   ```bash
   docker-compose up -d
   ```

3. **Run migrations**:
   ```bash
   docker-compose exec backend python manage.py migrate
   ```

4. **Create superuser** (optional):
   ```bash
   docker-compose exec backend python manage.py createsuperuser
   ```

The API will be available at `http://localhost:8000`

### Local Development Setup

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up environment variables** (see Environment Variables section)

3. **Run migrations**:
   ```bash
   python manage.py migrate
   ```

4. **Start development server**:
   ```bash
   python manage.py runserver
   ```

5. **Start Celery worker** (in separate terminal):
   ```bash
   celery -A config worker -l info
   ```

6. **Start Celery beat** (in separate terminal):
   ```bash
   celery -A config beat -l info
   ```

## Environment Variables

Create a `.env` file in the backend directory with the following variables:

### Required

```bash
# Django
SECRET_KEY=your-secret-key-here
DEBUG=False  # Set to True for development
ALLOWED_HOSTS=localhost,127.0.0.1,your-domain.com

# Database
POSTGRES_DB=resumeai
POSTGRES_USER=resumeai
POSTGRES_PASSWORD=your-db-password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

# Redis
REDIS_URL=redis://localhost:6379/0
```

### Optional

```bash
# Email (SendGrid)
SENDGRID_API_KEY=your-sendgrid-api-key
DEFAULT_FROM_EMAIL=noreply@yourdomain.com
EMAIL_FROM_NAME=Resume Refiner
FRONTEND_URL=http://localhost:3000

# Microservices
AI_AGENT_URL=http://localhost:8001
LATEX_SERVICE_URL=http://localhost:8002
GEMINI_API_KEY=your-gemini-api-key

# Authentication
AUTH_DETAILED_ERRORS=False  # Set to True for development only
```

## Project Structure

```
backend/
├── app/                    # Django applications
│   ├── authentication/     # User authentication & authorization
│   ├── common/             # Shared utilities & models
│   ├── profiles/           # User profile management
│   └── resumes/            # Resume generation & management
├── config/                 # Django project settings
├── services/               # Microservices
│   ├── agent/              # AI agent service
│   └── latex/              # LaTeX PDF generation service
├── tests/                  # Integration tests
├── docs/                   # Documentation
├── migrations/             # Database migrations (auto-generated)
├── openapi/                # OpenAPI specification
├── schemas/                # JSON schemas
├── Dockerfile              # Production Docker image
├── docker-compose.yml      # Local development setup
└── requirements.txt        # Python dependencies
```

## API Documentation

- **OpenAPI Spec**: `/openapi/v1/openapi.yaml`
- **Swagger UI**: Available when `DEBUG=True` at `/api/v1/docs/` (if configured)
- **Admin Panel**: `/admin/` (requires superuser account)

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test file
pytest app/authentication/tests.py

# Run with verbose output
pytest -v
```

## Database Migrations

```bash
# Create migrations
python manage.py makemigrations

# Apply migrations
python manage.py migrate

# Show migration status
python manage.py showmigrations
```

## Production Deployment

1. **Set `DEBUG=False`** in environment variables
2. **Set strong `SECRET_KEY`** (generate with `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`)
3. **Configure `ALLOWED_HOSTS`** with your domain
4. **Set up proper database** (use managed PostgreSQL service in production)
5. **Configure email service** (SendGrid or SMTP)
6. **Set up static files** (use `python manage.py collectstatic` with a static file server)
7. **Use production WSGI server** (Gunicorn is included in Dockerfile)
8. **Configure HTTPS** and set `SESSION_COOKIE_SECURE=True`

## Security Features

- Password validation (min 10 chars, uppercase, number, symbol)
- Session cookie security (HttpOnly, Secure, SameSite)
- PII filtering in logs
- Email verification required for account activation
- CORS protection
- CSRF protection

## Management Commands

```bash
# Verify user email
python manage.py verify_user <email>

# Cleanup expired tokens
python manage.py cleanup_expired

# Sync resume templates
python manage.py sync_templates
```

## Troubleshooting

### Database Connection Issues
- Ensure PostgreSQL is running and accessible
- Verify database credentials in `.env`
- Check `POSTGRES_HOST` matches your database location

### Celery Tasks Not Running
- Ensure Redis is running
- Check Celery worker logs: `docker-compose logs celery_worker`
- Verify `REDIS_URL` in environment variables

### Email Not Sending
- Check SendGrid API key is set correctly
- Verify `DEFAULT_FROM_EMAIL` matches verified sender in SendGrid
- Check email backend configuration

## License

Proprietary - All rights reserved

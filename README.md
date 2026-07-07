# Resume Refiner Backend

Django REST API backend for the Resume Refiner platform. Provides authentication, user profile management, and resume generation services.

## Architecture

- **Framework**: Django 4.2+ with Django REST Framework
- **Database**: Supabase Postgres (managed PostgreSQL)
- **Task Queue**: Celery with Redis Cloud broker
- **API**: RESTful API with OpenAPI/Swagger documentation
- **Authentication**: Clerk JWT verification with local user sync via webhooks
- **AI**: In-process NVIDIA NIM resume customization (`app/ai/nim_service.py`)
- **PDF**: FormaTeX cloud compilation

### Hybrid deployment (recommended)

| Component | Host |
|-----------|------|
| Next.js frontend | Vercel |
| Django API + Celery worker + Celery beat | Render (or Railway) |
| PostgreSQL | Supabase |
| Redis (Celery broker) | Redis Cloud |
| NVIDIA NIM | Direct API calls from Celery worker |

```mermaid
flowchart LR
  vercel[Vercel frontend] -->|"/api/v1 rewrite"| render[Render Django API]
  render --> supabase[(Supabase Postgres)]
  worker[Celery worker] --> supabase
  worker --> redis[(Redis Cloud)]
  worker --> nvidia[NVIDIA NIM API]
  worker --> formatex[FormaTeX API]
  clerk[Clerk] -->|webhooks| render
```

## Prerequisites

- Python 3.11+
- Supabase project (Postgres credentials)
- Redis Cloud database (`rediss://` URL)
- Docker and Docker Compose (optional, for local dev)
- NVIDIA NIM API key and FormaTeX API key

## Quick Start

### Using Docker Compose (local dev)

Docker Compose runs only the Django app and Celery processes. Postgres and Redis are **external** (Supabase + Redis Cloud).

1. **Create environment file**:
   ```bash
   cp .env.example .env
   # Set Supabase, Redis Cloud, NVIDIA, FormaTeX, and Clerk credentials
   ```

2. **Start services**:
   ```bash
   docker compose up -d
   ```

3. **Run migrations** (if not auto-run on backend start):
   ```bash
   docker compose exec backend python manage.py migrate
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
   celery -A config worker -l info -Q celery,resume_generation,maintenance
   ```

6. **Start Celery beat** (in separate terminal):
   ```bash
   celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
   ```

## Environment Variables

Create a `.env` file in the backend directory. See `.env.example` for the full list.

### Required

```bash
# Django
SECRET_KEY=your-secret-key-here
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1,.onrender.com,resume-refiner-api.onrender.com
CORS_ALLOWED_ORIGINS=http://localhost:3000,https://your-app.vercel.app
CSRF_TRUSTED_ORIGINS=http://localhost:3000,https://your-app.vercel.app

# Supabase Postgres (Session mode, port 5432)
POSTGRES_HOST=db.xxxxx.supabase.co
POSTGRES_PORT=5432
POSTGRES_DB=postgres
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_supabase_password
POSTGRES_SSLMODE=require

# Redis Cloud (TLS)
CELERY_BROKER_URL=rediss://default:password@redis-xxxxx.cloud.redislabs.com:6379

# NVIDIA NIM
NVIDIA_API_KEY=your-nvidia-nim-api-key
NVIDIA_MODEL=nvidia/nemotron-3-super-120b-a12b
NVIDIA_API_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_REQUEST_TIMEOUT=180

# FormaTeX (required for PDF generation)
FORMATEX_API_KEY=your-formatex-api-key
```

### Clerk

```bash
CLERK_SECRET_KEY=sk_test_...
CLERK_JWT_ISSUER=https://your-app.clerk.accounts.dev
CLERK_WEBHOOK_SECRET=whsec_...
```

## Render Deployment

Deploy the backend from this repo using [`render.yaml`](render.yaml) (free tier).

> **Free tier:** Render has no free background-worker service type. The blueprint deploys **one free web service** that runs Django API + Celery worker + Celery beat together via `scripts/start-render-free.sh`. Local `docker compose` still uses separate containers.

### 1. Create services (Blueprint)

1. Push this repo to GitHub.
2. In [Render Dashboard](https://dashboard.render.com/) → **New** → **Blueprint**.
3. Connect the `Resume-Refiner-Backend` repository and apply the blueprint.
4. Render creates `resume-refiner-api` (Web Service, free tier).

### 2. Set environment variables

In the **`resume-refiner-env`** environment group (or each service), set secrets marked `sync: false` in `render.yaml`:

| Variable | Source |
|----------|--------|
| `SECRET_KEY` | Django secret (generate a strong random string) |
| `POSTGRES_*` | Supabase Session mode (port `5432`) |
| `CELERY_BROKER_URL` | Redis Cloud `rediss://` URL |
| `NVIDIA_API_KEY` | NVIDIA NIM dashboard |
| `FORMATEX_API_KEY` | FormaTeX dashboard |
| `CLERK_SECRET_KEY` | Clerk dashboard |
| `CLERK_JWT_ISSUER` | Clerk dashboard |
| `CLERK_WEBHOOK_SECRET` | Clerk webhook signing secret |
| `CORS_ALLOWED_ORIGINS` | `https://your-app.vercel.app` (+ localhost for dev) |
| `CSRF_TRUSTED_ORIGINS` | Same as CORS |
| `FRONTEND_URL` | `https://your-app.vercel.app` |

Copy values from your local `.env` — do not commit `.env` to git.

**Important:** Set `NVIDIA_API_KEY` and `FORMATEX_API_KEY` on the **worker** service (resume jobs run there).

### 3. Migrations & health check

- Migrations run automatically via `preDeployCommand` on the web service.
- Health check: `GET /api/v1/health`
- Note your web URL: `https://resume-refiner-api.onrender.com` (name may vary).

### 4. Free tier (all-in-one)

| Component | How it runs on free Render |
|-----------|----------------------------|
| Django API | `resume-refiner-api` web service |
| Celery worker | Same container (`start-render-free.sh`) |
| Celery beat | Same container (`start-render-free.sh`) |

Limits: ~512MB RAM, idle spin-down, ephemeral PDF disk. For production scale, split into paid worker services.

### 5. Manual deploy (without Blueprint)

Create three Docker services and use these commands:

| Service | Start command |
|---------|---------------|
| **Web** | `gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --timeout 120` |
| **Worker** | `celery -A config worker -l info -Q celery,resume_generation,maintenance` |
| **Beat** | `celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler` |

Set **Pre-Deploy Command** on web: `python manage.py migrate --noinput`

**Note:** Generated PDFs are stored on the local filesystem (`generated/pdfs/`). Render's disk is ephemeral — users should download PDFs promptly. Supabase Storage is recommended for production persistence.

## Railway Deployment (alternative)

Same 3-service pattern as Render. See [`Procfile`](Procfile) and [`railway.toml`](railway.toml).

| Service | Start command |
|---------|---------------|
| **web** | `gunicorn config.wsgi:application --bind 0.0.0.0:$PORT` |
| **worker** | `celery -A config worker -l info -Q celery,resume_generation,maintenance` |
| **beat** | `celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler` |

## Vercel Frontend Configuration

In the Resume-Refiner-frontend Vercel project:

```bash
BACKEND_URL=https://resume-refiner-api.onrender.com
```

Update Clerk webhook endpoint to:

```
https://resume-refiner-api.onrender.com/api/v1/auth/clerk/webhook
```

Ensure Django `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, and `CSRF_TRUSTED_ORIGINS` include your Vercel domain and Render API domain.

## Project Structure

```
backend/
├── app/
│   ├── ai/                 # NVIDIA NIM resume customization (in-process)
│   ├── authentication/     # User authentication & authorization
│   ├── common/             # Shared utilities & models
│   ├── latex/templates/    # LaTeX resume templates
│   ├── profiles/           # User profile management
│   └── resumes/            # Resume generation & management
├── config/                 # Django project settings
├── render.yaml             # Render Blueprint (free web service)
├── Procfile                # Process types (Render / Railway)
├── railway.toml            # Railway deploy config (alternative)
├── scripts/start-render-free.sh  # API + Celery worker + beat (Render free)
├── scripts/start-web.sh          # Gunicorn only (local Docker web)
├── Dockerfile
├── docker-compose.yml      # Local dev (backend + celery only)
└── requirements.txt
```

## API Documentation

- **OpenAPI Spec**: `/openapi/v1/openapi.yaml`
- **Admin Panel**: `/admin/` (requires superuser account)

## Running Tests

```bash
pytest app/ai/ app/common/clients/tests/ app/resumes/tests.py -v
```

## Troubleshooting

### Database Connection Issues
- Use Supabase **Session mode** (port `5432`), not transaction pooler port `6543` (required for Celery Beat).
- Verify `POSTGRES_SSLMODE=require` for Supabase.

### Celery Tasks Not Running
- Ensure `CELERY_BROKER_URL` uses Redis Cloud `rediss://` URL.
- Check worker logs: `docker compose logs celery_worker`

### AI Generation Fails
- Verify `NVIDIA_API_KEY` is set on the **worker** service (generation runs in Celery).
- Check `NVIDIA_MODEL` matches an available NIM model.

## License

Proprietary - All rights reserved

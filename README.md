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
| Next.js frontend | Vercel (HTTPS) |
| Django API + Celery worker + Celery beat + Nginx | AWS VM (Docker Compose) |
| PostgreSQL | Supabase |
| Redis (Celery broker) | Redis Cloud |
| NVIDIA NIM | Direct API calls from Celery worker |

```mermaid
flowchart LR
  browser[Browser] -->|"HTTPS /api/v1"| vercel[Vercel frontend]
  vercel -->|"HTTP BACKEND_URL"| nginx[AWS Nginx]
  nginx --> web[Django Gunicorn]
  web --> supabase[(Supabase Postgres)]
  worker[Celery worker] --> supabase
  worker --> redis[(Redis Cloud)]
  worker --> nvidia[NVIDIA NIM API]
  worker --> formatex[FormaTeX API]
  clerk[Clerk] -->|"webhooks via Vercel proxy"| vercel
```

Browser traffic stays on HTTPS via the Vercel same-origin proxy. While the AWS VM serves HTTP only, set Vercel `ALLOW_INSECURE_BACKEND=true`. That Vercel → VM hop is unencrypted until TLS is added on the VM.

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

2. **Create the shared Docker network** (required once per machine):
   ```bash
   ./scripts/ensure-shared-network.sh
   ```

3. **Start services**:
   ```bash
   docker compose up -d
   ```

4. **Run migrations** (if not auto-run on backend start):
   ```bash
   docker compose exec backend python manage.py migrate
   ```

The API will be available at `http://localhost:8000`

### Local Development Setup

1. **Install dependencies**:
   ```bash
   # Runtime only
   pip install -r requirements.txt
   # Or runtime + tests
   pip install -r requirements-dev.txt
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
ALLOWED_HOSTS=backend,localhost,127.0.0.1
CORS_ALLOWED_ORIGINS=https://your-app.vercel.app
CSRF_TRUSTED_ORIGINS=https://your-app.vercel.app
FRONTEND_URL=https://your-app.vercel.app

# Supabase Postgres (Session mode, port 5432)
DIRECT_URL=postgresql://postgres.xxxxx:PASSWORD@aws-1-ap-south-1.pooler.supabase.com:5432/postgres
POSTGRES_SSLMODE=require

# Redis Cloud (TLS)
CELERY_BROKER_URL=rediss://default:password@redis-xxxxx.cloud.redislabs.com:6379

# NVIDIA NIM
NVIDIA_API_KEY=your-nvidia-nim-api-key
NVIDIA_MODEL=nvidia/nemotron-3-super-120b-a12b
NVIDIA_API_BASE_URL=   # required — NVIDIA OpenAI-compatible base URL
NVIDIA_REQUEST_TIMEOUT=180

# FormaTeX (required for PDF generation)
FORMATEX_API_KEY=your-formatex-api-key
FORMATEX_API_BASE_URL=   # required — FormaTeX API base URL

# Clerk Backend API base (required in production)
CLERK_API_BASE_URL=
```

### Clerk

```bash
CLERK_SECRET_KEY=sk_test_...
CLERK_JWT_ISSUER=https://your-app.clerk.accounts.dev
CLERK_WEBHOOK_SECRET=whsec_...
```

## AWS VM Deployment (Docker Compose)

Production stack: **Nginx + Gunicorn + Celery worker + Celery beat** via [`docker-compose.prod.yml`](docker-compose.prod.yml). Postgres (Supabase) and Redis (Redis Cloud) stay external.

### 1. VM prerequisites

1. Launch an EC2 (or equivalent) instance and attach an **Elastic IP**.
2. Security group:
   - **Inbound 8080/tcp** from `0.0.0.0/0` (Vercel / internet — Resume Refiner Nginx)
   - **Inbound 22/tcp** from your admin IP only
   - Do **not** expose Gunicorn `8000` publicly (it is container-internal only)
   - Port **80/443** may already be used by another app (e.g. Caddy); this stack defaults to **8080**
3. Install Docker Engine + Compose plugin on the VM.
4. Clone this repository onto the VM.

### 2. Environment file

```bash
cp .env.example .env
# Fill secrets — never commit .env
```

Critical production values:

| Variable | Value |
|----------|-------|
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | `backend,localhost,127.0.0.1` (Nginx sets `Host: backend`) |
| `DIRECT_URL` or `POSTGRES_*` | Supabase session mode (port `5432`) |
| `CELERY_BROKER_URL` | Redis Cloud `rediss://` URL |
| `CORS_ALLOWED_ORIGINS` / `CSRF_TRUSTED_ORIGINS` / `FRONTEND_URL` | `https://your-app.vercel.app` |
| `CLERK_*`, `NVIDIA_API_KEY`, `FORMATEX_API_KEY`, `SECRET_KEY` | From respective dashboards |

### 3. Start the stack

The CI/CD pipeline deploys a prebuilt image from GHCR (see [CI/CD](#cicd-github-actions)).
To start it manually on the VM with a prebuilt image:

```bash
export BACKEND_IMAGE=ghcr.io/ashoksanaka/resume-refiner-backend:latest
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

Local build fallback (no registry image):

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

What runs:

| Service | Role |
|---------|------|
| `migrate` | One-shot: `migrate`, `sync_templates`, `collectstatic` |
| `web` | Gunicorn (`scripts/start-web.sh`), internal port 8000 |
| `celery_worker` | Resume generation + maintenance queues |
| `celery_beat` | Periodic tasks (single instance only) |
| `nginx` | Public host port **8080** → container 80; proxies `/api/` and `/admin/`, serves `/static/` and `/media/` |

Migrations run once per deploy in the `migrate` service before web/worker start.

Profile pictures and other uploads are stored under `/app/media` on the named `media_files` volume and served by Nginx at `/media/`.


### 4. Vercel frontend configuration

In the Resume-Refiner-frontend Vercel project (server-only vars):

```bash
BACKEND_URL=http://<AWS_ELASTIC_IP>:8080
ALLOW_INSECURE_BACKEND=true
NEXT_PUBLIC_API_URL=/api/v1
```

Keep the browser on same-origin `/api/v1` and `/media` (Next.js rewrites) so HTTPS
pages never call the HTTP VM directly — mixed-content safe. Redeploy the frontend
after setting these. Override the host port with `HTTP_PORT` if needed (default `8080`).

When you add TLS on the VM (or an ALB), switch to:

```bash
BACKEND_URL=https://api.yourdomain.com
# remove ALLOW_INSECURE_BACKEND
```

### 5. Clerk webhook

Point Clerk at the **Vercel HTTPS proxy**, not the raw Elastic IP:

```
https://your-app.vercel.app/api/v1/auth/clerk/webhook
```

Subscribe to `user.created`, `user.updated`, and `user.deleted`. Nginx forwards Svix signature headers to Django.

### 6. Verify

```bash
# Direct VM health (HTTP on 8080 — avoids conflict with other apps on :80)
curl -fsS http://<AWS_ELASTIC_IP>:8080/api/v1/health
curl -fsS http://<AWS_ELASTIC_IP>:8080/healthz

# Proxied through Vercel (HTTPS)
curl -fsS https://your-app.vercel.app/api/v1/health

# Container status
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f web celery_worker nginx
```

Smoke tests: sign-in, profile save, resume generation (202 + poll), PDF download, Clerk user sync.

### 7. Persistence and upgrades

- Generated PDFs live in the Docker named volume `generated_pdfs`, shared by `web` and `celery_worker`.
- The volume survives container recreation on the **same VM**; it does **not** survive VM replacement. Use EBS snapshots / AMI backups for durability.
- Users should still download PDFs promptly (`DATA_TTL_HOURS`, default 24).
- Upgrade: push to `main` and let CI/CD deploy, or manually:

```bash
git pull
export BACKEND_IMAGE=ghcr.io/ashoksanaka/resume-refiner-backend:latest
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

The `migrate` service re-runs migrations and `collectstatic` on each recreate.

## CI/CD (GitHub Actions)

Two workflows in [`.github/workflows`](.github/workflows):

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| [`ci.yml`](.github/workflows/ci.yml) | Pull requests, non-`main` pushes | Runs `pytest` against a Postgres service and validates the Docker image builds |
| [`deploy.yml`](.github/workflows/deploy.yml) | Push to `main`, manual dispatch | Runs CI, builds and pushes the image to GHCR, then deploys to the AWS VM over SSH |

```mermaid
flowchart LR
  push[Push to main] --> test[CI tests]
  test --> build[Build image]
  build --> ghcr[(GHCR)]
  build --> ssh[SSH to AWS VM]
  ghcr --> pull[VM docker compose pull]
  ssh --> pull
  pull --> up[compose up -d]
  up --> health[healthz check]
```

### Deployment flow

1. `deploy.yml` reuses `ci.yml` and blocks on green tests.
2. The image is built once and pushed to `ghcr.io/ashoksanaka/resume-refiner-backend` tagged with the commit SHA and `latest`.
3. The `deploy` job SSHes into the VM, fast-forwards the checked-out repo to the deployed SHA (for `docker-compose.prod.yml` / `deploy/nginx.conf`), then runs [`scripts/deploy.sh`](scripts/deploy.sh) which logs in to GHCR, pulls the image, restarts the stack, prunes old images, and polls `http://localhost:8080/healthz`.

### Required GitHub configuration

Create a `production` environment (Settings -> Environments) and add these secrets:

| Secret | Description |
|--------|-------------|
| `AWS_VM_HOST` | VM public IP / DNS (Elastic IP) |
| `AWS_VM_USER` | SSH user (e.g. `ubuntu`) |
| `AWS_VM_SSH_KEY` | Private SSH key (PEM) with access to the VM |
| `AWS_VM_SSH_PORT` | Optional SSH port (defaults to `22`) |
| `AWS_VM_APP_DIR` | Optional repo path on the VM (defaults to `~/Resume-Refiner-Backend`) |

`GITHUB_TOKEN` is provided automatically and is used to push to and pull from GHCR (no extra registry secret needed).

### One-time VM bootstrap

On the AWS VM (see [AWS VM Deployment](#aws-vm-deployment-docker-compose) for security groups and Docker install):

```bash
# Clone into the path referenced by AWS_VM_APP_DIR (default shown)
git clone https://github.com/Ashoksanaka/Resume-Refiner-Backend.git ~/Resume-Refiner-Backend
cd ~/Resume-Refiner-Backend
cp .env.example .env   # fill production values (never committed)
```

Ensure the SSH user is in the `docker` group so the pipeline can run Docker without `sudo`:

```bash
sudo usermod -aG docker "$USER"   # then reconnect
```

After that, every push to `main` deploys automatically. Use the Actions tab -> "Deploy to AWS VM" -> "Run workflow" to deploy manually.

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
├── .github/workflows/      # CI (tests) and Deploy (GHCR + SSH) pipelines
├── deploy/nginx.conf       # Production Nginx reverse proxy
├── scripts/start-web.sh          # Gunicorn
├── scripts/start-migrate.sh      # migrate + sync_templates + collectstatic
├── scripts/deploy.sh             # VM deploy: pull image + compose up + healthcheck
├── Dockerfile
├── docker-compose.yml      # Local dev (backend + celery)
├── docker-compose.prod.yml # AWS VM production stack
├── requirements.txt        # Runtime dependencies (Docker image)
└── requirements-dev.txt    # Runtime + pytest / factories
```

## API Documentation

- **OpenAPI Spec**: `/openapi/v1/openapi.yaml`
- **Admin Panel**: `/admin/` (requires superuser account)

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest app/profiles/test_picture_upload.py app/authentication/tests.py app/resumes/tests.py -v
```

## Troubleshooting

### Database Connection Issues
- Use Supabase **Session mode** (port `5432`), not transaction pooler port `6543` (required for Celery Beat).
- Verify `POSTGRES_SSLMODE=require` for Supabase.

### Celery Tasks Not Running
- Ensure `CELERY_BROKER_URL` uses Redis Cloud `rediss://` URL.
- Check worker logs: `docker compose -f docker-compose.prod.yml logs celery_worker`
  (local dev: `docker compose logs celery_worker`)

### AI Generation Fails
- Verify `NVIDIA_API_KEY` is set on the **worker** service (generation runs in Celery).
- Check `NVIDIA_MODEL` matches an available NIM model.

## License

Proprietary - All rights reserved

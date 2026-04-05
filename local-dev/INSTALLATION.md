# Installing DeployCtrl

DeployCtrl is a Django REST API + Web UI for self-service infrastructure provisioning. It uses **MongoDB** for all data storage and exposes a JWT-authenticated API alongside a browser-based dashboard.

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.11+ | For local install |
| Docker + Docker Compose | 24+ | For Docker install |
| MongoDB | 6+ | Required for local install; included in Docker |

---

## Option 1 — Docker Compose (recommended)

The fastest way to get running. Docker Compose starts both the API and a MongoDB instance automatically.

```bash
git clone <repo-url> deployctrl
cd deployctrl

# (Optional) override defaults
cp .env.example .env
# Edit .env — at minimum change SECRET_KEY for any non-dev use

docker compose up --build
```

The API will be available at **http://localhost:8000** once the container prints `Booting worker`.

To stop:

```bash
docker compose down          # keep data
docker compose down -v       # also delete the MongoDB volume
```

To reset and re-seed demo data:

```bash
docker compose run --rm api python manage.py seed_data --reset
```

---

## Option 2 — Local Python Install

Use this if you want to run the server directly on your machine for development.

### 1. Clone and run the installer

```bash
git clone <repo-url> deployctrl
cd deployctrl
bash install.sh
```

The script will:
- Verify Python 3.11+ is available
- Create a `.venv` virtual environment
- Install all dependencies from `requirements.txt`
- Copy `.env.example` → `.env` and generate a random `SECRET_KEY`
- Collect static files
- Run database migrations
- Seed demo teams, roles, and users

### 2. Point to your MongoDB instance

Edit `.env` and set `MONGO_URI` if MongoDB is not on `localhost:27017`:

```dotenv
MONGO_URI=mongodb://localhost:27017/deployctrl
```

### 3. Start the server

```bash
source .venv/bin/activate
python manage.py runserver
```

Or with gunicorn (closer to production):

```bash
source .venv/bin/activate
gunicorn deployctrl.wsgi:application --bind 0.0.0.0:8000 --workers 2 --reload
```

---

## Environment Variables

All variables are read from `.env` (via `python-decouple`). Copy `.env.example` to get started.

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | *(generated)* | Django secret key — **change in production** |
| `DEBUG` | `True` | Set to `False` in production |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated list of allowed hostnames |
| `MONGO_URI` | `mongodb://localhost:27017/deployctrl` | MongoDB connection string |
| `MONGO_DB` | `deployctrl` | MongoDB database name |
| `JWT_ACCESS_HOURS` | `8` | Access token lifetime in hours |
| `JWT_REFRESH_DAYS` | `7` | Refresh token lifetime in days |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Comma-separated allowed CORS origins |

---

## Demo Accounts

Seeded automatically by `python manage.py seed_data`:

| Username | Password | Role | Team |
|----------|----------|------|------|
| `admin` | `adminpassword123` | admin | Platform |
| `alice` | `demopassword123` | developer | Product A |
| `bob` | `demopassword123` | architect | Governance |

Reset and re-seed at any time:

```bash
python manage.py seed_data --reset
```

---

## API Endpoints

| Prefix | Description |
|--------|-------------|
| `POST /api/auth/login/` | Obtain JWT access + refresh tokens |
| `POST /api/auth/refresh/` | Refresh access token |
| `GET/POST /api/templates/` | Infrastructure template catalog |
| `GET/POST /api/requests/` | Infrastructure provisioning requests |
| `GET /api/audit/` | Audit log |
| `GET/POST /api/teams/` | Team management |
| `GET/PUT /api/settings/` | GitOps configuration |

All endpoints (except auth) require `Authorization: Bearer <access_token>`.

---

## Production Checklist

- [ ] Set `DEBUG=False`
- [ ] Set a strong, unique `SECRET_KEY`
- [ ] Set `ALLOWED_HOSTS` to your real domain(s)
- [ ] Use a managed MongoDB instance or secure your self-hosted one with authentication
- [ ] Update `MONGO_URI` with credentials: `mongodb://user:pass@host:27017/deployctrl`
- [ ] Restrict `CORS_ALLOWED_ORIGINS` to your frontend URL
- [ ] Run behind a reverse proxy (nginx, Caddy) with TLS
- [ ] Set `JWT_ACCESS_HOURS` and `JWT_REFRESH_DAYS` to match your security policy

---

## Upgrading

```bash
git pull
pip install -r requirements.txt   # pick up new dependencies
python manage.py migrate           # apply any new migrations
```

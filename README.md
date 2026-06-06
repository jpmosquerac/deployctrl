# DeployCtrl

Self-service infrastructure provisioning platform. Developers submit requests for cloud resources, architects approve them, and DeployCtrl automatically generates Terraform files, pushes them to a GitOps repository, and runs `terraform apply` — all from a browser-based dashboard.

---

## Features

- **Template catalog** — reusable infrastructure templates (EC2, S3, custom modules)
- **Request workflow** — submit → approve → provision, with team-based cost thresholds for auto-approval
- **GitOps integration** — rendered Terraform files are committed to a GitHub repository before provisioning
- **Terraform automation** — `terraform apply` and `terraform destroy` run in the background; logs stream to the UI
- **Decommission** — one-click destroy: runs `terraform destroy`, deletes the GitHub folder, removes state from MongoDB
- **Role-based access** — `admin`, `architect`, `developer`, `user` roles with per-permission granularity
- **Audit log** — immutable log of every platform action
- **HTTP Terraform backend** — state stored in MongoDB (no S3 or remote backend required)

---

## Prerequisites

| Dependency | Version | Notes |
|------------|---------|-------|
| Python | 3.11+ | |
| Git | 2.x+ | Required for GitOps cloning during Terraform runs |
| MongoDB | 7+ | Local or Atlas |
| Terraform | 1.10+ | Auto-installed by `install.sh` on Linux/macOS |
| Docker & Compose | any recent | Docker path only |

---

## Quick start

### Docker Compose (recommended)

```bash
git clone https://github.com/jpmosquerac/deployctrl.git
cd deployctrl
docker compose -f local-dev/docker-compose.yml up --build
```

Open **http://localhost:8000**. Demo credentials are seeded automatically:

| Username | Password | Role |
|----------|----------|------|
| `admin` | `adminpassword123` | admin |
| `alice` | `demopassword123` | developer |
| `bob` | `demopassword123` | architect |

### Local install (no Docker)

```bash
git clone https://github.com/jpmosquerac/deployctrl.git
cd deployctrl
bash local-dev/install.sh
source .venv/bin/activate
python manage.py runserver
```

`install.sh` creates `.venv/`, installs dependencies, generates `.env` from `.env.example`, and seeds demo data. See [local-dev/INSTALLATION.md](local-dev/INSTALLATION.md) for detailed setup, environment variables, and a production checklist.

---

## Project layout

```
deployctrl/
├── apps/
│   ├── accounts/        # Users, roles, JWT auth (MongoDB)
│   ├── audit/           # Immutable audit log
│   ├── catalog/         # Template CRUD (disk-based JSON + .tf files)
│   ├── gitops/          # GitOps config model
│   ├── infra_requests/  # Request lifecycle and provisioning
│   ├── resources/       # Terraform renderer + GitHub push
│   ├── teams/           # Team management
│   ├── terraform/       # Run tracking, HTTP state backend, runner
│   └── web/             # Serves the dashboard SPA
├── deploy/
│   └── aws/             # CloudFormation + deploy script for EC2 deployment
├── deployctrl/          # Django project settings, URLs, WSGI
├── local-dev/           # Docker Compose and local install scripts
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── install.sh
│   └── INSTALLATION.md
├── templates/           # HTML templates (dashboard, login)
├── tf_templates/        # Infrastructure template library
│   ├── default/         # Backend config injected into every run
│   ├── ec2_instance/
│   └── s3_bucket/
├── .env.example         # Copy to .env and fill in values
├── manage.py
└── requirements.txt
```

---

## Template library

Templates live in `tf_templates/<slug>/` as a pair of files:

- `<slug>.json` — metadata (id, name, category, cost, parameters schema)
- `<slug>.tf` — the Terraform module

The `default/` folder contains `main.tf`, which is the HTTP backend configuration injected into every run. It is not listed in the catalog.

Templates can be created, edited, and deleted from the **Templates** section of the dashboard (architect/admin only).

---

## GitOps & Terraform

When a request is approved, DeployCtrl:

1. Renders `main.tf` + `terraform.tfvars` from the template and request parameters
2. Pushes the files to `<team>/<REQ-NNNN>/` in the configured GitHub repository
3. Clones the repo, copies the files into an isolated workspace, runs `terraform init && terraform apply`
4. Streams stdout/stderr to the `TerraformRun` document in MongoDB
5. Marks the request as `provisioned` on success

Decommissioning runs `terraform destroy`, removes the GitHub folder, deletes the Terraform state document, and marks the request as `decommissioned`.

Configure the GitOps integration from the **Configuration** section of the dashboard.

---

## API

All endpoints require `Authorization: Bearer <token>` except auth routes.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/auth/login/` | Obtain access + refresh tokens |
| `POST` | `/api/auth/refresh/` | Refresh access token |
| `GET/POST` | `/api/templates/` | List or create templates |
| `GET/PUT/DELETE` | `/api/templates/<id>/` | Get, update, or delete a template |
| `GET/POST` | `/api/requests/` | List or submit requests |
| `GET/PATCH` | `/api/requests/<id>/` | Get or update (approve/reject) a request |
| `POST` | `/api/requests/<id>/retry/` | Re-trigger a failed Terraform run |
| `POST` | `/api/requests/<id>/decommission/` | Destroy and decommission a request |
| `GET` | `/api/requests/<id>/outputs/` | Get Terraform outputs for a request |
| `GET` | `/api/terraform/runs/` | List Terraform runs |
| `GET` | `/api/terraform/runs/<id>/logs/` | Get full log for a run |
| `GET` | `/api/audit/` | Query the audit log |
| `GET/POST` | `/api/teams/` | List or create teams |
| `GET/PUT` | `/api/settings/gitops/` | Get or update GitOps config |
| `GET` | `/api/users/` | List users |
| `PATCH/DELETE` | `/api/users/<id>/` | Update or deactivate a user |

---

## AWS deployment

A CloudFormation template and deploy script are provided in [`deploy/aws/`](deploy/aws/).

```bash
cd deploy/aws
bash deploy.sh
```

See [`deploy/aws/README.md`](deploy/aws/README.md) for full setup instructions, parameters, and operations guide.

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | *(generated)* | Django secret key |
| `DEBUG` | `True` | Set `False` in production |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated allowed hosts |
| `MONGO_URI` | `mongodb://localhost:27017/deployctrl` | MongoDB connection string |
| `MONGO_DB` | `deployctrl` | MongoDB database name |
| `JWT_ACCESS_HOURS` | `8` | Access token lifetime (hours) |
| `JWT_REFRESH_DAYS` | `7` | Refresh token lifetime (days) |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173,...` | Comma-separated CORS origins |
| `TF_BACKEND_BASE_URL` | `http://127.0.0.1:8000` | Base URL reachable by Terraform for state |
| `TF_STATE_SECRET` | `change-me-in-production` | Shared secret for state endpoint auth |
| `TERRAFORM_WORK_DIR` | `/tmp/deployctrl/workspace` | Temp directory for Terraform runs |

---

## Contributing

Contributions are welcome. Please open an issue before submitting a pull request for significant changes.

1. Fork the repository and create a feature branch
2. Run the test suite before submitting: `python manage.py test`
3. Keep pull requests focused — one feature or fix per PR
4. Follow the existing code style (PEP 8, Django conventions)

---

## License

MIT License — see [LICENSE](LICENSE) for details.
# deployctrl

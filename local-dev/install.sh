#!/usr/bin/env bash
set -euo pipefail

# ── Constants ─────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$APP_DIR/.venv"
PYTHON="${PYTHON:-python3}"

# ── Helpers ───────────────────────────────────────────────────────────────────
info() { echo "==> $*"; }
ok()   { echo "    $*"; }
warn() { echo "WARNING: $*" >&2; }
die()  { echo "ERROR: $*" >&2; exit 1; }

echo "==> DeployCtrl Local Installer"

# ── Validate working directory ────────────────────────────────────────────────
cd "$APP_DIR"
[[ -f "manage.py" ]]        || die "manage.py not found — run this script from within the cloned repo"
[[ -f "requirements.txt" ]] || die "requirements.txt not found"
[[ -f ".env.example" ]]     || die ".env.example not found"

# ── Validate and check Python ─────────────────────────────────────────────────
# Reject PYTHON values that contain anything other than safe path characters.
[[ "$PYTHON" =~ ^[a-zA-Z0-9_./-]+$ ]] \
  || die "PYTHON variable contains unsafe characters: '$PYTHON'"

command -v "$PYTHON" &>/dev/null \
  || die "Python interpreter not found: '$PYTHON'. Install Python 3.11+ or set PYTHON=python3.11"

# Read major and minor in a single subprocess call.
read -r PY_MAJOR PY_MINOR < <("$PYTHON" -c "import sys; print(sys.version_info.major, sys.version_info.minor)")

[[ "$PY_MAJOR" =~ ^[0-9]+$ && "$PY_MINOR" =~ ^[0-9]+$ ]] \
  || die "Could not determine Python version from '$PYTHON'."

{ [[ "$PY_MAJOR" -gt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -ge 9 ]]; }; } \
  || die "Python 3.9+ required (found $PY_MAJOR.$PY_MINOR). Set PYTHON= to point at the right binary."

ok "Python $PY_MAJOR.$PY_MINOR OK"

# ── Check MongoDB ─────────────────────────────────────────────────────────────
if ! command -v mongod &>/dev/null && ! command -v mongosh &>/dev/null; then
  warn "MongoDB not detected locally. Ensure a MongoDB instance is reachable"
  warn "before starting the app. Set MONGO_URI in .env if not on localhost:27017."
fi

# ── Terraform ─────────────────────────────────────────────────────────────────
TERRAFORM_VERSION="1.10.5"
if command -v terraform &>/dev/null; then
  TF_INSTALLED=$(terraform version -json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['terraform_version'])" 2>/dev/null || terraform version | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
  ok "Terraform $TF_INSTALLED already installed"
else
  info "Installing Terraform $TERRAFORM_VERSION"
  OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
  ARCH="$(uname -m)"
  case "$ARCH" in
    x86_64)  ARCH="amd64" ;;
    arm64|aarch64) ARCH="arm64" ;;
    *) die "Unsupported architecture: $ARCH" ;;
  esac

  if [[ "$OS" == "darwin" ]] && command -v brew &>/dev/null; then
    brew install terraform
  else
    TF_ZIP="terraform_${TERRAFORM_VERSION}_${OS}_${ARCH}.zip"
    TF_URL="https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/${TF_ZIP}"
    TF_TMP="$(mktemp -d)"
    curl -fsSL "$TF_URL" -o "$TF_TMP/$TF_ZIP"
    unzip -q "$TF_TMP/$TF_ZIP" -d "$TF_TMP"
    mkdir -p "$HOME/.local/bin"
    mv "$TF_TMP/terraform" "$HOME/.local/bin/terraform"
    chmod +x "$HOME/.local/bin/terraform"
    rm -rf "$TF_TMP"
    # Ensure ~/.local/bin is on PATH for this session
    export PATH="$HOME/.local/bin:$PATH"
    ok "Terraform installed to $HOME/.local/bin/terraform"
    if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
      warn "Add \$HOME/.local/bin to your PATH to use terraform outside this session"
    fi
  fi
fi

# ── Virtual environment ───────────────────────────────────────────────────────
if [[ ! -d "$VENV_DIR" ]]; then
  info "Creating virtual environment at $VENV_DIR"
  "$PYTHON" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
ok "Virtual environment active"

# ── Dependencies ──────────────────────────────────────────────────────────────
info "Installing dependencies"
pip install --upgrade pip -q
pip install -r requirements.txt -q
ok "Dependencies installed"

# ── Environment file ──────────────────────────────────────────────────────────
if [[ ! -f "$APP_DIR/.env" ]]; then
  info "Creating .env from .env.example"
  cp .env.example "$APP_DIR/.env"

  # Use Python for the replacement so special characters in the generated
  # secret (e.g. | & $ /) can never break a sed delimiter or shell expansion.
  python - "$APP_DIR/.env" <<'PYEOF'
import secrets, string, pathlib, sys

env_path = pathlib.Path(sys.argv[1])
content = env_path.read_text()

placeholder = "django-insecure-replace-with-a-real-secret-key-in-production"
if placeholder not in content:
    print("    .env already has a custom SECRET_KEY — leaving it unchanged.")
else:
    allowed = string.ascii_letters + string.digits + "!@#%^&*-_=+"
    secret = "".join(secrets.choice(allowed) for _ in range(50))
    env_path.write_text(content.replace(placeholder, secret, 1))
    print("    SECRET_KEY generated and written to .env")
PYEOF

  ok "Edit .env to set MONGO_URI if MongoDB is not on localhost:27017"
else
  ok ".env already exists — skipping"
fi

# ── Template directory ────────────────────────────────────────────────────────
info "Checking tf_templates directory"
if [[ ! -d "tf_templates" ]]; then
  die "tf_templates/ not found. Re-clone the repository to restore the default templates."
fi
chmod -R u+rwX tf_templates
ok "tf_templates OK"

# ── Static files ──────────────────────────────────────────────────────────────
info "Collecting static files"
python manage.py collectstatic --noinput -v 0

# ── Seed demo data ────────────────────────────────────────────────────────────
info "Seeding demo data (teams, roles, users)"
python manage.py seed_data

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
info "Installation complete!"
echo ""
echo "    Start the development server:"
echo "      source .venv/bin/activate && python manage.py runserver"
echo ""
echo "    Or with gunicorn:"
echo "      source .venv/bin/activate && gunicorn deployctrl.wsgi:application --bind 0.0.0.0:8000"
echo ""
echo "    API:    http://localhost:8000/api/"
echo "    Web UI: http://localhost:8000/"
echo ""
echo "    Demo credentials:"
echo "      admin / adminpassword123  (admin)"
echo "      alice / demopassword123   (developer)"
echo "      bob   / demopassword123   (architect)"

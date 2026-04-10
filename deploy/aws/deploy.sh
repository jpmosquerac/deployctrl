#!/usr/bin/env bash
# deploy.sh — packages DeployCtrl and deploys it to AWS via CloudFormation
set -euo pipefail

STACK_NAME="deployctrl"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
KEY_PAIR="${KEY_PAIR:-InstanceKey}"
KEY_PEM="${KEY_PEM:-/Users/jp/Documents/instance_test/InstanceKey.pem}"
SSH_CIDR="${SSH_CIDR:-0.0.0.0/0}"
S3_KEY="deployctrl.tar.gz"

# ── Derive S3 bucket name from AWS account ID ─────────────────────────────────
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
S3_BUCKET="${S3_BUCKET:-deployctrl-code-${ACCOUNT_ID}}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "==> Packaging application code..."
TMPDIR_CODE=$(mktemp -d)
trap 'rm -rf "$TMPDIR_CODE"' EXIT

tar -czf "$TMPDIR_CODE/$S3_KEY" \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='*.pyo' \
  --exclude='.env' \
  --exclude='staticfiles' \
  --exclude='.DS_Store' \
  --exclude='._*' \
  -C "$PROJECT_ROOT" .

echo "==> Ensuring S3 bucket exists: $S3_BUCKET"
if ! aws s3api head-bucket --bucket "$S3_BUCKET" 2>/dev/null; then
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$S3_BUCKET" --region "$REGION"
  else
    aws s3api create-bucket --bucket "$S3_BUCKET" --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION"
  fi
  aws s3api put-public-access-block --bucket "$S3_BUCKET" \
    --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
fi

echo "==> Uploading code tarball to s3://$S3_BUCKET/$S3_KEY"
aws s3 cp "$TMPDIR_CODE/$S3_KEY" "s3://$S3_BUCKET/$S3_KEY"

echo "==> Generating Django secret key..."
SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")

# ── Check for existing stack ──────────────────────────────────────────────────
EXISTING=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query 'Stacks[0].StackStatus' \
  --output text 2>/dev/null || echo "NONE")

if [[ "$EXISTING" == *ROLLBACK_COMPLETE* ]]; then
  echo "==> Deleting previous ROLLBACK_COMPLETE stack..."
  aws cloudformation delete-stack --stack-name "$STACK_NAME"
  aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME"
  EXISTING="NONE"
fi

if [ "$EXISTING" = "NONE" ]; then
  echo "==> Creating CloudFormation stack: $STACK_NAME"
  aws cloudformation create-stack \
    --stack-name "$STACK_NAME" \
    --template-body file://"$SCRIPT_DIR/cloudformation.yml" \
    --capabilities CAPABILITY_NAMED_IAM \
    --region "$REGION" \
    --parameters \
      ParameterKey=CodeS3Bucket,ParameterValue="$S3_BUCKET" \
      ParameterKey=CodeS3Key,ParameterValue="$S3_KEY" \
      ParameterKey=AppSecretKey,ParameterValue="$SECRET" \
      ParameterKey=KeyPairName,ParameterValue="$KEY_PAIR" \
      ParameterKey=SSHLocation,ParameterValue="$SSH_CIDR"

  echo "==> Waiting for stack creation..."
  aws cloudformation wait stack-create-complete --stack-name "$STACK_NAME"
  INSTANCE_IP=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --query 'Stacks[0].Outputs[?OutputKey==`PublicIP`].OutputValue' \
    --output text)
  echo "==> Stack created. App running at http://$INSTANCE_IP"

else
  echo "==> Stack already exists ($EXISTING) — deploying code to running instance..."

  # Get the instance IP from stack outputs
  INSTANCE_IP=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --query 'Stacks[0].Outputs[?OutputKey==`PublicIP`].OutputValue' \
    --output text)

  if [ -z "$INSTANCE_IP" ]; then
    echo "ERROR: Could not determine instance IP from stack outputs." >&2
    exit 1
  fi

  echo "==> SSHing into $INSTANCE_IP to update code..."
  ssh -i "$KEY_PEM" -o StrictHostKeyChecking=no "ec2-user@$INSTANCE_IP" \
    "set -e
     aws s3 cp s3://$S3_BUCKET/$S3_KEY /tmp/deployctrl.tar.gz
     sudo tar -xzf /tmp/deployctrl.tar.gz -C /opt/deployctrl --overwrite 2>/dev/null
     sudo find /opt/deployctrl/tf_templates -name '._*' -delete 2>/dev/null || true
     rm /tmp/deployctrl.tar.gz
     sudo chown -R deployctrl:deployctrl /opt/deployctrl
     sudo chmod -R g+rw /opt/deployctrl/tf_templates
     sudo /opt/deployctrl/.venv/bin/pip install -r /opt/deployctrl/requirements.txt -q
     cd /opt/deployctrl && sudo -u deployctrl /opt/deployctrl/.venv/bin/python manage.py collectstatic --noinput -v 0
     sudo systemctl restart deployctrl
     sudo systemctl is-active deployctrl"

  echo ""
  echo "==> Deployment complete. App running at http://$INSTANCE_IP"
fi

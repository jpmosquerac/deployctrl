# AWS Deployment — CloudFormation

Deploys DeployCtrl on a single EC2 instance running Django (gunicorn), MongoDB, and Nginx.
Everything is bootstrapped automatically via UserData on first boot.

---

## Prerequisites

- AWS CLI installed and configured (`aws configure`)
- An existing EC2 key pair in the target region
- Git repository with the DeployCtrl source code accessible via HTTPS
- IAM permissions: `cloudformation:*`, `ec2:*`, `iam:*`

---

## Quick deploy

**1. Store the Django secret key in SSM (one-time setup):**

```bash
aws ssm put-parameter \
  --name /deployctrl/secret-key \
  --value "$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')" \
  --type SecureString
```

**2. Deploy the stack:**

```bash
aws cloudformation create-stack \
  --stack-name deployctrl \
  --template-body file://cloudformation.yml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters \
    ParameterKey=InstanceType,ParameterValue=t3.small \
    ParameterKey=DiskSizeGB,ParameterValue=30 \
    ParameterKey=DiskType,ParameterValue=gp3 \
    ParameterKey=KeyPairName,ParameterValue=InstanceKey \
    ParameterKey=GitRepoUrl,ParameterValue=https://github.com/<your-org>/deployctrl.git \
    ParameterKey=SSHLocation,ParameterValue=203.0.113.10/32
```

> `AppSecretKey` is read automatically from SSM (`/deployctrl/secret-key`) — do not pass it on the CLI.

CloudFormation waits up to **20 minutes** for the instance to finish bootstrapping before marking the stack `CREATE_COMPLETE`. If anything fails during setup the stack automatically rolls back.

### Watch deployment progress

```bash
aws cloudformation describe-stack-events \
  --stack-name deployctrl \
  --query 'StackEvents[*].[Timestamp,ResourceStatus,ResourceType,ResourceStatusReason]' \
  --output table
```

### Get the application URL after deploy

```bash
aws cloudformation describe-stacks \
  --stack-name deployctrl \
  --query 'Stacks[0].Outputs' \
  --output table
```

---

## Parameters

| Parameter | Default | Required | Description |
|---|---|---|---|
| `InstanceType` | `t3.small` | No | EC2 instance type (see sizing guide below) |
| `DiskSizeGB` | `20` | No | EBS root volume size in GB (20–500) |
| `DiskType` | `gp3` | No | EBS volume type: `gp3`, `gp2`, or `io1` |
| `KeyPairName` | — | **Yes** | Existing EC2 key pair name in the target region |
| `SSHLocation` | `0.0.0.0/0` | No | CIDR allowed to SSH — restrict to your IP in production |
| `GitRepoUrl` | — | **Yes** | HTTPS URL of the DeployCtrl repository |
| `GitBranch` | `main` | No | Branch to clone and deploy |
| `AppSecretKey` | `/deployctrl/secret-key` | No | SSM parameter path for the Django `SECRET_KEY` — store with `SecureString` before deploying |
| `AllowedHosts` | `*` | No | Comma-separated Django `ALLOWED_HOSTS` |
| `CORSAllowedOrigins` | _(empty)_ | No | Comma-separated CORS origins for the API |
| `Environment` | `production` | No | `production` sets `DEBUG=False` |
| `MongoDBVersion` | `8.0` | No | MongoDB version: `7.0` or `8.0` |
| `JWTAccessHours` | `8` | No | JWT access token lifetime in hours (1–72) |
| `JWTRefreshDays` | `7` | No | JWT refresh token lifetime in days (1–30) |

### Instance sizing guide

| Instance | vCPU | RAM | Recommended for |
|---|---|---|---|
| `t3.micro` | 2 | 1 GB | Testing only |
| `t3.small` | 2 | 2 GB | Small teams, < 20 users |
| `t3.medium` | 2 | 4 GB | Medium teams, < 100 users |
| `t3.large` | 2 | 8 GB | Large teams or high request volume |
| `t3.xlarge` | 4 | 16 GB | Heavy workloads |
| `m5.large` | 2 | 8 GB | Consistent workloads (no burst credits) |

### Generate and store a secure secret key

```bash
aws ssm put-parameter \
  --name /deployctrl/secret-key \
  --value "$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')" \
  --type SecureString
```

---

## What gets provisioned

### AWS resources

| Resource | Type | Notes |
|---|---|---|
| `AppRole` | IAM Role | SSM Session Manager + CloudWatch Logs |
| `AppInstanceProfile` | IAM Instance Profile | Attached to the EC2 instance |
| `AppSecurityGroup` | EC2 Security Group | SSH (restricted), HTTP 80, HTTPS 443 |
| `AppEIP` | Elastic IP | Persistent public IP — survives reboots |
| `AppEIPAssociation` | EIP Association | Binds EIP to the instance |
| `AppInstance` | EC2 Instance | Amazon Linux 2023, encrypted EBS |

### Stack outputs

| Output | Description |
|---|---|
| `ApplicationURL` | `http://<elastic-ip>` — open in your browser |
| `PublicIP` | Elastic IP address |
| `SSHCommand` | Ready-to-run `ssh` command |
| `InstanceId` | EC2 instance ID |
| `AppLogsPath` | `/var/log/deployctrl/` — gunicorn access and error logs |
| `InitLogPath` | `/var/log/deployctrl-init.log` — bootstrap log, check here first on failure |
| `AllowedHostsReminder` | Reminds you to update `ALLOWED_HOSTS` after deploy |

---

## What the bootstrap script does

The UserData script runs automatically on first boot and signals CloudFormation when it finishes.

1. **cfn-bootstrap** — installs the CloudFormation helper tools needed for `cfn-signal`
2. **System packages** — `dnf update`, installs Python 3.11, Nginx, Git
3. **MongoDB** — adds the official MongoDB repo, installs and starts `mongod`
4. **System user** — creates a `deployctrl` user with no login shell
5. **Clone repo** — clones `GitRepoUrl` at `GitBranch` into `/opt/deployctrl`
6. **Python venv** — creates `.venv` with Python 3.11, installs `requirements.txt`
7. **Environment file** — writes `/opt/deployctrl/.env` from CloudFormation parameters (mode `600`, owned by `deployctrl`)
8. **Static files** — runs `python manage.py collectstatic`
9. **Seed data** — runs `python manage.py seed_data` (demo users, teams, roles)
10. **Systemd service** — installs and starts `deployctrl.service` (gunicorn, depends on `mongod`)
11. **Nginx** — installs reverse proxy config, serves `/static/` directly, proxies everything else to gunicorn on `127.0.0.1:8000`
12. **cfn-signal** — notifies CloudFormation of success (or failure, triggering rollback)

### Services on the instance

| Service | Port | Managed by |
|---|---|---|
| `mongod` | 27017 (localhost only) | systemd |
| `deployctrl` (gunicorn) | 8000 (localhost only) | systemd |
| `nginx` | 80 / 443 | systemd |

---

## Post-deployment steps

### 1. Update ALLOWED_HOSTS

After the stack is created, replace `*` with the actual Elastic IP or your domain:

```bash
ssh -i InstanceKey.pem ec2-user@<elastic-ip>
sudo sed -i 's/^ALLOWED_HOSTS=.*/ALLOWED_HOSTS=<elastic-ip>,app.example.com/' /opt/deployctrl/.env
sudo systemctl restart deployctrl
```

### 2. Set up a domain (optional)

Point your domain's A record to the Elastic IP, then update `ALLOWED_HOSTS` as above.

### 3. Enable HTTPS (recommended for production)

Install Certbot and get a free Let's Encrypt certificate:

```bash
ssh -i InstanceKey.pem ec2-user@<elastic-ip>
sudo dnf install -y certbot python3-certbot-nginx
sudo certbot --nginx -d app.example.com
```

Certbot will update the nginx config automatically and set up auto-renewal.

### 4. Change demo passwords

The seed script creates three demo accounts. Change their passwords before exposing the app publicly:

```bash
ssh -i InstanceKey.pem ec2-user@<elastic-ip>
cd /opt/deployctrl
sudo -u deployctrl .venv/bin/python manage.py shell -c "
from apps.accounts.mongo_models import MongoUser
for username, pw in [('admin','your-new-admin-pw'), ('alice','your-new-alice-pw'), ('bob','your-new-bob-pw')]:
    u = MongoUser.objects(username=username).first()
    if u: u.set_password(pw); u.save(); print(f'Updated {username}')
"
```

---

## Operations

### Check application status

```bash
ssh -i InstanceKey.pem ec2-user@<elastic-ip>
sudo systemctl status deployctrl
sudo systemctl status mongod
sudo systemctl status nginx
```

### View logs

```bash
# Gunicorn access log
sudo tail -f /var/log/deployctrl/access.log

# Gunicorn error log
sudo tail -f /var/log/deployctrl/error.log

# Bootstrap log (useful if deployment failed)
sudo cat /var/log/deployctrl-init.log

# Systemd journal
sudo journalctl -u deployctrl -f
```

### Restart the application

```bash
sudo systemctl restart deployctrl
```

### Deploy a new version

```bash
ssh -i InstanceKey.pem ec2-user@<elastic-ip>
cd /opt/deployctrl
sudo -u deployctrl git pull origin main
sudo -u deployctrl .venv/bin/pip install -r requirements.txt -q
sudo -u deployctrl .venv/bin/python manage.py collectstatic --noinput -v 0
sudo systemctl restart deployctrl
```

### Connect without SSH key (SSM Session Manager)

Because the instance has the `AmazonSSMManagedInstanceCore` policy attached, you can open a shell from the AWS Console or CLI without a key pair:

```bash
aws ssm start-session --target <instance-id>
```

---

## Update the stack

To change the instance type, disk size, or any other parameter without destroying the stack:

```bash
aws cloudformation update-stack \
  --stack-name deployctrl \
  --template-body file://cloudformation.yml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters \
    ParameterKey=InstanceType,ParameterValue=t3.medium \
    ParameterKey=DiskSizeGB,UsePreviousValue=true \
    ParameterKey=DiskType,UsePreviousValue=true \
    ParameterKey=KeyPairName,UsePreviousValue=true \
    ParameterKey=GitRepoUrl,UsePreviousValue=true
```

> **Note:** Changing `InstanceType` requires stopping and starting the instance, causing a brief downtime. Changing `DiskSizeGB` or `DiskType` replaces the root volume — back up MongoDB data first.

---

## Delete the stack

```bash
aws cloudformation delete-stack --stack-name deployctrl
```

This deletes the EC2 instance, security group, IAM role, and Elastic IP.
**MongoDB data is not backed up before deletion — export it first if needed:**

```bash
ssh -i InstanceKey.pem ec2-user@<elastic-ip>
mongodump --uri="mongodb://localhost:27017/deployctrl" --out=/tmp/deployctrl-backup
# Copy the backup off the instance before deleting the stack
scp -i InstanceKey.pem -r ec2-user@<elastic-ip>:/tmp/deployctrl-backup ./
```

---

## Troubleshooting

| Symptom | Where to look | Likely cause |
|---|---|---|
| Stack stuck at `CREATE_IN_PROGRESS` | CloudFormation Events tab | UserData script running — wait up to 20 min |
| Stack rolls back | `/var/log/deployctrl-init.log` | Package install or git clone failed |
| 502 Bad Gateway | `journalctl -u deployctrl` | Gunicorn crashed — check `.env` values |
| MongoDB connection error | `journalctl -u mongod` | `mongod` not running or wrong `MONGO_URI` |
| Static files return 404 | nginx error log | `collectstatic` didn't run — re-run manually |
| `DisallowedHost` error | gunicorn error log | `ALLOWED_HOSTS` doesn't include the server's IP/domain |

# Blue/Green Deployment on AWS — GitHub Actions

End-to-end Blue/Green deployment for DeployCtrl on AWS, driven by
[`.github/workflows/deploy-bg.yml`](../../.github/workflows/deploy-bg.yml).

## Architecture

```
                       ┌────────────────────────────┐
   Internet ──► ALB ──►│ Listener :80               │
                       │   default → live-color TG  │
                       └─────┬──────────────┬───────┘
                             │              │
                    ┌────────▼──────┐  ┌────▼──────────┐
                    │ blue TG       │  │ green TG      │
                    └────────┬──────┘  └────┬──────────┘
                             │              │
                       ┌─────▼────┐    ┌────▼─────┐
                       │  ASG     │    │   ASG    │
                       │ blue x1  │    │ green x1 │
                       └─────┬────┘    └────┬─────┘
                             │              │
                             └──────┬───────┘
                                    │ MONGO_URI=mongodb://<mongo-priv-ip>:27017
                                    ▼
                          ┌──────────────────┐
                          │  MongoDB EC2     │   ← persistent stack
                          │  (long-lived)    │
                          └──────────────────┘
```

Three CloudFormation stacks:

| Stack | Template | Lifetime |
|---|---|---|
| `deployctrl-persistent` | `bg-persistent.yml` | One-time; holds ALB, both TGs, listener, MongoDB |
| `deployctrl-app-blue`   | `bg-app.yml`        | Recreated on deploys *to* blue |
| `deployctrl-app-green`  | `bg-app.yml`        | Recreated on deploys *to* green |

The workflow auto-picks the *inactive* color, deploys it fresh, health-checks it
through its target group, then flips the ALB listener. The previous color stays
running until the **next** deploy (gives you an instant-rollback window).

---

## One-time setup

### 1. Deploy the persistent stack

```bash
# Pick a VPC and 2+ public subnets in different AZs (the default VPC works fine).
VPC_ID=$(aws ec2 describe-vpcs --filters Name=is-default,Values=true \
  --query 'Vpcs[0].VpcId' --output text)

SUBNETS=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'Subnets[*].SubnetId' --output text | tr '\t' ',')

aws cloudformation create-stack \
  --stack-name deployctrl-persistent \
  --template-body file://deploy/aws/bg-persistent.yml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters \
    ParameterKey=VpcId,ParameterValue="$VPC_ID" \
    ParameterKey=SubnetIds,ParameterValue="\"$SUBNETS\"" \
    ParameterKey=KeyPairName,ParameterValue=InstanceKey \
    ParameterKey=SSHLocation,ParameterValue=203.0.113.10/32

aws cloudformation wait stack-create-complete --stack-name deployctrl-persistent
```

> The `SSHLocation` parameter restricts SSH to your IP — replace `203.0.113.10/32` accordingly.

### 2. Create an IAM user for GitHub Actions

The user needs permissions to run CloudFormation, ELBv2 changes, EC2/IAM/S3,
and to assume the EC2 instance profile. Minimal inline policy:

<details>
<summary><code>ci-deploy-policy.json</code> — click to expand</summary>

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": "cloudformation:*",         "Resource": "*" },
    { "Effect": "Allow", "Action": "ec2:*",                    "Resource": "*" },
    { "Effect": "Allow", "Action": "autoscaling:*",            "Resource": "*" },
    { "Effect": "Allow", "Action": "elasticloadbalancing:*",   "Resource": "*" },
    { "Effect": "Allow", "Action": "iam:*",                    "Resource": "*" },
    { "Effect": "Allow", "Action": "s3:*",                     "Resource": "*" },
    { "Effect": "Allow", "Action": "ssm:GetParameter*",        "Resource": "*" },
    { "Effect": "Allow", "Action": "sts:GetCallerIdentity",    "Resource": "*" }
  ]
}
```

</details>

Tighten the resource ARNs once everything works (especially `iam:*` and `s3:*`).

```bash
aws iam create-user --user-name deployctrl-ci
aws iam put-user-policy --user-name deployctrl-ci \
  --policy-name deployctrl-ci-deploy \
  --policy-document file://ci-deploy-policy.json
aws iam create-access-key --user-name deployctrl-ci
# → copy AccessKeyId + SecretAccessKey into GitHub secrets below
```

### 3. Set GitHub secrets and variables

In **Settings → Secrets and variables → Actions**:

| Secret | Required | Description |
|---|---|---|
| `AWS_ACCESS_KEY_ID`     | ✅ | From step 2 |
| `AWS_SECRET_ACCESS_KEY` | ✅ | From step 2 |
| `AWS_KEY_PAIR_NAME`     | ✅ | EC2 key pair name (e.g. `InstanceKey`) — must exist in the region |
| `APP_SECRET_KEY`        | ✅ | Django `SECRET_KEY`. Generate once: `python3 -c 'import secrets; print(secrets.token_urlsafe(50))'`. **Must stay constant** so sessions survive the blue↔green swap. |

| Variable | Default | Description |
|---|---|---|
| `AWS_REGION`          | `us-east-1` | |
| `PERSISTENT_STACK`    | `deployctrl-persistent` | Override only if you named the persistent stack differently |
| `APP_STACK_PREFIX`    | `deployctrl-app` | Stack names become `<prefix>-blue` and `<prefix>-green` |
| `INSTANCE_TYPE`       | `t3.small` | App instance type |
| `ALLOWED_HOSTS`       | `*` | Comma-separated. Set to your ALB DNS / domain in production |
| `CORS_ALLOWED_ORIGINS`| _(empty)_ | |
| `APP_ENVIRONMENT`     | `production` | `production` sets `DEBUG=False` |
| `RUN_SEED_DATA`       | `false` | Set to `true` *only* for the very first deploy, to seed demo accounts |

### 4. First deploy

Push to `main` (or run **Actions → Deploy Blue/Green to AWS → Run workflow**).

Because the persistent stack's listener defaults to blue, the first run will
auto-pick **green** and put traffic on it. On the next run, blue gets the new
code and traffic flips back. And so on.

Get the public URL from the persistent stack:

```bash
aws cloudformation describe-stacks --stack-name deployctrl-persistent \
  --query 'Stacks[0].Outputs[?OutputKey==`AlbDnsName`].OutputValue' --output text
```

---

## How a deploy works

The workflow runs the following steps in order:

1. **Detect live color** — reads the ALB listener's default action and identifies which TG is live (blue or green). The other color is the deploy target.
2. **Package + upload** — `tar.gz`s the repo (excluding `.git`, `.venv`, etc.) and uploads it to `s3://deployctrl-code-<account-id>/deployctrl-<sha>.tar.gz`.
3. **Delete stale target-color stack** — if `deployctrl-app-<new-color>` already exists (from two deploys ago), delete it cleanly so the create step starts fresh.
4. **Create new color stack** — `bg-app.yml` launches a single-instance ASG. The instance bootstraps Django + Nginx + gunicorn, pointing `MONGO_URI` at the persistent Mongo box. CFN waits for `cfn-signal` from the instance.
5. **Wait for healthy targets** — polls `describe-target-health` on the new TG until at least one target reports `healthy`.
6. **Swap listener** — `aws elbv2 modify-listener` flips the default action to the new TG. Traffic moves instantly.
7. **Smoke test** — `curl`s the ALB DNS and accepts 200/301/302.

The old color's stack is **not** deleted. It stays warm until the next deploy
overwrites it, giving you a one-click rollback (see below).

---

## Rollback

Two options, in order of speed:

### Instant rollback (old stack still running)

The old color is still healthy in its target group until the next deploy
nukes it. Flip the listener back manually:

```bash
LISTENER_ARN=$(aws cloudformation list-exports \
  --query "Exports[?Name=='deployctrl-persistent-listener-arn'].Value" --output text)

# Whichever TG was the previous "live":
OLD_TG=$(aws cloudformation list-exports \
  --query "Exports[?Name=='deployctrl-persistent-blue-tg'].Value" --output text)
# or 'green-tg' depending on which was live before

aws elbv2 modify-listener \
  --listener-arn "$LISTENER_ARN" \
  --default-actions "Type=forward,TargetGroupArn=$OLD_TG"
```

Or re-run the workflow with `force_color` set to the previous color.

### Full redeploy

Re-run the workflow on the previous Git SHA: **Actions → Deploy Blue/Green → Run workflow** from the older commit/ref.

---

## Operations

### View live color

```bash
LISTENER_ARN=$(aws cloudformation list-exports \
  --query "Exports[?Name=='deployctrl-persistent-listener-arn'].Value" --output text)
BLUE_TG=$(aws cloudformation list-exports \
  --query "Exports[?Name=='deployctrl-persistent-blue-tg'].Value" --output text)
CURRENT_TG=$(aws elbv2 describe-listeners --listener-arns "$LISTENER_ARN" \
  --query 'Listeners[0].DefaultActions[0].TargetGroupArn' --output text)
[ "$CURRENT_TG" = "$BLUE_TG" ] && echo blue || echo green
```

### SSH into an app instance

The app SG allows port 22 from `SSHLocation` (set when you deployed the persistent stack). Find the instance via tag:

```bash
aws ec2 describe-instances \
  --filters "Name=tag:Color,Values=green" "Name=instance-state-name,Values=running" \
  --query 'Reservations[].Instances[].PublicIpAddress' --output text
```

Or use SSM Session Manager (no key needed — the role has `AmazonSSMManagedInstanceCore`):

```bash
aws ssm start-session --target <instance-id>
```

### Tearing it all down

```bash
aws cloudformation delete-stack --stack-name deployctrl-app-blue   2>/dev/null
aws cloudformation delete-stack --stack-name deployctrl-app-green  2>/dev/null
aws cloudformation wait stack-delete-complete --stack-name deployctrl-app-blue   2>/dev/null
aws cloudformation wait stack-delete-complete --stack-name deployctrl-app-green  2>/dev/null
aws cloudformation delete-stack --stack-name deployctrl-persistent
```

> The persistent stack delete will fail if anything still references the exports — delete the app stacks first.

---

## Cost note

Steady state runs:

- 1× ALB (~\$16/mo)
- 1× MongoDB EC2 (t3.small ~\$15/mo) + ~50 GB gp3 (~\$4/mo)
- 1× live app EC2 (t3.small ~\$15/mo)
- 1× idle "old color" app EC2 during the rollback window (~\$15/mo until the next deploy)

To save money: change the workflow's last steps to `delete-stack` the old color
immediately after the smoke test passes — you lose the instant-rollback window
but cut the idle instance.

---

## Limitations / known caveats

- **Single MongoDB instance** is a SPOF and lives on the persistent stack. If you need HA, migrate to MongoDB Atlas or DocumentDB and point `MONGO_URI` at the managed endpoint — the app stack already reads `MONGO_URI` from `/opt/deployctrl/.env`.
- **No HTTPS in the listener.** Add an `:443` listener + ACM certificate by extending `bg-persistent.yml`. The app SG already accepts port 80 from the ALB, so the ALB itself terminates TLS — no changes to the app stack needed.
- **Schema migrations** run on every fresh instance via `collectstatic` only — there are no Django migrations because the app uses MongoEngine. If you add any future migration step, be aware both colors connect to the **same** Mongo DB during the swap window: forward-compatible schema changes only.
- **`seed_data` is gated** behind the `RUN_SEED_DATA` workflow variable and defaults to `false`. Set it to `true` for the very first deploy, then flip it back, otherwise demo accounts get re-seeded on every release.

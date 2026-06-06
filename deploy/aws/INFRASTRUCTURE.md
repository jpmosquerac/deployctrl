# DeployCtrl — AWS Infrastructure Description

> This document describes the **static topology** of the production deployment.
> Use it as input to generate an architecture diagram (suggested type:
> AWS architecture diagram, layered: Internet → VPC → AZs → resources).

---

## High-level summary

DeployCtrl runs on AWS in a single VPC behind an Application Load Balancer.
A **Blue/Green** strategy is used: two parallel single-instance app stacks
(blue and green) sit behind their own target groups. At any moment one
color receives 100% of traffic; the other is either absent (first deploy)
or a warm rollback target (subsequent deploys). A separate persistent
MongoDB EC2 instance is shared by both colors.

The system has three logical layers:

1. **Edge / public** — Internet → ALB (HTTP :80, internet-facing)
2. **Application** — two single-instance Auto Scaling Groups (one per color), each behind its own ALB target group
3. **Data** — a single long-lived MongoDB EC2 instance, reachable only from app instances

---

## Account and region

| Item | Value |
|---|---|
| AWS account | 231112207161 |
| Region | us-east-1 |
| VPC | `vpc-0a50f29999343bac4` (default VPC) |
| Availability Zones in use | us-east-1a, us-east-1b, us-east-1c |

---

## Resource inventory by CloudFormation stack

### Stack 1 — `deployctrl-persistent` (one-time, long-lived)

**Purpose:** holds the resources that survive across blue/green swaps.

| Resource | Type | Notes |
|---|---|---|
| `ApplicationLoadBalancer` | AWS::ElasticLoadBalancingV2::LoadBalancer | Internet-facing, type `application`, attached to 3 public subnets (1a/1b/1c). DNS: `deployctrl-persistent-alb-<id>.us-east-1.elb.amazonaws.com` |
| `BlueTargetGroup` | AWS::ElasticLoadBalancingV2::TargetGroup | HTTP :80, target type `instance`, health check `GET /`, matcher `200,301,302`, deregistration delay 30s |
| `GreenTargetGroup` | AWS::ElasticLoadBalancingV2::TargetGroup | Same config as blue |
| `HttpListener` | AWS::ElasticLoadBalancingV2::Listener | Port 80, HTTP. Default action forwards to whichever color is currently live. On first create, defaults to BlueTargetGroup. |
| `AlbSecurityGroup` | AWS::EC2::SecurityGroup | Ingress: TCP 80 + 443 from `0.0.0.0/0`. Attached to ALB. |
| `AppSecurityGroup` | AWS::EC2::SecurityGroup | Ingress: TCP 80 from AlbSecurityGroup, TCP 22 from `SSHLocation` CIDR. Attached to all app instances. |
| `MongoSecurityGroup` | AWS::EC2::SecurityGroup | Ingress: TCP 27017 from AppSecurityGroup, TCP 22 from `SSHLocation` CIDR. Attached to Mongo instance. |
| `MongoRole` | AWS::IAM::Role | Trust: `ec2.amazonaws.com`. Managed policies: `AmazonSSMManagedInstanceCore`, `CloudWatchAgentServerPolicy`. |
| `MongoInstanceProfile` | AWS::IAM::InstanceProfile | Wraps MongoRole. Attached to Mongo instance. |
| `MongoInstance` | AWS::EC2::Instance | t3.small, Amazon Linux 2023, EBS gp3 10 GB encrypted, in subnet `us-east-1a`. Runs MongoDB 8.0 listening on `0.0.0.0:27017`. Private IP only consumed by app instances. |

**Stack outputs (CloudFormation exports consumed by app stacks):**

| Export name (suffix) | Value |
|---|---|
| `-alb-dns` | DNS hostname of the ALB |
| `-alb-arn` | ARN of the ALB |
| `-listener-arn` | ARN of the HTTP listener |
| `-blue-tg` | ARN of the blue target group |
| `-green-tg` | ARN of the green target group |
| `-app-sg` | ID of the app security group |
| `-mongo-ip` | Private IP of the MongoDB instance |
| `-mongo-id` | EC2 instance ID of the MongoDB instance |

### Stack 2 — `deployctrl-app-blue` (per-deploy, replaced each cycle)

**Purpose:** runs the live (or warm-rollback) blue version of the app.

| Resource | Type | Notes |
|---|---|---|
| `AppRole` | AWS::IAM::Role | Trust: `ec2.amazonaws.com`. Managed: SSM + CloudWatch Agent. Inline policy: `s3:GetObject` on `s3://deployctrl-code-231112207161/deployctrl-<sha>.tar.gz`. |
| `AppInstanceProfile` | AWS::IAM::InstanceProfile | Wraps AppRole. |
| `AppLaunchTemplate` | AWS::EC2::LaunchTemplate | Describes the bootable image: AL2023 x86_64, t3.small, encrypted gp3 20 GB, AppInstanceProfile, AppSecurityGroup (imported from persistent stack), UserData script that fully provisions the app. |
| `AppAutoScalingGroup` | AWS::AutoScaling::AutoScalingGroup | Size 1/1/1, `HealthCheckType=ELB`, registered to BlueTargetGroup (imported), in one ALB-enabled subnet. Sends `cfn-signal` on bootstrap success. |

### Stack 3 — `deployctrl-app-green` (per-deploy, replaced each cycle)

Identical structure to `deployctrl-app-blue`; registers with `GreenTargetGroup` instead.

---

## Network topology

- **VPC** `vpc-0a50f29999343bac4` (default VPC, 172.31.0.0/16)
- **3 public subnets** in `us-east-1a`, `us-east-1b`, `us-east-1c` attached to the ALB
- **Mongo instance subnet:** `us-east-1a` (first of the ALB's subnets)
- **App instance subnet:** picked at deploy time from the ALB's enabled AZs

All resources are in public subnets. App and Mongo instances have public IPs but are only reachable on ports the security groups allow.

---

## Security group ingress matrix

| Security group | Port(s) | Source | Purpose |
|---|---|---|---|
| `AlbSecurityGroup` | 80, 443 | `0.0.0.0/0` | Internet traffic to ALB |
| `AppSecurityGroup` | 80 | `AlbSecurityGroup` | ALB → gunicorn-behind-nginx |
| `AppSecurityGroup` | 22 | `SSHLocation` CIDR | Operator SSH |
| `MongoSecurityGroup` | 27017 | `AppSecurityGroup` | App → MongoDB |
| `MongoSecurityGroup` | 22 | `SSHLocation` CIDR | Operator SSH |

**Egress:** all security groups allow all outbound traffic (default).

---

## IAM identities

| Identity | Trust / type | Permissions |
|---|---|---|
| `deployctrl-ci` (IAM user) | Static access keys, used by GitHub Actions runner | Broad: CloudFormation, EC2, AutoScaling, ELBv2, IAM, S3, SSM (GetParameter), STS (GetCallerIdentity) |
| `deployctrl-persistent-mongo-role` | EC2 service role | SSM Session Manager, CloudWatch Agent |
| `deployctrl-app-<color>-role` | EC2 service role (per color stack) | SSM Session Manager, CloudWatch Agent, `s3:GetObject` scoped to the release tarball |

---

## On-instance software

### App instances (blue and green)

- OS: Amazon Linux 2023, kernel x86_64
- Python 3.11 (system) + venv at `/opt/deployctrl/.venv`
- Terraform 1.10.5 in `/usr/local/bin` (used by the app at runtime to provision tenant infra)
- nginx on `:80` (proxies to gunicorn, serves `/static/`)
- gunicorn on `127.0.0.1:8000` (systemd unit `deployctrl.service`)
- App code in `/opt/deployctrl`, owned by user `deployctrl`
- Env file `/opt/deployctrl/.env` with `MONGO_URI=mongodb://<mongo-private-ip>:27017/deployctrl`
- Log files in `/var/log/deployctrl/`

### MongoDB instance

- OS: Amazon Linux 2023
- MongoDB 8.0 from the official repo, listening on `0.0.0.0:27017`
- No authentication (relies on the security group to gate access)
- Single replica set member (no HA)

---

## External systems

| System | Role | Connection |
|---|---|---|
| GitHub repository `jpmosquerac/deployctrl` | Source of truth for application code and CloudFormation templates | Cloned by GitHub Actions runner on each deploy |
| GitHub Actions | CI/CD runner | Uses `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` from repo secrets to talk to AWS APIs |
| GitHub Pages (`jpmosquerac.github.io/deployctrl`) | Public landing page; "Live Demo" button links to the ALB DNS | Static, no live integration |
| Amazon S3 bucket `deployctrl-code-231112207161` | Holds versioned release tarballs (`deployctrl-<commit-sha>.tar.gz`) | Written by GitHub Actions runner; read by app instances during UserData |
| (Runtime) GitHub repository for GitOps | Stores Terraform files DeployCtrl generates for tenant requests; cloned by the app | Configured at runtime via the dashboard; not part of this deployment stack |

---

## Data and traffic flow (steady state)

1. End user requests `http://<alb-dns>/` from the internet
2. ALB on port 80 forwards to the live color's target group
3. The target group routes to the single registered EC2 instance on port 80
4. nginx on the instance serves `/static/` directly and proxies the rest to gunicorn on `127.0.0.1:8000`
5. gunicorn runs the Django WSGI app
6. Django reads/writes data over TCP 27017 to the MongoDB instance at `172.31.0.93`

---

## Resource relationships (for the diagram)

Use arrows for these directional dependencies:

- Internet → ALB
- ALB → BlueTargetGroup (when blue is live)
- ALB → GreenTargetGroup (when green is live)
- BlueTargetGroup → app-blue ASG → app-blue EC2
- GreenTargetGroup → app-green ASG → app-green EC2
- app-blue EC2 → MongoDB EC2 (TCP 27017)
- app-green EC2 → MongoDB EC2 (TCP 27017)
- app-blue/green EC2 → S3 (bootstrap GetObject)
- GitHub Actions runner → AWS APIs (CloudFormation, S3, ELBv2)

Group the boxes by:

- **Internet** (outside the VPC border)
- **VPC** (containing everything else)
  - **AZ us-east-1a** — Mongo EC2
  - **AZ us-east-1b/1c** — possible app EC2 placement
  - **Spans all 3 AZs** — ALB
- **External systems** (outside AWS): GitHub repo, GitHub Actions, GitHub Pages, S3 bucket (S3 is AWS but service-level, draw outside the VPC border)

---

## Conventions to use in the diagram

- AWS-style icons for ALB, EC2, S3, IAM
- Distinct colors for the two color stacks (blue and green — match the names)
- Dashed line between the inactive color's stack and its target group to indicate "warm but not live"
- Solid line from the listener to the currently-live target group (with a small "100%" label)
- Annotate the listener's default action to make the swap mechanism obvious

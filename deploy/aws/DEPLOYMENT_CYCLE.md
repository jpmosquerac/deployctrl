# DeployCtrl — Blue/Green Deployment Cycle

> This document describes the **temporal flow** of a single deployment.
> Use it as input to generate a deployment diagram. Two diagram types
> work well: a **sequence diagram** (actors over time) or a **flowchart**
> (steps with decision branches). The sequence form is recommended.

---

## Actors

The diagram should swim-lane these five participants:

1. **Developer / Operator** — pushes to `main` or clicks "Run workflow"
2. **GitHub Actions runner** — executes the `deploy-bg.yml` workflow
3. **AWS CloudFormation** — creates/deletes the per-color app stack
4. **AWS ELBv2 (ALB)** — listener, target groups, health checks
5. **EC2 instance** — the new app instance launched by CloudFormation

A sixth participant, **MongoDB EC2**, exists outside the cycle (it's persistent and shared). Show it as a passive box that the new instance connects to during bootstrap.

---

## Trigger

The deployment starts in one of two ways. Both reach the same runner:

| Trigger | What |
|---|---|
| `git push` to branch `main` | Any commit on the default branch |
| Manual `workflow_dispatch` | Operator clicks "Run workflow" in the GitHub Actions UI; optionally supplies `force_color=blue` or `force_color=green` to override auto-pick |

A `concurrency` guard prevents two deploys from overlapping — a second push while one is in flight queues until the first finishes.

---

## Phase 1 — Preparation (runner-only, ~30 seconds)

1. **Checkout** the repository at the triggering commit (SHA used as part of the release tarball key).
2. **Configure AWS credentials** — reads `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` from GitHub secrets; calls `sts:GetCallerIdentity` implicitly to verify.
3. **Resolve persistent-stack exports** — lists CloudFormation exports and pulls: listener ARN, blue/green TG ARNs, ALB DNS, ALB ARN. If any are missing, abort with a "deploy the persistent stack first" error.

---

## Phase 2 — Pick the inactive color (decision point)

4. **Determine live color** — `aws elbv2 describe-listeners` on the persistent listener.
   - If `DefaultActions[0].TargetGroupArn` is set (simple forward), use it.
   - Else, look at `ForwardConfig.TargetGroups` (weighted forward, intermediate state) and pick the TG with the higher weight.
5. **Decision branch:**
   - If live is **blue**, set `NEW = green`.
   - If live is **green**, set `NEW = blue`.
   - If the operator supplied `force_color` via manual dispatch, that overrides the auto-pick.

---

## Phase 3 — Package and upload (runner ↔ S3, ~10–30 s)

6. **Package application** — tars the repo into `/tmp/deployctrl.tar.gz`, excluding `.git`, `.github`, `.venv`, `__pycache__`, `.env`, `staticfiles`, etc.
7. **Upload code to S3** — creates the bucket `deployctrl-code-<account-id>` on first run (private + versioning enabled), then uploads the tarball as `deployctrl-<commit-sha>.tar.gz`.

---

## Phase 4 — Pick a placement subnet

8. **Pick a subnet** — queries the ALB's `AvailabilityZones[].SubnetId` and uses the first one returned. This guarantees the new instance lands in an AZ the ALB has enabled (a previous version of this step picked an arbitrary VPC subnet and failed when it didn't match the ALB's AZ set).

---

## Phase 5 — Clean slate for the target color

9. **Delete stale stack of the target color** — if `deployctrl-app-<NEW>` already exists (it was the warm-rollback target from the previous deploy), delete it and wait for `stack-delete-complete`. This guarantees a clean create.

---

## Phase 6 — Create the new color stack (CFN, ~5–10 min)

10. **Create stack** — `aws cloudformation create-stack` with template `deploy/aws/bg-app.yml`. CloudFormation creates, in order:
    1. The per-stack IAM role (`AppRole`) and instance profile.
    2. The launch template (`AppLaunchTemplate`) containing the UserData bootstrap script.
    3. The Auto Scaling Group (`AppAutoScalingGroup`), size 1/1/1, registered to the NEW color's target group via the launch template `TargetGroupARNs` reference.
11. **ASG launches one EC2 instance** in the chosen subnet.
12. **UserData script runs** on the instance (~5–8 min):
    1. Installs `python3.11`, `nginx`, `git`, `unzip` via `dnf`.
    2. Downloads Terraform 1.10.5 (used by the app at runtime).
    3. Creates the `deployctrl` system user.
    4. Downloads `s3://deployctrl-code-<account>/<release-key>` and extracts to `/opt/deployctrl/`.
    5. Creates a venv and `pip install -r requirements.txt`.
    6. Writes `/opt/deployctrl/.env` with `MONGO_URI=mongodb://<persistent-mongo-private-ip>:27017/deployctrl` and the Django secret.
    7. Runs `manage.py collectstatic` (and optionally `seed_data` when `RUN_SEED_DATA=true`).
    8. Installs and starts a systemd unit for gunicorn on `127.0.0.1:8000`.
    9. Drops the nginx reverse-proxy config and starts nginx on `:80`.
    10. Sends `cfn-signal -e 0` to mark the resource creation successful.
13. **CloudFormation waits** for the cfn-signal (up to 20 min); if no signal arrives in time, the stack rolls back and the workflow fails.

---

## Phase 7 — Hook the new TG into the listener for health checks (~10 s)

14. **Attach new TG with weight 0** — `aws elbv2 modify-listener` replaces the listener's default action with a **weighted forward** referencing both TGs:
    - Old color: weight **100** (still receives all traffic)
    - New color: weight **0** (no traffic yet, but ELB will now run health probes on it)
    
    This step exists to break a chicken-and-egg: an ALB does **not** health-check a target group until a listener references it. Before this change, the new TG sat in `unused` state and the next step timed out.

---

## Phase 8 — Wait for new TG to be healthy (~30 s – 2 min)

15. **Poll target health** — every 10 s, calls `aws elbv2 describe-target-health`. Considers the TG healthy when at least one target exists and all targets report state `healthy`. Times out at 10 min.

---

## Phase 9 — The actual swap (~1 s)

16. **Flip the listener** — `aws elbv2 modify-listener` replaces the weighted forward with a single forward to the NEW color's TG.
    - Old color: now removed from the listener (still running, target group remains, but receives no traffic)
    - New color: receives **100%** of traffic
    
    The swap is atomic from the client's perspective; new connections route to the new color the moment the API call returns.

---

## Phase 10 — Smoke test (~5–30 s)

17. **Smoke-test the ALB** — `curl http://<alb-dns>/` up to 12 times with 5 s between attempts. Accepts HTTP 200, 301, or 302. If none of the attempts pass, the workflow fails with a hint to roll back manually.

---

## Phase 11 — Summary (instant)

18. **Write a deployment summary** to the GitHub Actions UI: previous live color, new live color, commit SHA, app URL.

---

## What happens on failure

The workflow has no automated rollback. Failure modes and their consequences:

| Failing step | Consequence | Recovery |
|---|---|---|
| AWS credentials configuration | No AWS state changed | Fix secrets and re-run |
| Stack create / cfn-signal timeout | New color stack rolls back to `ROLLBACK_COMPLETE` (no instance), listener untouched | Re-run; the stale-delete step removes the rolled-back stack first |
| Health-check wait timeout | New color stack exists and is running but ALB never marked it healthy; listener still weighted 100/0 toward old | Investigate via SSM, then either fix and re-deploy, or `modify-listener` back to a simple forward to the old TG |
| Swap step | Listener didn't flip; old color still live | Just re-run the workflow |
| Smoke test | Listener has already been swapped to the new color, but the new color isn't serving healthy responses | **Manual rollback:** `modify-listener` back to the old TG ARN (old stack is still running) |

---

## Rollback (independent of the workflow)

The previous color's stack is **not** torn down by the workflow. It stays warm until the next deploy starts (the "delete stale stack" step removes it before creating the next inactive color).

To roll back instantly during this warm window:

```
aws elbv2 modify-listener
  --listener-arn <listener-arn>
  --default-actions "Type=forward,TargetGroupArn=<old-color-tg-arn>"
```

This is a single API call and completes in under a second.

---

## Steady-state cadence

After two consecutive deploys, the system reaches steady state:

- **Deploy N:** create new-color stack → swap to it → keep old-color stack warm.
- **Deploy N+1:** delete the still-warm stale color → create fresh stack of that color → swap → keep new-other-color warm.

There is always **exactly one** color receiving traffic, and at most **one** other color present as warm rollback.

---

## Diagram hints

For a sequence diagram, draw:

- Time flowing top-to-bottom.
- Phases 1–11 as horizontal bands.
- Color-code the "Phase 7 / weight-0 attach" and "Phase 9 / swap" boxes — those are the two ELB-mutating moments and the most important to highlight.
- The "loop" symbol for Phase 8 (health-check polling).
- A dashed return arrow from the EC2 instance back up to CloudFormation for the `cfn-signal` in Phase 6.
- Annotate Phase 9 with **"atomic — clients see no downtime"**.

For a flowchart, draw:

- Diamond at the "Determine live color" decision (Phase 2).
- Diamond at "Stale stack exists?" (Phase 5).
- Two failure branches off Phase 8 and Phase 10, both pointing to a "Manual rollback" terminal node.

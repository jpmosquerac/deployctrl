"""
Terraform runner — executes `terraform init && terraform apply` for a specific
InfraRequest in a background thread.

Per-run layout on disk (temporary, deleted after run):
    <TERRAFORM_WORK_DIR>/<run-id>/iac/          ← full repo clone
    <TERRAFORM_WORK_DIR>/<run-id>/tf/           ← isolated workspace for this request
        default.tf                              ← filled-in copy of tf_templates/default/main.tf
        main.tf                                 ← copy of <team>/<req-id>/main.tf from repo
        terraform.tfvars                        ← copy of <team>/<req-id>/terraform.tfvars

Full stdout/stderr is stored in the TerraformRun.log field in MongoDB.
A parsed summary (plan/apply line + any errors) is stored in TerraformRun.summary.
"""
import logging
import os
import re
import shutil
import subprocess
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from django.conf import settings


def _work_dir():
    return getattr(settings, 'TERRAFORM_WORK_DIR', '/tmp/deployctrl/workspace')


def _slugify(text):
    return re.sub(r'[^a-z0-9]+', '-', text.lower().strip()).strip('-')


# ── Public API ────────────────────────────────────────────────────────────────

def trigger_destroy(infra_request, actor):
    """
    Create a TerraformRun of type 'destroy' and start execution in a daemon thread.
    Returns the created run immediately (non-blocking), or None if GitOps is not configured.
    On success the runner: destroys infra, deletes the GitHub folder, deletes the
    TerraformState document, and marks the InfraRequest as decommissioned.
    """
    from .models import TerraformRun
    from apps.gitops.models import GitOpsConfig
    from apps.infra_requests.models import InfraRequest

    config = GitOpsConfig.objects(name='default').first()
    if not config or not config.enabled:
        return None

    run = TerraformRun(
        req_id=infra_request.req_id,
        team=infra_request.team,
        run_type=TerraformRun.RUN_TYPE_DESTROY,
        triggered_by=actor,
        owner=config.owner,
        repo=config.repo,
        branch=config.branch or 'main',
    )
    run.save()

    infra_request.status = InfraRequest.STATUS_DECOMMISSIONING
    infra_request.save()

    threading.Thread(
        target=_execute_destroy,
        args=(
            str(run.id),
            str(infra_request.id),
            infra_request.team,
            infra_request.req_id,
            config.owner,
            config.repo,
            config.branch or 'main',
            config.token,
        ),
        daemon=True,
    ).start()

    return run


def trigger_run(infra_request, actor):
    """
    Create a TerraformRun record and start execution in a daemon thread.
    Uses the global GitOps configuration for repo details.
    Returns the created run immediately (non-blocking), or None if GitOps
    is not configured.
    """
    from .models import TerraformRun
    from apps.gitops.models import GitOpsConfig

    config = GitOpsConfig.objects(name='default').first()
    if not config or not config.enabled:
        return None

    run = TerraformRun(
        req_id=infra_request.req_id,
        team=infra_request.team,
        triggered_by=actor,
        owner=config.owner,
        repo=config.repo,
        branch=config.branch or 'main',
    )
    run.save()

    threading.Thread(
        target=_execute,
        args=(
            str(run.id),
            infra_request.team,
            infra_request.req_id,
            config.owner,
            config.repo,
            config.branch or 'main',
            config.token,
        ),
        daemon=True,
    ).start()

    return run


# ── Execution (background thread) ─────────────────────────────────────────────

def _execute(run_id, team_name, req_id, owner, repo, branch, token):
    from .models import TerraformRun
    from apps.audit.utils import log_event

    run = TerraformRun.objects.get(id=run_id)
    run.status     = TerraformRun.STATUS_RUNNING
    run.started_at = datetime.now(timezone.utc)
    run.save()

    team_slug     = _slugify(team_name)
    clone_url     = f'https://oauth2:{token}@github.com/{owner}/{repo}.git'
    run_workspace = os.path.join(_work_dir(), run_id)
    iac_dir       = os.path.join(run_workspace, 'iac')
    tf_dir        = os.path.join(run_workspace, 'tf')

    # In-memory log buffer — flushed to DB after each step
    _buf = []

    def _w(msg=''):
        _buf.append(msg)

    def _flush():
        run.log = '\n'.join(_buf)
        run.save()

    try:
        os.makedirs(run_workspace, exist_ok=True)

        _w('=== DeployCtrl Terraform Run ===')
        _w(f'Team      : {team_name}')
        _w(f'Request   : {req_id}')
        _w(f'Repo      : {owner}/{repo}@{branch}')
        _w(f'Run ID    : {run_id}')
        _w(f'Workspace : {tf_dir}')
        _w(f'Start     : {datetime.now(timezone.utc).isoformat()}')
        _w()
        _flush()

        # ── 1. Clone full repo ───────────────────────────────────────────────
        _w('--- git clone ---')
        r = subprocess.run(
            ['git', 'clone', '--depth=1', f'--branch={branch}', clone_url, iac_dir],
            capture_output=True, text=True, timeout=120,
        )
        _w(r.stdout)
        _w(r.stderr)
        _flush()

        if r.returncode != 0:
            _w(f'\n[ERROR] git clone failed (exit {r.returncode})')
            _flush()
            _finish(run, TerraformRun.STATUS_FAILED, r.returncode,
                    'git clone failed: ' + r.stderr[-600:])
            return

        # ── 2. Copy request files into isolated workspace ────────────────────
        req_folder = os.path.join(iac_dir, team_slug, req_id)
        src_tf     = os.path.join(req_folder, 'main.tf')
        src_tfvars = os.path.join(req_folder, 'terraform.tfvars')

        if not os.path.exists(src_tf):
            msg = f'main.tf not found under {team_slug}/{req_id}/ in repo {owner}/{repo}.'
            _w(f'\n[ERROR] {msg}')
            _flush()
            _finish(run, TerraformRun.STATUS_FAILED, 1, msg)
            return

        os.makedirs(tf_dir, exist_ok=True)
        shutil.copy2(src_tf, os.path.join(tf_dir, 'main.tf'))
        if os.path.exists(src_tfvars):
            shutil.copy2(src_tfvars, os.path.join(tf_dir, 'terraform.tfvars'))
            _w(f'Copied {team_slug}/{req_id}/main.tf and terraform.tfvars')
        else:
            _w(f'Copied {team_slug}/{req_id}/main.tf  (no tfvars found)')

        # ── 2b. Substitute and write default.tf ─────────────────────────────
        base_url    = getattr(settings, 'TF_BACKEND_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
        secret      = getattr(settings, 'TF_STATE_SECRET', '')
        src_default = os.path.join(req_folder, 'default.tf')
        if os.path.exists(src_default):
            with open(src_default) as f:
                default_tpl = f.read()
        else:
            from apps.resources.renderer import EXAMPLES_DIR
            default_tpl = (EXAMPLES_DIR / 'default' / 'main.tf').read_text()
        default_tf = (
            default_tpl
            .replace('{BASE_URL}', base_url)
            .replace('{REQ_ID}',  req_id)
            .replace('{SECRET}',  secret)
        )
        with open(os.path.join(tf_dir, 'default.tf'), 'w') as df:
            df.write(default_tf)
        _w(f'Wrote default.tf (backend → {base_url}/api/terraform/state/{req_id}/)')
        _flush()

        # ── 3. terraform init ────────────────────────────────────────────────
        _w('\n--- terraform init ---')
        r = subprocess.run(
            ['terraform', 'init', '-no-color'],
            cwd=tf_dir, capture_output=True, text=True, timeout=300,
            env=_build_env(),
        )
        _w(r.stdout)
        _w(r.stderr)
        _flush()

        if r.returncode != 0:
            _w(f'\n[ERROR] terraform init failed (exit {r.returncode})')
            _flush()
            _finish(run, TerraformRun.STATUS_FAILED, r.returncode,
                    _parse_summary(r.stdout + r.stderr))
            return

        # ── 4. terraform apply ───────────────────────────────────────────────
        _w('\n--- terraform apply -auto-approve ---')
        _flush()
        r = subprocess.run(
            ['terraform', 'apply', '-auto-approve', '-no-color'],
            cwd=tf_dir, capture_output=True, text=True, timeout=1800,
            env=_build_env(),
        )
        _w(r.stdout)
        _w(r.stderr)

        combined   = r.stdout + r.stderr
        summary    = _parse_summary(combined)
        fin_status = TerraformRun.STATUS_SUCCEEDED if r.returncode == 0 else TerraformRun.STATUS_FAILED

        _w(f'\n=== Finished (exit {r.returncode}) at {datetime.now(timezone.utc).isoformat()} ===')
        _flush()
        _finish(run, fin_status, r.returncode, summary)

        if fin_status == TerraformRun.STATUS_SUCCEEDED:
            from apps.infra_requests.models import InfraRequest
            try:
                if req_id.startswith('REQ-'):
                    infra_req = InfraRequest.objects.get(req_number=int(req_id[4:]))
                else:
                    infra_req = InfraRequest.objects.get(id=req_id)
                infra_req.status = InfraRequest.STATUS_PROVISIONED
                infra_req.save()
                _w(f'Marked {req_id} as provisioned.')
                _flush()
            except Exception as e:
                _w(f'[WARN] Could not mark {req_id} as provisioned: {e}')
                _flush()

        log_event(
            'TERRAFORM_APPLIED' if r.returncode == 0 else 'TERRAFORM_FAILED',
            run.triggered_by,
            'team',
            run.team,
            f'Run {run_id} ({team_name} / {req_id}): {summary[:200]}',
        )

    except Exception as exc:
        try:
            _w(f'\n[EXCEPTION] {exc}')
            _flush()
            run.reload()
            _finish(run, TerraformRun.STATUS_FAILED, 1, f'Unexpected error: {exc}')
        except Exception:
            pass
    finally:
        shutil.rmtree(run_workspace, ignore_errors=True)


def _execute_destroy(run_id, infra_req_db_id, team_name, req_id, owner, repo, branch, token):
    from .models import TerraformRun, TerraformState
    from apps.audit.utils import log_event
    from apps.infra_requests.models import InfraRequest

    run = TerraformRun.objects.get(id=run_id)
    run.status     = TerraformRun.STATUS_RUNNING
    run.started_at = datetime.now(timezone.utc)
    run.save()

    team_slug     = _slugify(team_name)
    clone_url     = f'https://oauth2:{token}@github.com/{owner}/{repo}.git'
    run_workspace = os.path.join(_work_dir(), run_id)
    iac_dir       = os.path.join(run_workspace, 'iac')
    tf_dir        = os.path.join(run_workspace, 'tf')

    _buf = []

    def _w(msg=''):
        _buf.append(msg)

    def _flush():
        run.log = '\n'.join(_buf)
        run.save()

    try:
        os.makedirs(run_workspace, exist_ok=True)

        _w('=== DeployCtrl Terraform Destroy ===')
        _w(f'Team      : {team_name}')
        _w(f'Request   : {req_id}')
        _w(f'Repo      : {owner}/{repo}@{branch}')
        _w(f'Run ID    : {run_id}')
        _w(f'Workspace : {tf_dir}')
        _w(f'Start     : {datetime.now(timezone.utc).isoformat()}')
        _w()
        _flush()

        # ── 1. Clone full repo ───────────────────────────────────────────────
        _w('--- git clone ---')
        r = subprocess.run(
            ['git', 'clone', '--depth=1', f'--branch={branch}', clone_url, iac_dir],
            capture_output=True, text=True, timeout=120,
        )
        _w(r.stdout)
        _w(r.stderr)
        _flush()

        if r.returncode != 0:
            _w(f'\n[ERROR] git clone failed (exit {r.returncode})')
            _flush()
            _finish(run, TerraformRun.STATUS_FAILED, r.returncode, 'git clone failed: ' + r.stderr[-600:])
            _mark_request(infra_req_db_id, req_id, InfraRequest.STATUS_PROVISIONED)
            return

        # ── 2. Copy request files into isolated workspace ────────────────────
        req_folder = os.path.join(iac_dir, team_slug, req_id)
        src_tf     = os.path.join(req_folder, 'main.tf')
        src_tfvars = os.path.join(req_folder, 'terraform.tfvars')

        if not os.path.exists(src_tf):
            msg = f'main.tf not found under {team_slug}/{req_id}/ — cannot destroy.'
            _w(f'\n[ERROR] {msg}')
            _flush()
            _finish(run, TerraformRun.STATUS_FAILED, 1, msg)
            _mark_request(infra_req_db_id, req_id, InfraRequest.STATUS_PROVISIONED)
            return

        os.makedirs(tf_dir, exist_ok=True)
        shutil.copy2(src_tf, os.path.join(tf_dir, 'main.tf'))
        if os.path.exists(src_tfvars):
            shutil.copy2(src_tfvars, os.path.join(tf_dir, 'terraform.tfvars'))

        # ── 2b. Write default.tf ─────────────────────────────────────────────
        base_url    = getattr(settings, 'TF_BACKEND_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
        secret      = getattr(settings, 'TF_STATE_SECRET', '')
        src_default = os.path.join(req_folder, 'default.tf')
        if os.path.exists(src_default):
            with open(src_default) as f:
                default_tpl = f.read()
        else:
            from apps.resources.renderer import EXAMPLES_DIR
            default_tpl = (EXAMPLES_DIR / 'default' / 'main.tf').read_text()
        default_tf = (
            default_tpl
            .replace('{BASE_URL}', base_url)
            .replace('{REQ_ID}',  req_id)
            .replace('{SECRET}',  secret)
        )
        with open(os.path.join(tf_dir, 'default.tf'), 'w') as df:
            df.write(default_tf)
        _w('Workspace prepared for destroy.')
        _flush()

        # ── 3. terraform init ────────────────────────────────────────────────
        _w('\n--- terraform init ---')
        r = subprocess.run(
            ['terraform', 'init', '-no-color'],
            cwd=tf_dir, capture_output=True, text=True, timeout=300,
            env=_build_env(),
        )
        _w(r.stdout)
        _w(r.stderr)
        _flush()

        if r.returncode != 0:
            _w(f'\n[ERROR] terraform init failed (exit {r.returncode})')
            _flush()
            _finish(run, TerraformRun.STATUS_FAILED, r.returncode, _parse_summary(r.stdout + r.stderr))
            _mark_request(infra_req_db_id, req_id, InfraRequest.STATUS_PROVISIONED)
            return

        # ── 4. terraform destroy ─────────────────────────────────────────────
        _w('\n--- terraform destroy -auto-approve ---')
        _flush()
        r = subprocess.run(
            ['terraform', 'destroy', '-auto-approve', '-no-color'],
            cwd=tf_dir, capture_output=True, text=True, timeout=1800,
            env=_build_env(),
        )
        _w(r.stdout)
        _w(r.stderr)

        combined   = r.stdout + r.stderr
        summary    = _parse_summary(combined)
        fin_status = TerraformRun.STATUS_SUCCEEDED if r.returncode == 0 else TerraformRun.STATUS_FAILED

        _w(f'\n=== Finished (exit {r.returncode}) at {datetime.now(timezone.utc).isoformat()} ===')
        _flush()
        _finish(run, fin_status, r.returncode, summary)

        if fin_status == TerraformRun.STATUS_SUCCEEDED:
            # ── 5. Delete folder from GitHub ─────────────────────────────────
            try:
                from apps.resources.gitops_push import delete_from_github
                ok, err = delete_from_github(team_slug, req_id, owner, repo, branch, token)
                if ok:
                    _w('GitHub folder deleted.')
                else:
                    _w(f'[WARN] GitHub folder delete failed: {err}')
                _flush()
            except Exception as ge:
                _w(f'[WARN] GitHub folder delete error: {ge}')
                _flush()

            # ── 6. Delete TerraformState ─────────────────────────────────────
            try:
                TerraformState.objects(req_id=req_id).delete()
                _w('Terraform state deleted from database.')
                _flush()
            except Exception as se:
                _w(f'[WARN] State delete failed: {se}')
                _flush()

            # ── 7. Mark request decommissioned ───────────────────────────────
            _mark_request(infra_req_db_id, req_id, InfraRequest.STATUS_DECOMMISSIONED)
        else:
            # Destroy failed — revert request status to provisioned
            _mark_request(infra_req_db_id, req_id, InfraRequest.STATUS_PROVISIONED)

        log_event(
            'TERRAFORM_DESTROYED' if r.returncode == 0 else 'TERRAFORM_DESTROY_FAILED',
            run.triggered_by,
            'team',
            run.team,
            f'Destroy run {run_id} ({team_name} / {req_id}): {summary[:200]}',
        )

    except Exception as exc:
        try:
            _w(f'\n[EXCEPTION] {exc}')
            _flush()
            run.reload()
            _finish(run, TerraformRun.STATUS_FAILED, 1, f'Unexpected error: {exc}')
            _mark_request(infra_req_db_id, req_id, InfraRequest.STATUS_PROVISIONED)
        except Exception:
            pass
    finally:
        shutil.rmtree(run_workspace, ignore_errors=True)


def _mark_request(infra_req_db_id, req_id, new_status):
    from apps.infra_requests.models import InfraRequest
    try:
        infra_req = InfraRequest.objects.get(id=infra_req_db_id)
        infra_req.status = new_status
        infra_req.save()
    except Exception as e:
        logger.error('_mark_request failed for %s → %s: %s', req_id, new_status, e)


def _finish(run, status, exit_code, summary):
    run.status      = status
    run.exit_code   = exit_code
    run.summary     = summary[:2000]
    run.finished_at = datetime.now(timezone.utc)
    run.save()


def _build_env():
    """Inherit the process environment so AWS credentials flow through."""
    return os.environ.copy()


def _parse_summary(output):
    """
    Extract the most actionable lines from terraform output:
      - Apply complete / No changes / Plan lines
      - Error lines
    """
    summary = []
    seen = set()

    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped in seen:
            continue

        if re.search(r'Apply complete!', stripped):
            summary.insert(0, stripped)
            seen.add(stripped)
        elif re.search(r'^Plan:', stripped):
            summary.append(stripped)
            seen.add(stripped)
        elif re.search(r'No changes\.', stripped):
            summary.append(stripped)
            seen.add(stripped)
        elif re.search(r'(^Error|Error:)', stripped):
            summary.append(stripped)
            seen.add(stripped)

    if summary:
        return '\n'.join(summary[:6])

    fallback = [
        l.strip() for l in output.splitlines()
        if l.strip() and not l.startswith('│') and not l.startswith('╷')
    ]
    return '\n'.join(fallback[-5:]) if fallback else 'No output captured.'

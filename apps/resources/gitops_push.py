"""
Pushes rendered Terraform files to the configured GitHub repository via the
GitHub Contents API.

Directory layout inside the repo:
    <team-slug>/<request-id>/main.tf
    <team-slug>/<request-id>/terraform.tfvars
"""
import base64
import json
import re
import urllib.request
import urllib.error

from django.conf import settings

from pathlib import Path

from apps.gitops.models import GitOpsConfig

EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / 'tf_templates'


# ── Helpers ───────────────────────────────────────────────────────────────────

def _slugify(text):
    return re.sub(r'[^a-z0-9]+', '-', text.lower().strip()).strip('-')


def _api_call(method, url, token, payload=None):
    """
    Make a JSON request to the GitHub API.
    Returns (response_dict_or_None, error_str_or_None).
    """
    headers = {
        'Accept': 'application/vnd.github+json',
        'Authorization': f'Bearer {token}',
        'X-GitHub-Api-Version': '2022-11-28',
        'Content-Type': 'application/json',
    }
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read()), None
    except urllib.error.HTTPError as exc:
        return None, f'GitHub {exc.code}: {exc.read().decode()}'
    except Exception as exc:
        return None, str(exc)


def _existing_sha(api_base, owner, repo, branch, path, token):
    """Return the blob SHA of an existing file, or None if it does not exist."""
    url = f'{api_base}/repos/{owner}/{repo}/contents/{path}?ref={branch}'
    result, _ = _api_call('GET', url, token)
    return result.get('sha') if result else None


# ── Public API ────────────────────────────────────────────────────────────────

def push_to_github(infra_request, tf_content, tfvars_content, tf_filename):
    """
    Push rendered Terraform files to the GitOps repository.

    Returns:
        (True,  {'github_url': str, 'paths': [str, ...]})
        (False, error_message_str)
    """
    config = GitOpsConfig.objects(name='default').first()
    if not config or not config.enabled:
        return False, 'GitOps is not enabled.'

    api_base = getattr(settings, 'GITHUB_API_BASE', 'https://api.github.com')
    owner  = config.owner
    repo   = config.repo
    branch = config.branch
    token  = config.token

    if not owner or not repo or not token:
        return False, 'GitOps configuration is incomplete (owner/repo/token missing).'

    team_slug  = _slugify(infra_request.team or 'default')
    req_id     = infra_request.req_id

    folder = f'{team_slug}/{req_id}'

    default_tf_content = (EXAMPLES_DIR / 'default' / 'main.tf').read_text()

    # Files to push: default config, module, variables
    files = [
        (
            f'{folder}/default.tf',
            default_tf_content,
            f'deployctrl: add {req_id}/default.tf for team {team_slug}',
        ),
    ]
    if tf_content:
        files.append((
            f'{folder}/main.tf',
            tf_content,
            f'deployctrl: add {req_id}/main.tf for team {team_slug}',
        ))
    files.append((
        f'{folder}/terraform.tfvars',
        tfvars_content,
        f'deployctrl: add {req_id}/terraform.tfvars for team {team_slug}',
    ))

    pushed_paths = []
    for path, content, commit_msg in files:
        sha = _existing_sha(api_base, owner, repo, branch, path, token)

        payload = {
            'message': commit_msg,
            'content': base64.b64encode(content.encode()).decode(),
            'branch': branch,
        }
        if sha:
            payload['sha'] = sha  # required when updating an existing file

        url = f'{api_base}/repos/{owner}/{repo}/contents/{path}'
        result, err = _api_call('PUT', url, token, payload)
        if err:
            return False, f'Failed to push {path!r}: {err}'
        pushed_paths.append(path)

    github_url = f'https://github.com/{owner}/{repo}/tree/{branch}/{folder}'
    return True, {'github_url': github_url, 'paths': pushed_paths}


def delete_from_github(team_slug, req_id, owner, repo, branch, token):
    """
    Delete all files in <team_slug>/<req_id>/ from the GitOps repository.

    Returns:
        (True,  None)
        (False, error_message_str)
    """
    api_base = getattr(settings, 'GITHUB_API_BASE', 'https://api.github.com')
    folder   = f'{team_slug}/{req_id}'

    # Fetch tree for the folder to discover all files
    url   = f'{api_base}/repos/{owner}/{repo}/contents/{folder}?ref={branch}'
    items, err = _api_call('GET', url, token)
    if err:
        # 404 means folder already gone — treat as success
        if '404' in err:
            return True, None
        return False, f'Could not list folder {folder!r}: {err}'

    if not isinstance(items, list):
        return False, f'Unexpected response listing {folder!r}'

    for item in items:
        if item.get('type') != 'file':
            continue
        path = item['path']
        sha  = item.get('sha')
        if not sha:
            continue
        del_url = f'{api_base}/repos/{owner}/{repo}/contents/{path}'
        _, del_err = _api_call('DELETE', del_url, token, {
            'message': f'deployctrl: decommission {req_id} — remove {path}',
            'sha':     sha,
            'branch':  branch,
        })
        if del_err:
            return False, f'Failed to delete {path!r}: {del_err}'

    return True, None

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from mongoengine.errors import DoesNotExist, ValidationError as MEValidationError

from django.http import HttpResponse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.authentication import MongoJWTAuthentication
from apps.accounts.rbac import IsMongoAuthenticated
from apps.audit.utils import log_event
from apps.resources.renderer import render_resource
from apps.resources.gitops_push import push_to_github
from apps.teams.models import Team
from .models import InfraRequest, RequestCounter
from .serializers import (
    InfraRequestCreateSerializer,
    InfraRequestPatchSerializer,
    InfraRequestSerializer,
)

EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / 'tf_templates'


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_by_req_id(pk, qs=None):
    """Look up an InfraRequest by REQ-NNNN identifier."""
    if qs is None:
        qs = InfraRequest.objects
    try:
        return qs.get(req_number=int(pk.replace('REQ-', '')))
    except (DoesNotExist, MEValidationError, ValueError):
        return None


def _provision_resource(infra_req):
    """
    Render the Terraform module for infra_req and either push it to GitHub
    (if GitOps is enabled) or store it locally for download.

    Saves the updated infra_req in place.
    """
    try:
        tf_content, tfvars_content, tf_filename = render_resource(infra_req)
    except ValueError as exc:
        log_event('RESOURCE_ERROR', 'System', 'request', infra_req.req_id,
                  f'Render failed: {exc}')
        return

    from apps.gitops.models import GitOpsConfig
    config = GitOpsConfig.objects(name='default').first()

    if config and config.enabled:
        ok, result = push_to_github(infra_req, tf_content, tfvars_content, tf_filename)
        if ok:
            infra_req.resource_rendered    = True
            infra_req.resource_tf_filename = f'{infra_req.req_id}.tf'
            infra_req.resource_tfvars      = tfvars_content
            infra_req.resource_github_url  = result['github_url']
            infra_req.save()
            log_event('RESOURCE_PUSHED', 'System', 'request', infra_req.req_id,
                      f'Pushed to {result["github_url"]}')

            from apps.terraform.runner import trigger_run
            run = trigger_run(infra_req, 'System')
            if run:
                infra_req.terraform_run_id = str(run.id)
                infra_req.save()
        else:
            log_event('RESOURCE_ERROR', 'System', 'request', infra_req.req_id,
                      f'GitHub push failed: {result}')
    else:
        infra_req.resource_rendered    = True
        infra_req.resource_tf_filename = tf_filename
        infra_req.resource_tfvars      = tfvars_content
        infra_req.resource_github_url  = ''
        infra_req.save()
        log_event('RESOURCE_RENDERED', 'System', 'request', infra_req.req_id,
                  f'Resource ready for download ({tf_filename})')


# ── Views ─────────────────────────────────────────────────────────────────────

class RequestListView(APIView):
    authentication_classes = [MongoJWTAuthentication]
    permission_classes = [IsMongoAuthenticated]

    def get(self, request):
        qs = InfraRequest.objects.order_by('-created_at')
        if not request.user.has_permission('view_requests_all'):
            qs = qs.filter(mongo_user_id=request.user.id_str)
        return Response(InfraRequestSerializer(list(qs), many=True).data)

    def post(self, request):
        if not request.user.has_permission('create_request'):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        serializer = InfraRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        team = Team.objects(name=request.user.team).first()
        threshold = team.approval_threshold if team else 100.0
        req_status = (
            InfraRequest.STATUS_PENDING
            if d['cost'] > threshold
            else InfraRequest.STATUS_APPROVED
        )

        infra_req = InfraRequest(
            req_number=RequestCounter.next(),
            template_id=d['template_id'],
            mongo_user_id=request.user.id_str,
            user_name=request.user.get_full_name(),
            team=request.user.team,
            status=req_status,
            cost=d['cost'],
            region=d['region'],
            justification=d['justification'],
            parameters=d.get('parameters', {}),
        )
        infra_req.save()

        log_event('REQUEST_CREATED', infra_req.user_name, 'request', infra_req.req_id,
                  f'Requested {infra_req.template_id} in {infra_req.region}')
        if req_status == InfraRequest.STATUS_APPROVED:
            log_event('REQUEST_APPROVED', 'System Policy', 'request', infra_req.req_id,
                      'Auto-approved (cost below threshold)')
            _provision_resource(infra_req)

        return Response(InfraRequestSerializer(infra_req).data, status=status.HTTP_201_CREATED)


class RequestDetailView(APIView):
    authentication_classes = [MongoJWTAuthentication]
    permission_classes = [IsMongoAuthenticated]

    def _get_obj(self, pk, user):
        qs = InfraRequest.objects
        if not user.has_permission('view_requests_all'):
            qs = qs.filter(mongo_user_id=user.id_str)
        return _get_by_req_id(pk, qs)

    def get(self, request, pk):
        obj = self._get_obj(pk, request.user)
        if not obj:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(InfraRequestSerializer(obj).data)

    def patch(self, request, pk):
        has_any = any(
            request.user.has_permission(p)
            for p in ['approve_request', 'reject_request', 'provision_request']
        )
        if not has_any:
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        infra_req = _get_by_req_id(pk)
        if not infra_req:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        new_status = request.data.get('status')
        perm_map = {
            'approved':    'approve_request',
            'rejected':    'reject_request',
            'provisioned': 'provision_request',
        }
        required_perm = perm_map.get(new_status)
        if required_perm and not request.user.has_permission(required_perm):
            return Response(
                {'detail': f'Permission "{required_perm}" required.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = InfraRequestPatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        infra_req.status      = serializer.validated_data['status']
        infra_req.reviewed_by = request.user.get_full_name()
        infra_req.reviewed_at = datetime.now(timezone.utc)
        infra_req.save()

        event_map = {
            'approved':    'REQUEST_APPROVED',
            'rejected':    'REQUEST_REJECTED',
            'provisioned': 'REQUEST_PROVISIONED',
        }
        log_event(
            event_map.get(infra_req.status, 'REQUEST_UPDATED'),
            infra_req.reviewed_by,
            'request', infra_req.req_id,
            f'{infra_req.status.title()} {infra_req.req_id}',
        )

        if infra_req.status == InfraRequest.STATUS_APPROVED:
            _provision_resource(infra_req)

        return Response(InfraRequestSerializer(infra_req).data)


class RequestRetryView(APIView):
    """
    POST /api/requests/<req-id>/retry/
    Re-triggers the Terraform run for an approved request.
    """
    authentication_classes = [MongoJWTAuthentication]
    permission_classes = [IsMongoAuthenticated]

    def post(self, request, pk):
        if not request.user.has_permission('provision_request'):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        infra_req = _get_by_req_id(pk)
        if not infra_req:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if infra_req.status not in (InfraRequest.STATUS_APPROVED, InfraRequest.STATUS_PROVISIONED):
            return Response(
                {'detail': 'Only approved or provisioned requests can be retried.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from apps.terraform.runner import trigger_run
        run = trigger_run(infra_req, request.user.get_full_name())
        if not run:
            return Response(
                {'detail': 'GitOps is not configured or disabled.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        infra_req.terraform_run_id = str(run.id)
        infra_req.save()

        log_event(
            'TERRAFORM_RETRIED',
            request.user.get_full_name(),
            'request', infra_req.req_id,
            f'Retry run {run.id} triggered for {infra_req.req_id}',
        )

        from apps.terraform.serializers import TerraformRunSerializer
        return Response(TerraformRunSerializer(run).data, status=status.HTTP_201_CREATED)


class RequestResourceView(APIView):
    """
    GET /api/requests/<req-id>/resource/

    If GitOps is configured and the resource was pushed to GitHub:
        → 200 JSON  { "status": "pushed", "github_url": "..." }

    If no GitOps and the resource is stored locally:
        → 200 ZIP download containing the Terraform module + tfvars

    If the request has not been provisioned yet:
        → 404
    """
    authentication_classes = [MongoJWTAuthentication]
    permission_classes = [IsMongoAuthenticated]

    def get(self, request, pk):
        qs = InfraRequest.objects
        if not request.user.has_permission('view_requests_all'):
            qs = qs.filter(mongo_user_id=request.user.id_str)
        infra_req = _get_by_req_id(pk, qs)
        if not infra_req:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not infra_req.resource_rendered:
            return Response(
                {'detail': 'Resource not yet generated. Request must be approved first.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # ── Pushed to GitHub ──────────────────────────────────────────────────
        if infra_req.resource_github_url:
            return Response({
                'status': 'pushed',
                'github_url': infra_req.resource_github_url,
            })

        # ── Local download ────────────────────────────────────────────────────
        tf_filename = infra_req.resource_tf_filename or 'main.tf'
        tfvars      = infra_req.resource_tfvars

        tf_content = None
        for tf_path in EXAMPLES_DIR.glob(f'*/{tf_filename}'):
            tf_content = tf_path.read_text()
            break

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            if tf_content:
                zf.writestr(tf_filename, tf_content)
            zf.writestr('terraform.tfvars', tfvars)

        zip_name = f'deployctrl-{infra_req.req_id}.zip'
        response = HttpResponse(buf.getvalue(), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="{zip_name}"'
        return response


class RequestDecommissionView(APIView):
    """
    POST /api/requests/<req-id>/decommission/

    Runs `terraform destroy`, deletes the GitHub folder, removes the Terraform
    state from MongoDB, and marks the request as decommissioned.
    """
    authentication_classes = [MongoJWTAuthentication]
    permission_classes = [IsMongoAuthenticated]

    def post(self, request, pk):
        if not request.user.has_permission('decommission_request'):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        infra_req = _get_by_req_id(pk)
        if not infra_req:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if infra_req.status not in (
            InfraRequest.STATUS_PROVISIONED,
            InfraRequest.STATUS_APPROVED,
        ):
            return Response(
                {'detail': 'Only provisioned or approved requests can be decommissioned.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from apps.terraform.runner import trigger_destroy
        run = trigger_destroy(infra_req, request.user.get_full_name())
        if not run:
            return Response(
                {'detail': 'GitOps is not configured or disabled.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        infra_req.terraform_run_id = str(run.id)
        infra_req.save()

        log_event(
            'TERRAFORM_DECOMMISSION_TRIGGERED',
            request.user.get_full_name(),
            'request', infra_req.req_id,
            f'Decommission run {run.id} triggered for {infra_req.req_id}',
        )

        from apps.terraform.serializers import TerraformRunSerializer
        return Response(TerraformRunSerializer(run).data, status=status.HTTP_201_CREATED)


class RequestOutputsView(APIView):
    """
    GET /api/requests/<req-id>/outputs/

    Parses the stored Terraform state for this request and returns the outputs.
    Returns 404 if no state exists, 204 if state exists but has no outputs.
    """
    authentication_classes = [MongoJWTAuthentication]
    permission_classes = [IsMongoAuthenticated]

    def get(self, request, pk):
        if not request.user.has_permission('view_deployments'):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        infra_req = _get_by_req_id(pk)
        if not infra_req:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        from apps.terraform.models import TerraformState
        state_doc = TerraformState.objects(req_id=infra_req.req_id).first()
        if not state_doc or not state_doc.state_json:
            return Response({'detail': 'No state found for this request.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            state = json.loads(state_doc.state_json)
        except (json.JSONDecodeError, ValueError):
            return Response({'detail': 'State is not valid JSON.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        raw_outputs = state.get('outputs', {})
        if not raw_outputs:
            return Response({'outputs': []})

        outputs = [
            {'key': k, 'value': v.get('value', ''), 'type': v.get('type', 'string')}
            for k, v in raw_outputs.items()
        ]
        return Response({'outputs': outputs})

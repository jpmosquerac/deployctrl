from mongoengine.errors import DoesNotExist, ValidationError as MEValidationError

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.authentication import MongoJWTAuthentication
from apps.accounts.rbac import IsMongoAuthenticated
from .models import TerraformRun
from .serializers import TerraformRunSerializer


class TerraformRunListView(APIView):
    authentication_classes = [MongoJWTAuthentication]
    permission_classes = [IsMongoAuthenticated]

    def get(self, request):
        if not request.user.has_permission('view_deployments'):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        team = request.query_params.get('team')
        qs = TerraformRun.objects.order_by('-created_at')
        if team:
            qs = qs.filter(team=team)
        return Response(TerraformRunSerializer(list(qs[:100]), many=True).data)


class TerraformRunDetailView(APIView):
    authentication_classes = [MongoJWTAuthentication]
    permission_classes = [IsMongoAuthenticated]

    def get(self, request, pk):
        if not request.user.has_permission('view_deployments'):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            run = TerraformRun.objects.get(id=pk)
        except (DoesNotExist, MEValidationError):
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(TerraformRunSerializer(run).data)


class TerraformRunLogsView(APIView):
    """
    GET /api/terraform/runs/<id>/logs/

    Returns the full log content stored in MongoDB.
    Also returns current status so the UI can detect run completion.
    """
    authentication_classes = [MongoJWTAuthentication]
    permission_classes = [IsMongoAuthenticated]

    def get(self, request, pk):
        if not request.user.has_permission('view_deployments'):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            run = TerraformRun.objects.get(id=pk)
        except (DoesNotExist, MEValidationError):
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        if run.log:
            logs = run.log
        elif run.status in (TerraformRun.STATUS_PENDING, TerraformRun.STATUS_RUNNING):
            logs = '[Run in progress — log not yet available]'
        else:
            logs = '(no output captured)'

        return Response({
            'req_id':    run.req_id,
            'team':      run.team,
            'status':    run.status,
            'exit_code': run.exit_code,
            'summary':   run.summary,
            'logs':      logs,
        })

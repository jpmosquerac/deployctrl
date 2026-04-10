from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.authentication import MongoJWTAuthentication
from apps.accounts.rbac import CanViewAudit
from .models import AuditLog
from .serializers import AuditLogSerializer


class AuditLogListView(APIView):
    authentication_classes = [MongoJWTAuthentication]
    permission_classes = [CanViewAudit]

    def get(self, request):
        from datetime import datetime, timezone, timedelta
        qs = AuditLog.objects.order_by('-timestamp')
        if event_type := request.query_params.get('event_type'):
            qs = qs.filter(event_type=event_type)
        if resource_type := request.query_params.get('resource_type'):
            qs = qs.filter(resource_type=resource_type)
        if actor := request.query_params.get('actor'):
            qs = qs.filter(actor__icontains=actor)
        if from_date := request.query_params.get('from'):
            try:
                qs = qs.filter(timestamp__gte=datetime.fromisoformat(from_date).replace(tzinfo=timezone.utc))
            except ValueError:
                pass
        if to_date := request.query_params.get('to'):
            try:
                qs = qs.filter(timestamp__lt=datetime.fromisoformat(to_date).replace(tzinfo=timezone.utc) + timedelta(days=1))
            except ValueError:
                pass
        return Response(AuditLogSerializer(list(qs[:1000]), many=True).data)

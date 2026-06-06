import urllib.request
import urllib.error
from datetime import datetime

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from django.conf import settings

from apps.accounts.authentication import MongoJWTAuthentication
from apps.accounts.rbac import IsMongoAuthenticated
from apps.audit.utils import log_event
from .models import GitOpsConfig
from .serializers import GitOpsConfigSerializer


class GitOpsConfigView(APIView):
    authentication_classes = [MongoJWTAuthentication]
    permission_classes = [IsMongoAuthenticated]

    def _get_config(self):
        config = GitOpsConfig.objects(name='default').first()
        if not config:
            config = GitOpsConfig(name='default')
            config.save()
        return config

    def get(self, request):
        return Response(GitOpsConfigSerializer(self._get_config()).data)

    def put(self, request):
        if not request.user.has_permission('manage_gitops'):
            return Response(
                {'detail': 'Permission "manage_gitops" required.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        config = self._get_config()
        serializer = GitOpsConfigSerializer(config, data=request.data)
        serializer.is_valid(raise_exception=True)
        config = serializer.update(config, serializer.validated_data)

        log_event(
            event_type='GITOPS_CONFIGURED',
            actor=request.user.get_full_name(),
            resource_type='gitops',
            resource_id='default',
            details=f'GitOps {"enabled" if config.enabled else "disabled"} — {config.owner}/{config.repo}@{config.branch}',
        )
        return Response(GitOpsConfigSerializer(config).data)


class GitOpsTestView(APIView):
    authentication_classes = [MongoJWTAuthentication]
    permission_classes = [IsMongoAuthenticated]

    def post(self, request):
        owner  = request.data.get('owner', '').strip()
        repo   = request.data.get('repo', '').strip()
        branch = request.data.get('branch', 'main').strip()
        token  = request.data.get('token', '').strip()

        if not owner or not repo:
            return Response({'detail': 'owner and repo are required.'}, status=status.HTTP_400_BAD_REQUEST)

        api_base = getattr(settings, 'GITHUB_API_BASE', 'https://api.github.com')
        url = f'{api_base}/repos/{owner}/{repo}/branches/{branch}'
        req = urllib.request.Request(url, headers={
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            **(({'Authorization': f'Bearer {token}'}) if token else {}),
        })

        try:
            with urllib.request.urlopen(req, timeout=8):
                return Response({'ok': True, 'message': f'Conexion exitosa: {owner}/{repo}@{branch}'})
        except urllib.error.HTTPError as e:
            if e.code == 404:
                msg = f'Repositorio o branch no encontrado: {owner}/{repo}@{branch}'
            elif e.code == 401:
                msg = 'Token invalido o sin permisos.'
            elif e.code == 403:
                msg = 'Acceso denegado. Verifica los permisos del token.'
            else:
                msg = f'GitHub respondio con error {e.code}.'
            return Response({'ok': False, 'message': msg}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'ok': False, 'message': f'Error de conexion: {str(e)}'}, status=status.HTTP_200_OK)

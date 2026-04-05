from mongoengine.errors import DoesNotExist, ValidationError as MEValidationError

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.authentication import MongoJWTAuthentication
from apps.accounts.rbac import IsArchitectOrAdmin, IsMongoAuthenticated
from .models import Team
from .serializers import TeamSerializer


class TeamListView(APIView):
    authentication_classes = [MongoJWTAuthentication]
    permission_classes = [IsMongoAuthenticated]

    def get(self, request):
        return Response(TeamSerializer(list(Team.objects.order_by('name')), many=True).data)

    def post(self, request):
        if not IsArchitectOrAdmin().has_permission(request, self):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        s = TeamSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        team = Team(
            name=s.validated_data['name'],
            description=s.validated_data.get('description', ''),
            budget=s.validated_data.get('budget', 0.0),
            approval_threshold=s.validated_data.get('approval_threshold', 100.0),
        )
        team.save()
        return Response(TeamSerializer(team).data, status=status.HTTP_201_CREATED)


class TeamDetailView(APIView):
    authentication_classes = [MongoJWTAuthentication]
    permission_classes = [IsArchitectOrAdmin]

    def _get(self, pk):
        try:
            return Team.objects.get(id=pk)
        except (DoesNotExist, MEValidationError):
            return None

    def patch(self, request, pk):
        team = self._get(pk)
        if not team:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        s = TeamSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        for field, value in s.validated_data.items():
            if field not in ('id', 'created_at'):
                setattr(team, field, value)
        team.save()
        return Response(TeamSerializer(team).data)

    def delete(self, request, pk):
        team = self._get(pk)
        if not team:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        team.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

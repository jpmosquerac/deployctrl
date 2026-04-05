from datetime import datetime, timezone

import jwt
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .authentication import MongoJWTAuthentication
from .mongo_auth import decode_refresh_token, generate_tokens
from .mongo_models import MongoUser
from .mongo_models import PERMISSIONS, ROLE_PERMISSIONS, Role
from .rbac import CanManageUsers, IsAdmin, CanViewUsers, IsMongoAuthenticated
from .serializers import (
    LoginSerializer,
    MongoUserSerializer,
    RegisterSerializer,
    UpdateProfileSerializer,
)


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        user.last_login = datetime.now(timezone.utc)
        user.save()
        access, refresh = generate_tokens(user)
        return Response({
            'token': access,
            'refresh': refresh,
            'user': MongoUserSerializer(user).data,
        })


class TokenRefreshView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response({'detail': 'refresh token required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            payload = decode_refresh_token(refresh_token)
            user = MongoUser.objects.get(id=payload['user_id'])
        except jwt.ExpiredSignatureError:
            return Response({'detail': 'Refresh token expired.'}, status=status.HTTP_401_UNAUTHORIZED)
        except (jwt.InvalidTokenError, MongoUser.DoesNotExist):
            return Response({'detail': 'Invalid refresh token.'}, status=status.HTTP_401_UNAUTHORIZED)

        access, new_refresh = generate_tokens(user)
        return Response({'token': access, 'refresh': new_refresh})


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        access, refresh = generate_tokens(user)
        return Response({
            'token': access,
            'refresh': refresh,
            'user': MongoUserSerializer(user).data,
        }, status=status.HTTP_201_CREATED)


class MeView(APIView):
    authentication_classes = [MongoJWTAuthentication]
    permission_classes = [IsMongoAuthenticated]

    def get(self, request):
        return Response({'user': MongoUserSerializer(request.user).data})

    def patch(self, request):
        serializer = UpdateProfileSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = serializer.update(request.user, serializer.validated_data)
        return Response({'user': MongoUserSerializer(user).data})


class UserListView(APIView):
    authentication_classes = [MongoJWTAuthentication]
    permission_classes = [CanViewUsers]

    def get(self, request):
        users = MongoUser.objects.filter(is_active=True).order_by('username')
        return Response(MongoUserSerializer(users, many=True).data)


class UserDetailView(APIView):
    authentication_classes = [MongoJWTAuthentication]
    permission_classes = [CanManageUsers]

    def patch(self, request, user_id):
        try:
            user = MongoUser.objects.get(id=user_id)
        except MongoUser.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        allowed_fields = {'role', 'team', 'is_active', 'first_name', 'last_name'}
        for field, value in request.data.items():
            if field in allowed_fields:
                setattr(user, field, value)
        user.save()
        return Response(MongoUserSerializer(user).data)

    def delete(self, request, user_id):
        try:
            user = MongoUser.objects.get(id=user_id)
        except MongoUser.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        user.is_active = False
        user.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class RoleListView(APIView):
    """GET all roles with their permission lists."""
    authentication_classes = [MongoJWTAuthentication]
    permission_classes = [IsMongoAuthenticated]

    def get(self, request):
        roles = []
        for name, perms in ROLE_PERMISSIONS.items():
            db_role = Role.objects(name=name).first()
            roles.append({
                'name': name,
                'permissions': db_role.permissions if db_role else perms,
                'all_permissions': list(PERMISSIONS.keys()),
            })
        return Response(roles)


class RoleDetailView(APIView):
    """PUT to update a role's permissions (admin only)."""
    authentication_classes = [MongoJWTAuthentication]
    permission_classes = [IsAdmin]

    def put(self, request, name):
        allowed_names = list(ROLE_PERMISSIONS.keys())
        if name not in allowed_names:
            return Response({'detail': f'Role must be one of: {allowed_names}'}, status=status.HTTP_400_BAD_REQUEST)

        new_perms = request.data.get('permissions', [])
        if not isinstance(new_perms, list):
            return Response({'detail': 'permissions must be a list.'}, status=status.HTTP_400_BAD_REQUEST)

        Role.objects(name=name).update_one(set__permissions=new_perms, upsert=True)
        # Also update the in-memory map so running views see it immediately
        ROLE_PERMISSIONS[name] = new_perms

        return Response({'name': name, 'permissions': new_perms})

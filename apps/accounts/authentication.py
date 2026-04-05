"""Custom DRF authentication class that validates JWT against MongoDB users."""
import jwt
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .mongo_auth import decode_access_token
from .mongo_models import MongoUser


class MongoJWTAuthentication(BaseAuthentication):
    """
    Authenticate via 'Authorization: Bearer <access_token>'.
    Looks up the user in MongoDB; returns (MongoUser, token) on success.
    """

    def authenticate(self, request):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return None  # no credentials — let other authenticators try

        token = auth.split(' ', 1)[1].strip()
        try:
            payload = decode_access_token(token)
        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed('Token has expired.')
        except jwt.InvalidTokenError as exc:
            raise AuthenticationFailed(f'Invalid token: {exc}')

        try:
            user = MongoUser.objects.get(id=payload['user_id'])
        except (MongoUser.DoesNotExist, Exception):
            raise AuthenticationFailed('User not found.')

        if not user.is_active:
            raise AuthenticationFailed('Account is disabled.')

        return (user, token)

    def authenticate_header(self, request):
        return 'Bearer realm="api"'

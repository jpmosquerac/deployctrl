from django.urls import path
from .views import (
    LoginView,
    MeView,
    RegisterView,
    RoleDetailView,
    RoleListView,
    TokenRefreshView,
    UserDetailView,
    UserListView,
)

urlpatterns = [
    path('login/', LoginView.as_view(), name='auth-login'),
    path('register/', RegisterView.as_view(), name='auth-register'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    path('me/', MeView.as_view(), name='auth-me'),
    path('users/', UserListView.as_view(), name='user-list'),
    path('users/<str:user_id>/', UserDetailView.as_view(), name='user-detail'),
    path('roles/', RoleListView.as_view(), name='role-list'),
    path('roles/<str:name>/', RoleDetailView.as_view(), name='role-detail'),
]

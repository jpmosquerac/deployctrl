from django.urls import path
from .views import TerraformRunListView, TerraformRunDetailView, TerraformRunLogsView
from .state_views import TerraformStateView, TerraformStateLockView

urlpatterns = [
    path('runs/',                          TerraformRunListView.as_view(),   name='terraform-run-list'),
    path('runs/<str:pk>/',                 TerraformRunDetailView.as_view(), name='terraform-run-detail'),
    path('runs/<str:pk>/logs/',            TerraformRunLogsView.as_view(),   name='terraform-run-logs'),
    path('state/<str:req_id>/',            TerraformStateView.as_view(),     name='terraform-state'),
    path('state/<str:req_id>/lock/',       TerraformStateLockView.as_view(), name='terraform-state-lock'),
]

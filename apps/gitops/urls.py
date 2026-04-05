from django.urls import path
from .views import GitOpsConfigView, GitOpsTestView

urlpatterns = [
    path('gitops/', GitOpsConfigView.as_view(), name='gitops-config'),
    path('gitops/test/', GitOpsTestView.as_view(), name='gitops-test'),
]

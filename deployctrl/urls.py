from django.urls import path, include

urlpatterns = [
    path('', include('apps.web.urls')),
    path('api/auth/', include('apps.accounts.urls')),
    path('api/templates/', include('apps.catalog.urls')),
    path('api/requests/', include('apps.infra_requests.urls')),
    path('api/audit/', include('apps.audit.urls')),
    path('api/settings/', include('apps.gitops.urls')),
    path('api/teams/', include('apps.teams.urls')),
    path('api/terraform/', include('apps.terraform.urls')),
]

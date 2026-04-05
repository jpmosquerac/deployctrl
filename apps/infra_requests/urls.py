from django.urls import path
from .views import (
    RequestListView, RequestDetailView, RequestResourceView,
    RequestRetryView, RequestDecommissionView, RequestOutputsView,
)

urlpatterns = [
    path('', RequestListView.as_view(), name='request-list'),
    path('<str:pk>/', RequestDetailView.as_view(), name='request-detail'),
    path('<str:pk>/resource/', RequestResourceView.as_view(), name='request-resource'),
    path('<str:pk>/retry/', RequestRetryView.as_view(), name='request-retry'),
    path('<str:pk>/decommission/', RequestDecommissionView.as_view(), name='request-decommission'),
    path('<str:pk>/outputs/', RequestOutputsView.as_view(), name='request-outputs'),
]

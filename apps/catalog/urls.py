from django.urls import path
from .views import TemplateListView, TemplateDetailView

urlpatterns = [
    path('', TemplateListView.as_view(), name='template-list'),
    path('<str:pk>/', TemplateDetailView.as_view(), name='template-detail'),
]

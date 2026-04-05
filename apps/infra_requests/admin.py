from django.contrib import admin
from .models import InfraRequest


@admin.register(InfraRequest)
class InfraRequestAdmin(admin.ModelAdmin):
    list_display = ['id', 'template_id', 'user_name', 'team', 'status', 'cost', 'region', 'created_at']
    list_filter = ['status', 'region', 'template']
    search_fields = ['id', 'user_name', 'team', 'justification']
    readonly_fields = ['created_at']
    ordering = ['-created_at']

from django.contrib import admin
from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['timestamp', 'event_type', 'actor', 'resource_type', 'resource_id']
    list_filter = ['event_type', 'resource_type']
    search_fields = ['actor', 'resource_id', 'details']
    readonly_fields = ['timestamp', 'event_type', 'actor', 'resource_type', 'resource_id', 'details']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

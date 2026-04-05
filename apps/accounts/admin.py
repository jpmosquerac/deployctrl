from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['username', 'email', 'role', 'team', 'is_active', 'date_joined']
    list_filter = ['role', 'is_active', 'is_staff']
    fieldsets = BaseUserAdmin.fieldsets + (
        ('CloudGov Profile', {'fields': ('role', 'team')}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('CloudGov Profile', {'fields': ('role', 'team')}),
    )
    search_fields = ['username', 'email', 'team']

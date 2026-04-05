from django.contrib import admin
from .models import GitOpsConfig


@admin.register(GitOpsConfig)
class GitOpsConfigAdmin(admin.ModelAdmin):
    list_display = ['name', 'enabled', 'owner', 'repo', 'branch', 'updated_at']
    readonly_fields = ['updated_at']

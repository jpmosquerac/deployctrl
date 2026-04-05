import json
from pathlib import Path

from rest_framework import serializers

from .models import InfraRequest

EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / 'tf_templates'


def _valid_template_ids():
    ids = set()
    for json_path in EXAMPLES_DIR.glob('*/*.json'):
        with open(json_path) as f:
            data = json.load(f)
        if tid := data.get('id'):
            ids.add(tid)
    return ids


class InfraRequestSerializer(serializers.Serializer):
    id              = serializers.SerializerMethodField()
    templateId      = serializers.CharField(source='template_id')
    userId          = serializers.CharField(source='mongo_user_id')
    userName        = serializers.CharField(source='user_name')
    team            = serializers.CharField()
    status          = serializers.CharField()
    cost            = serializers.FloatField()
    region          = serializers.CharField()
    justification   = serializers.CharField()
    parameters      = serializers.DictField()
    createdAt       = serializers.DateTimeField(source='created_at')
    reviewedBy      = serializers.CharField(source='reviewed_by')
    reviewedAt      = serializers.DateTimeField(source='reviewed_at', allow_null=True)
    resourceRendered      = serializers.BooleanField(source='resource_rendered')
    resourceGithubUrl     = serializers.CharField(source='resource_github_url')
    terraformRunId        = serializers.CharField(source='terraform_run_id')
    terraformRunStatus    = serializers.SerializerMethodField()

    def get_id(self, obj):
        return obj.req_id

    def get_terraformRunStatus(self, obj):
        if not obj.terraform_run_id:
            return ''
        from apps.terraform.models import TerraformRun
        from mongoengine.errors import DoesNotExist, ValidationError
        try:
            run = TerraformRun.objects.only('status').get(id=obj.terraform_run_id)
            return run.status
        except (DoesNotExist, ValidationError):
            return ''


class InfraRequestCreateSerializer(serializers.Serializer):
    # Accept camelCase from the frontend; validated_data keys stay snake_case
    # via the source= argument so the view doesn't need to change.
    templateId    = serializers.CharField(source='template_id')
    cost          = serializers.FloatField(min_value=0)
    region        = serializers.CharField(max_length=64)
    justification = serializers.CharField(max_length=1000)
    parameters    = serializers.DictField(required=False, default=dict)

    def validate_templateId(self, value):
        if value not in _valid_template_ids():
            raise serializers.ValidationError(
                f'Template {value!r} not found in catalog.'
            )
        return value

    def validate_region(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Region cannot be blank.')
        return value

    def validate_cost(self, value):
        if value < 0:
            raise serializers.ValidationError('Cost must be non-negative.')
        return value


class InfraRequestPatchSerializer(serializers.Serializer):
    status = serializers.CharField()

    def validate_status(self, value):
        allowed = [
            InfraRequest.STATUS_APPROVED,
            InfraRequest.STATUS_REJECTED,
            InfraRequest.STATUS_PROVISIONED,
        ]
        if value not in allowed:
            raise serializers.ValidationError(f'Must be one of: {allowed}')
        return value

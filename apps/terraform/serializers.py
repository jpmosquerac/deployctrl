from rest_framework import serializers


class TerraformRunSerializer(serializers.Serializer):
    id           = serializers.SerializerMethodField()
    req_id       = serializers.CharField()
    team         = serializers.CharField()
    run_type     = serializers.CharField(default='apply', allow_null=True, allow_blank=True)
    status       = serializers.CharField()
    triggered_by = serializers.CharField()
    owner        = serializers.CharField()
    repo         = serializers.CharField()
    branch       = serializers.CharField()
    started_at   = serializers.DateTimeField(allow_null=True)
    finished_at  = serializers.DateTimeField(allow_null=True)
    summary      = serializers.CharField()
    exit_code    = serializers.IntegerField(allow_null=True)
    has_logs     = serializers.SerializerMethodField()
    created_at   = serializers.DateTimeField()

    def get_id(self, obj):
        return str(obj.id)

    def get_has_logs(self, obj):
        return bool(obj.log)

from rest_framework import serializers


class AuditLogSerializer(serializers.Serializer):
    id            = serializers.SerializerMethodField()
    event_type    = serializers.CharField()
    actor         = serializers.CharField()
    resource_type = serializers.CharField()
    resource_id   = serializers.CharField()
    details       = serializers.CharField()
    timestamp     = serializers.DateTimeField()

    def get_id(self, obj):
        return str(obj.id)

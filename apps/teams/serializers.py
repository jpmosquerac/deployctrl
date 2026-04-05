from rest_framework import serializers


class TeamSerializer(serializers.Serializer):
    id                 = serializers.SerializerMethodField()
    name               = serializers.CharField()
    description        = serializers.CharField(required=False, default='')
    budget             = serializers.FloatField(required=False, default=0.0)
    approval_threshold = serializers.FloatField(required=False, default=100.0)
    created_at         = serializers.DateTimeField(read_only=True)

    def get_id(self, obj):
        return str(obj.id)

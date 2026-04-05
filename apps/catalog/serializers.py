from rest_framework import serializers


class TemplateSerializer(serializers.Serializer):
    id            = serializers.CharField(read_only=True)
    name          = serializers.CharField()
    description   = serializers.CharField()
    estimatedCost = serializers.FloatField(source='estimated_cost')
    category      = serializers.CharField()
    icon          = serializers.CharField()

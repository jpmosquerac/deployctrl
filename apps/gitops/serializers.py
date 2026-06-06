from rest_framework import serializers


class GitOpsConfigSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(default=False)
    config  = serializers.SerializerMethodField()

    def get_config(self, obj):
        return {
            'token':  obj.token,
            'owner':  obj.owner,
            'repo':   obj.repo,
            'branch': obj.branch,
        }

    def to_internal_value(self, data):
        internal = {}
        internal['enabled'] = data.get('enabled', False)
        cfg = data.get('config', {})
        internal['token']  = cfg.get('token',  '')
        internal['owner']  = cfg.get('owner',  '')
        internal['repo']   = cfg.get('repo',   '')
        internal['branch'] = cfg.get('branch', 'main')
        return internal

    def update(self, instance, validated_data):
        instance.enabled = validated_data.get('enabled', instance.enabled)
        instance.token   = validated_data.get('token',   instance.token)
        instance.owner   = validated_data.get('owner',   instance.owner)
        instance.repo    = validated_data.get('repo',    instance.repo)
        instance.branch  = validated_data.get('branch',  instance.branch)
        from datetime import datetime
        instance.updated_at = datetime.utcnow()
        instance.save()
        return instance

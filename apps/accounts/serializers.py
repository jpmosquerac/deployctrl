from rest_framework import serializers

from .mongo_models import ROLE_CHOICES, MongoUser


class MongoUserSerializer(serializers.Serializer):
    id = serializers.SerializerMethodField()
    username = serializers.CharField()
    email = serializers.EmailField()
    name = serializers.SerializerMethodField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    role = serializers.CharField()
    team = serializers.CharField()
    permissions = serializers.SerializerMethodField()

    def get_id(self, obj):
        return obj.id_str

    def get_name(self, obj):
        return obj.get_full_name()

    def get_permissions(self, obj):
        return obj.get_permissions()


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        try:
            user = MongoUser.objects.get(username=data['username'])
        except MongoUser.DoesNotExist:
            raise serializers.ValidationError('Invalid credentials.')
        if not user.is_active:
            raise serializers.ValidationError('Account is disabled.')
        if not user.check_password(data['password']):
            raise serializers.ValidationError('Invalid credentials.')
        data['user'] = user
        return data


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    first_name = serializers.CharField(max_length=100, default='', required=False)
    last_name = serializers.CharField(max_length=100, default='', required=False)
    role = serializers.ChoiceField(choices=ROLE_CHOICES, default='developer')
    team = serializers.CharField(max_length=100, default='', required=False)

    def validate_username(self, value):
        if MongoUser.objects(username=value).count():
            raise serializers.ValidationError('Username already taken.')
        return value

    def validate_email(self, value):
        if MongoUser.objects(email=value).count():
            raise serializers.ValidationError('Email already registered.')
        return value

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = MongoUser(**validated_data)
        user.set_password(password)
        user.save()
        return user


class UpdateProfileSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=100, required=False)
    last_name = serializers.CharField(max_length=100, required=False)
    team = serializers.CharField(max_length=100, required=False)
    email = serializers.EmailField(required=False)

    def update(self, instance, validated_data):
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        return instance

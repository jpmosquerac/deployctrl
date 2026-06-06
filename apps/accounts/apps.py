from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = 'apps.accounts'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        import mongoengine
        from django.conf import settings

        mongoengine.connect(
            host=settings.MONGO_URI,
            db=settings.MONGO_DB,
            alias='default',
            uuidRepresentation='standard',
        )

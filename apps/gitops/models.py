from datetime import datetime
import mongoengine as me


class GitOpsConfig(me.Document):
    name       = me.StringField(max_length=50, unique=True, default='default')
    enabled    = me.BooleanField(default=False)
    token      = me.StringField(default='')
    owner      = me.StringField(default='')
    repo       = me.StringField(default='')
    branch     = me.StringField(default='main')
    updated_at = me.DateTimeField(default=datetime.utcnow)

    meta = {'collection': 'gitops_config'}

    def __str__(self):
        return f'GitOps: {self.owner}/{self.repo}'

from datetime import datetime
import mongoengine as me


class RequestCounter(me.Document):
    """Atomic counter used to generate sequential REQ-NNNN identifiers."""
    name  = me.StringField(unique=True, default='infra_requests')
    count = me.IntField(default=0)
    meta  = {'collection': 'counters'}

    @classmethod
    def next(cls):
        counter = cls.objects(name='infra_requests').modify(
            upsert=True,
            new=True,
            inc__count=1,
        )
        return counter.count


class InfraRequest(me.Document):
    STATUS_PENDING         = 'pending'
    STATUS_APPROVED        = 'approved'
    STATUS_REJECTED        = 'rejected'
    STATUS_PROVISIONED     = 'provisioned'
    STATUS_DECOMMISSIONING = 'decommissioning'
    STATUS_DECOMMISSIONED  = 'decommissioned'

    req_number     = me.IntField()          # sequential counter → REQ-0001
    template_id    = me.StringField(required=True)
    mongo_user_id  = me.StringField(required=True)
    user_name      = me.StringField(default='')
    team           = me.StringField(default='')
    status         = me.StringField(
        choices=['pending', 'approved', 'rejected', 'provisioned', 'decommissioning', 'decommissioned'],
        default='pending',
    )
    cost           = me.FloatField(required=True)
    region         = me.StringField(required=True)
    justification  = me.StringField(default='')
    parameters     = me.DictField()
    created_at     = me.DateTimeField(default=datetime.utcnow)
    reviewed_by    = me.StringField(default='')
    reviewed_at    = me.DateTimeField()

    # Resource generation — populated when status transitions to 'approved'
    resource_rendered    = me.BooleanField(default=False)
    resource_tf_filename = me.StringField(default='')
    resource_tfvars      = me.StringField(default='')
    resource_github_url  = me.StringField(default='')

    # Terraform run triggered after push
    terraform_run_id = me.StringField(default='')

    meta = {'collection': 'infra_requests', 'ordering': ['-created_at']}

    @property
    def req_id(self):
        if self.req_number:
            return f'REQ-{self.req_number:04d}'
        return str(self.id)

    def __str__(self):
        return f'{self.req_id} — {self.template_id} ({self.status})'

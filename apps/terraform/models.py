from datetime import datetime
import mongoengine as me


class TerraformState(me.Document):
    """
    Stores Terraform state for a single request, used by the HTTP backend.
    state_json and lock_info are stored as raw strings to avoid MongoDB
    key restrictions (Terraform state can contain keys with dots and $ signs).
    """
    req_id     = me.StringField(unique=True, required=True)
    state_json = me.StringField(default='')   # raw Terraform state JSON
    lock_id    = me.StringField(default='')
    lock_info  = me.StringField(default='')   # raw LockInfo JSON
    updated_at = me.DateTimeField(default=datetime.utcnow)

    meta = {
        'collection': 'terraform_states',
        'indexes': ['req_id'],
    }

    def __str__(self):
        return f'TerraformState({self.req_id})'


class TerraformRun(me.Document):
    STATUS_PENDING   = 'pending'
    STATUS_RUNNING   = 'running'
    STATUS_SUCCEEDED = 'succeeded'
    STATUS_FAILED    = 'failed'

    RUN_TYPE_APPLY   = 'apply'
    RUN_TYPE_DESTROY = 'destroy'

    req_id       = me.StringField(default='')   # REQ-NNNN of the triggering request
    team         = me.StringField(required=True)
    run_type     = me.StringField(default=RUN_TYPE_APPLY)
    status       = me.StringField(default=STATUS_PENDING)
    triggered_by = me.StringField(default='system')
    owner        = me.StringField(default='')
    repo         = me.StringField(default='')
    branch       = me.StringField(default='main')
    started_at   = me.DateTimeField()
    finished_at  = me.DateTimeField()
    log          = me.StringField(default='')   # full stdout/stderr stored in DB
    summary      = me.StringField(default='')
    exit_code    = me.IntField()
    created_at   = me.DateTimeField(default=datetime.utcnow)

    meta = {
        'collection': 'terraform_runs',
        'ordering': ['-created_at'],
        'strict': False,  # ignore legacy fields (e.g. log_path) still in DB
    }

    def __str__(self):
        return f'TerraformRun({self.req_id or self.team}, {self.status})'

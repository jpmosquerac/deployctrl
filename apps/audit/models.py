from datetime import datetime
import mongoengine as me


class AuditLog(me.Document):
    event_type    = me.StringField(max_length=50, required=True)
    actor         = me.StringField(max_length=200, required=True)
    resource_type = me.StringField(max_length=50, required=True)
    resource_id   = me.StringField(max_length=100, required=True)
    details       = me.StringField(default='')
    timestamp     = me.DateTimeField(default=datetime.utcnow)

    meta = {'collection': 'audit_logs', 'ordering': ['-timestamp']}

    def __str__(self):
        return f'[{self.timestamp}] {self.event_type} by {self.actor}'

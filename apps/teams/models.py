from datetime import datetime
import mongoengine as me


class Team(me.Document):
    name               = me.StringField(max_length=100, unique=True, required=True)
    description        = me.StringField(default='')
    budget             = me.FloatField(default=0.0)
    approval_threshold = me.FloatField(default=100.0)
    created_at         = me.DateTimeField(default=datetime.utcnow)

    meta = {'collection': 'teams', 'ordering': ['name']}

    def __str__(self):
        return self.name

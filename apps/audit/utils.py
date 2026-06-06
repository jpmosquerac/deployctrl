from .models import AuditLog


def log_event(event_type: str, actor: str, resource_type: str, resource_id: str, details: str = ''):
    AuditLog(
        event_type=event_type,
        actor=actor,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
    ).save()

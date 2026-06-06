import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class TerraformConfig(AppConfig):
    name = 'apps.terraform'

    def ready(self):
        """
        On startup, any TerraformRun still marked 'running' or 'pending' is
        orphaned — its background thread was killed when the server stopped.
        Mark them failed so the UI shows the correct state and operators can
        re-trigger if needed.
        """
        try:
            from .models import TerraformRun
            from datetime import datetime, timezone

            stuck = TerraformRun.objects(
                status__in=[TerraformRun.STATUS_RUNNING, TerraformRun.STATUS_PENDING]
            )
            count = stuck.count()
            if count:
                stuck.update(
                    set__status=TerraformRun.STATUS_FAILED,
                    set__finished_at=datetime.now(timezone.utc),
                    set__summary='Run interrupted — server restarted before completion.',
                )
                logger.warning(
                    'TerraformConfig.ready: marked %d orphaned run(s) as failed.', count
                )
        except Exception as exc:
            logger.error('TerraformConfig.ready cleanup failed: %s', exc)

"""
Management command — mark orphaned TerraformRun documents as failed.

Usage:
    # Reset ALL stuck runs
    python manage.py reset_stuck_runs

    # Reset a single specific run by its MongoDB ObjectId
    python manage.py reset_stuck_runs --id 69d89eac809e45c1f2b73bb9
"""
from datetime import datetime, timezone

from django.core.management.base import BaseCommand

from apps.terraform.models import TerraformRun


class Command(BaseCommand):
    help = 'Mark orphaned (running/pending) TerraformRun documents as failed.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--id',
            dest='run_id',
            default=None,
            help='MongoDB ObjectId of a specific run to reset (default: all stuck runs).',
        )

    def handle(self, *args, **options):
        now = datetime.now(timezone.utc)
        run_id = options['run_id']

        if run_id:
            try:
                qs = TerraformRun.objects(id=run_id)
            except Exception as e:
                self.stderr.write(self.style.ERROR(f'Invalid id: {e}'))
                return
        else:
            qs = TerraformRun.objects(
                status__in=[TerraformRun.STATUS_RUNNING, TerraformRun.STATUS_PENDING]
            )

        runs = list(qs)
        if not runs:
            self.stdout.write(self.style.WARNING('No stuck runs found.'))
            return

        for run in runs:
            self.stdout.write(
                f'  Resetting run {run.id}  req={run.req_id}  team={run.team}  '
                f'status={run.status}  started={run.started_at}'
            )

        qs.update(
            set__status=TerraformRun.STATUS_FAILED,
            set__finished_at=now,
            set__summary='Run interrupted — reset manually via reset_stuck_runs command.',
        )

        self.stdout.write(
            self.style.SUCCESS(f'Reset {len(runs)} run(s) to failed.')
        )

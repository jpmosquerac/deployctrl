from django.core.management.base import BaseCommand


MONGO_USERS = [
    {'username': 'alice', 'email': 'alice@example.com', 'password': 'demopassword123', 'first_name': 'Alice', 'last_name': 'Developer', 'role': 'developer', 'team': 'Product A'},
    {'username': 'bob',   'email': 'bob@example.com',   'password': 'demopassword123', 'first_name': 'Bob',   'last_name': 'Architect', 'role': 'architect', 'team': 'Governance'},
    {'username': 'admin', 'email': 'admin@example.com', 'password': 'adminpassword123','first_name': 'Admin', 'last_name': 'User',      'role': 'admin',     'team': 'Platform'},
]

DEMO_TEAMS = [
    {'name': 'Product A',   'description': 'Frontend product team',          'budget': 5000.0,  'approval_threshold': 100.0},
    {'name': 'Governance',  'description': 'Platform governance team',       'budget': 12000.0, 'approval_threshold': 500.0},
    {'name': 'Platform',    'description': 'Infrastructure platform team',   'budget': 25000.0, 'approval_threshold': 250.0},
]


class Command(BaseCommand):
    help = 'Seed all data into MongoDB'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Delete existing data before seeding')

    def handle(self, *args, **options):
        from apps.teams.models import Team
        from apps.accounts.mongo_models import MongoUser, Permission, Role, PERMISSIONS, ROLE_PERMISSIONS

        if options['reset']:
            Team.objects.all().delete()
            MongoUser.objects.all().delete()
            Role.objects.all().delete()
            Permission.objects.all().delete()
            self.stdout.write('Cleared existing data.')

        # ── Demo Teams ─────────────────────────────────────────────────────
        team_new = 0
        for t in DEMO_TEAMS:
            if not Team.objects(name=t['name']).first():
                Team(**t).save()
                team_new += 1
        self.stdout.write(self.style.SUCCESS(f'Teams: {len(DEMO_TEAMS)} total ({team_new} new).'))

        # ── Permissions ────────────────────────────────────────────────────
        for codename, description in PERMISSIONS.items():
            Permission.objects(codename=codename).update_one(set__description=description, upsert=True)
        self.stdout.write(self.style.SUCCESS(f'Synced {len(PERMISSIONS)} permissions.'))

        # ── Roles ──────────────────────────────────────────────────────────
        for role_name, perms in ROLE_PERMISSIONS.items():
            Role.objects(name=role_name).update_one(set__permissions=perms, upsert=True)
        self.stdout.write(self.style.SUCCESS(f'Synced {len(ROLE_PERMISSIONS)} roles.'))

        # ── Demo Users ─────────────────────────────────────────────────────
        for u in MONGO_USERS:
            password = u.pop('password')
            if MongoUser.objects(username=u['username']).first():
                self.stdout.write(f'User already exists: {u["username"]}')
            else:
                user = MongoUser(**u)
                user.set_password(password)
                user.save()
                self.stdout.write(self.style.SUCCESS(f'Created user: {user.username} [{user.role}]'))
            u['password'] = password

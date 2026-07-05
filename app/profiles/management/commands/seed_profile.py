"""
Seed a complete profile with all sections for local/testing use.

Usage:
    python manage.py seed_profile --email you@example.com
    python manage.py seed_profile --email test@example.com --create-user
    python manage.py seed_profile --all-verified
"""

import copy
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from jsonschema import ValidationError as JSONSchemaValidationError
from jsonschema import validate

from app.authentication.models import User
from app.profiles.models import Profile
from app.profiles.services import ProfileService


def load_full_profile_example() -> dict:
    schema_path = Path(settings.BASE_DIR) / 'schemas' / 'profile.json'
    with schema_path.open('r', encoding='utf-8') as handle:
        schema = json.load(handle)

    for example in schema.get('examples', []):
        if example.get('description') == 'Full profile with all sections':
            return copy.deepcopy(example['value'])

    raise CommandError('Full profile example not found in schemas/profile.json')


def normalize_seed_data(data: dict, email: str) -> dict:
    seeded = copy.deepcopy(data)
    seeded['personalInfo']['email'] = email.lower()
    seeded['personalInfo']['location'] = 'San Francisco, California, United States'
    return seeded


class Command(BaseCommand):
    help = 'Seed a complete profile (all sections) for testing'

    def add_arguments(self, parser):
        parser.add_argument(
            '--email',
            type=str,
            help='Email of the user whose profile should be seeded',
        )
        parser.add_argument(
            '--create-user',
            action='store_true',
            help='Create the user if missing (password: testpass123, verified)',
        )
        parser.add_argument(
            '--all-verified',
            action='store_true',
            help='Seed every verified user in the database',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Replace existing profile data',
        )

    def handle(self, *args, **options):
        if not options['email'] and not options['all_verified']:
            raise CommandError('Provide --email USER@example.com or --all-verified')

        schema_path = Path(settings.BASE_DIR) / 'schemas' / 'profile.json'
        with schema_path.open('r', encoding='utf-8') as handle:
            profile_schema = json.load(handle)

        base_data = load_full_profile_example()

        if options['all_verified']:
            users = User.objects.filter(is_verified=True)
            if not users.exists():
                raise CommandError('No verified users found to seed.')
            for user in users:
                self._seed_user(user, base_data, profile_schema, options['force'])
            return

        email = options['email'].lower()
        user = User.objects.filter(email=email).first()
        if user is None:
            if not options['create_user']:
                raise CommandError(
                    f'User "{email}" does not exist. Pass --create-user to create one.'
                )
            user = User.objects.create_user(
                email=email,
                password='testpass123',
                is_verified=True,
            )
            self.stdout.write(self.style.WARNING(f'Created user {email} (password: testpass123)'))

        self._seed_user(user, base_data, profile_schema, options['force'])

    def _seed_user(self, user, base_data, profile_schema, force: bool):
        if Profile.objects.filter(user=user).exists() and not force:
            raise CommandError(
                f'Profile already exists for {user.email}. Use --force to replace it.'
            )

        data = normalize_seed_data(base_data, user.email)

        try:
            validate(instance=data, schema=profile_schema)
        except JSONSchemaValidationError as exc:
            path = '.'.join(str(part) for part in exc.absolute_path) or 'root'
            raise CommandError(f'Seed data failed schema validation at {path}: {exc.message}') from exc

        profile = ProfileService.create_or_update_profile(
            user=user,
            data=data,
            partial=False,
        )

        section_counts = {
            key: len(value) if isinstance(value, list) else (1 if value else 0)
            for key, value in data.items()
            if key not in ('personalInfo', 'summary', 'address', 'social_urls', 'profile_picture', 'contact_info')
        }

        self.stdout.write(self.style.SUCCESS(f'Seeded profile for {user.email} (id={profile.id})'))
        self.stdout.write('Sections populated:')
        for section, count in sorted(section_counts.items()):
            self.stdout.write(f'  - {section}: {count}')

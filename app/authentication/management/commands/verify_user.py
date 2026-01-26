"""
Django management command to verify a user's email.

Usage:
    python manage.py verify_user test@gmail.com
    python manage.py verify_user test@gmail.com --unverify
"""

from django.core.management.base import BaseCommand, CommandError
from app.authentication.models import User


class Command(BaseCommand):
    help = 'Verify or unverify a user\'s email address'
    
    def add_arguments(self, parser):
        parser.add_argument(
            'email',
            type=str,
            help='Email address of the user to verify',
        )
        parser.add_argument(
            '--unverify',
            action='store_true',
            help='Unverify the user instead of verifying',
        )
    
    def handle(self, *args, **options):
        email = options['email']
        unverify = options['unverify']
        
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise CommandError(f'User with email "{email}" does not exist.')
        
        if unverify:
            user.is_verified = False
            action = 'unverified'
        else:
            user.is_verified = True
            action = 'verified'
        
        user.save()
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully {action} email for user: {user.email}'
            )
        )

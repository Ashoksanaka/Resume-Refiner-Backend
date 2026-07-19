"""
Custom authentication backends for the Resume AI platform.

EmailBackend is retained for Django admin superuser login only.
"""

import logging

from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.hashers import make_password

from app.authentication.models import User

logger = logging.getLogger(__name__)


class EmailBackend(ModelBackend):
    """
    Django authentication backend that authenticates admin users by email.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get('email')

        if username is None or password is None:
            return None

        try:
            email = username.lower()
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Hash work comparable to a real check_password, without setting a user password.
            make_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user

        return None

    def user_can_authenticate(self, user):
        return getattr(user, 'is_active', True)

"""
Authentication services for the Resume AI platform.
"""

from app.authentication.models import User
from app.common.exceptions import EmailNotVerifiedException


class AuthenticationService:
    """Service class for authentication-related business logic."""

    @staticmethod
    def require_verified_email(user: User) -> None:
        """
        Check that a user has verified their email.

        Clerk-managed users are created with is_verified=True.
        """
        if not user.is_verified:
            raise EmailNotVerifiedException()

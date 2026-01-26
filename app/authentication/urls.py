"""
URL patterns for authentication endpoints.

Maps to:
- POST /auth/signup
- POST /auth/verify
- POST /auth/resend-verification
- POST /auth/login
- POST /auth/logout
- GET /auth/me
- POST /auth/forgot-password
- POST /auth/reset-password
- GET /auth/password-policy
- POST /auth/password-strength
"""

from django.urls import path
from app.authentication.views import (
    SignupView,
    VerifyEmailView,
    ResendVerificationView,
    LoginView,
    LogoutView,
    MeView,
    ForgotPasswordView,
    ResetPasswordView,
    PasswordPolicyView,
    PasswordStrengthView,
)

app_name = 'authentication'

urlpatterns = [
    path('signup', SignupView.as_view(), name='signup'),
    path('verify', VerifyEmailView.as_view(), name='verify'),
    path('resend-verification', ResendVerificationView.as_view(), name='resend-verification'),
    path('login', LoginView.as_view(), name='login'),
    path('logout', LogoutView.as_view(), name='logout'),
    path('me', MeView.as_view(), name='me'),
    path('forgot-password', ForgotPasswordView.as_view(), name='forgot-password'),
    path('reset-password', ResetPasswordView.as_view(), name='reset-password'),
    path('password-policy', PasswordPolicyView.as_view(), name='password-policy'),
    path('password-strength', PasswordStrengthView.as_view(), name='password-strength'),
]

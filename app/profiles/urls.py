"""
URL patterns for profile endpoints.

Maps to:
- GET, PUT, PATCH /profiles/me
- POST, DELETE /profiles/me/picture
"""

from django.urls import path
from app.profiles.views import ProfileView, ProfilePictureView

app_name = 'profiles'

urlpatterns = [
    path('me', ProfileView.as_view(), name='profile'),
    path('me/picture', ProfilePictureView.as_view(), name='profile-picture'),
]

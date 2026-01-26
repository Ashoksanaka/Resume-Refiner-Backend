"""
URL configuration for Resume AI Platform.

The `urlpatterns` list routes URLs to views.
All API endpoints are prefixed with /api/v1 as per the API specification.
"""

from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    # Admin interface
    path('admin/', admin.site.urls),
    
    # API v1 endpoints
    path('api/v1/auth/', include('app.authentication.urls')),
    path('api/v1/profiles/', include('app.profiles.urls')),
    path('api/v1/', include('app.resumes.urls')),
]

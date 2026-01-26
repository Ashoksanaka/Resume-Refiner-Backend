"""
URL patterns for resume-related endpoints.

Maps to:
- POST /jds
- GET, DELETE /jds/{jd_id}
- GET, POST /resumes
- GET /resumes/{generation_id}/status
- GET /resumes/{generation_id}/download
- GET /resumes/{generation_id}/source
"""

from django.urls import path
from app.resumes.views import (
    JobDescriptionListCreateView,
    JobDescriptionDetailView,
    ResumeListCreateView,
    ResumeStatusView,
    ResumeDownloadView,
    ResumeSourceView,
    HealthCheckView,
)

app_name = 'resumes'

urlpatterns = [
    # Job Descriptions
    path('jds', JobDescriptionListCreateView.as_view(), name='jd-list-create'),
    path('jds/<uuid:jd_id>', JobDescriptionDetailView.as_view(), name='jd-detail'),
    
    # Resumes
    path('resumes', ResumeListCreateView.as_view(), name='resume-list-create'),
    path('resumes/<uuid:generation_id>/status', ResumeStatusView.as_view(), name='resume-status'),
    path('resumes/<uuid:generation_id>/download', ResumeDownloadView.as_view(), name='resume-download'),
    path('resumes/<uuid:generation_id>/source', ResumeSourceView.as_view(), name='resume-source'),
    
    # Health
    path('health', HealthCheckView.as_view(), name='health'),
]

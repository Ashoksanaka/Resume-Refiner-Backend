"""
Model stubs for Profile data structure.

This file provides type hints and documentation for the Profile model's JSONField data structure.
The actual Profile model is defined in app.profiles.models.Profile.

The data field contains a JSON object matching the schema in /backend/schemas/profile.json.
"""

from typing import TypedDict, List, Optional, Literal
from datetime import date, datetime


class PersonalInfo(TypedDict, total=False):
    """Personal information section."""
    full_name: str
    email: str
    phone_number: Optional[str]
    location: Optional[str]
    portfolio_url: Optional[str]


class ExperienceItem(TypedDict, total=False):
    """Work experience item."""
    company: str
    title: str
    start_date: str  # ISO 8601 date format
    end_date: Optional[str]  # ISO 8601 date format
    description: Optional[str]


class EducationItem(TypedDict, total=False):
    """Education item."""
    institution: str
    degree: str
    start_date: str  # ISO 8601 date format
    end_date: Optional[str]  # ISO 8601 date format
    description: Optional[str]


class CertificationItem(TypedDict, total=False):
    """Certification item."""
    name: str
    issuing_organization: str
    issue_date: Optional[str]  # ISO 8601 date format


class ProjectItem(TypedDict, total=False):
    """Project item."""
    id: str  # UUID
    title: str
    role: str
    description: Optional[str]
    start_date: Optional[str]  # ISO 8601 date format
    end_date: Optional[str]  # ISO 8601 date format
    ongoing: bool
    technologies: List[str]
    link: Optional[str]  # URL
    achievements: List[str]


class AchievementItem(TypedDict, total=False):
    """Achievement item."""
    id: str  # UUID
    title: str
    description: Optional[str]
    issuer: Optional[str]
    date: Optional[str]  # ISO 8601 date format


class Geolocation(TypedDict, total=False):
    """Geolocation coordinates."""
    lat: float
    lon: float


class Address(TypedDict, total=False):
    """Address information."""
    street: Optional[str]
    city: Optional[str]
    region: Optional[str]
    country: Optional[str]
    postal_code: Optional[str]
    geolocation: Optional[Geolocation]


class SocialUrlItem(TypedDict, total=False):
    """Social URL item in 'other' array."""
    label: str
    url: str


class SocialUrls(TypedDict, total=False):
    """Social media URLs."""
    linkedin: Optional[str]  # URL
    github: Optional[str]  # URL
    twitter: Optional[str]  # URL
    portfolio: Optional[str]  # URL
    website: Optional[str]  # URL
    other: List[SocialUrlItem]


class ProfilePicture(TypedDict, total=False):
    """Profile picture information."""
    url: str
    thumbnail_url: str
    uploaded_at: str  # ISO 8601 datetime format


class VolunteeringItem(TypedDict, total=False):
    """Volunteering item."""
    id: str  # UUID
    organization: str
    role: str
    start_date: Optional[str]  # ISO 8601 date format
    end_date: Optional[str]  # ISO 8601 date format
    description: Optional[str]


class PositionItem(TypedDict, total=False):
    """Position (board/leadership) item."""
    id: str  # UUID
    title: str
    organization: str
    start_date: str  # ISO 8601 date format
    end_date: Optional[str]  # ISO 8601 date format
    description: Optional[str]


class CareerBreakItem(TypedDict, total=False):
    """Career break item."""
    id: str  # UUID
    start_date: str  # ISO 8601 date format
    end_date: Optional[str]  # ISO 8601 date format
    reason: Literal['parental', 'health', 'travel', 'education', 'other']
    description: Optional[str]


class LicenseItem(TypedDict, total=False):
    """License item."""
    id: str  # UUID
    name: str
    issuer: str
    license_number: Optional[str]
    date: Optional[str]  # ISO 8601 date format
    url: Optional[str]  # URL


class TrainingItem(TypedDict, total=False):
    """Training/course item."""
    id: str  # UUID
    title: str
    provider: str
    date: Optional[str]  # ISO 8601 date format
    certificate_url: Optional[str]  # URL
    description: Optional[str]


class PublicationItem(TypedDict, total=False):
    """Publication item."""
    id: str  # UUID
    title: str
    authors: List[str]
    venue: str
    date: Optional[str]  # ISO 8601 date format
    url: Optional[str]  # URL
    abstract: Optional[str]


class PatentItem(TypedDict, total=False):
    """Patent item."""
    id: str  # UUID
    title: str
    patent_number: str
    status: Literal['filed', 'granted', 'pending']
    filing_date: Optional[str]  # ISO 8601 date format
    grant_date: Optional[str]  # ISO 8601 date format
    url: Optional[str]  # URL


class HonorAwardItem(TypedDict, total=False):
    """Honor/award item."""
    id: str  # UUID
    title: str
    issuer: str
    date: Optional[str]  # ISO 8601 date format
    description: Optional[str]


class TestScoreItem(TypedDict, total=False):
    """Test score item."""
    id: str  # UUID
    test_name: str
    score: str  # Can be number or string
    max_score: Optional[float]
    percentile: Optional[float]
    date: Optional[str]  # ISO 8601 date format


class LanguageItem(TypedDict, total=False):
    """Language item."""
    language: str
    proficiency: Literal['native', 'full_professional', 'limited_professional', 'conversational', 'basic']
    certification: Optional[str]


class OrganizationItem(TypedDict, total=False):
    """Organization item."""
    id: str  # UUID
    name: str
    role: str
    start_date: Optional[str]  # ISO 8601 date format
    end_date: Optional[str]  # ISO 8601 date format
    description: Optional[str]


class ContactInfo(TypedDict, total=False):
    """Contact information (sensitive - redacted for non-owners)."""
    primary_phone: str
    secondary_phone: Optional[str]
    secondary_email: Optional[str]
    preferred_contact_method: Literal['email', 'phone', 'none']
    timezone: Optional[str]


class ProfileData(TypedDict, total=False):
    """
    Complete Profile data structure.
    
    This matches the JSON schema in /backend/schemas/profile.json.
    All fields are optional except personalInfo.full_name and personalInfo.email.
    """
    personalInfo: PersonalInfo
    summary: Optional[str]
    experience: List[ExperienceItem]
    education: List[EducationItem]
    skills: List[str]
    certifications: List[CertificationItem]
    projects: List[ProjectItem]
    achievements: List[AchievementItem]
    areas_of_interest: List[str]
    hobbies: List[str]
    address: Optional[Address]
    social_urls: Optional[SocialUrls]
    profile_picture: Optional[ProfilePicture]
    volunteering: List[VolunteeringItem]
    positions: List[PositionItem]
    career_breaks: List[CareerBreakItem]
    licenses: List[LicenseItem]
    trainings: List[TrainingItem]
    publications: List[PublicationItem]
    patents: List[PatentItem]
    honors_awards: List[HonorAwardItem]
    test_scores: List[TestScoreItem]
    languages: List[LanguageItem]
    organizations: List[OrganizationItem]
    contact_info: Optional[ContactInfo]

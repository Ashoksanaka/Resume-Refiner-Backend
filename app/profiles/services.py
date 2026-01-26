"""
Profile services for the Resume AI platform.

Business logic for:
- Profile CRUD operations
- Profile validation against JSON schema
"""

import logging
from app.profiles.models import Profile
from app.authentication.models import User
from app.common.exceptions import ResourceNotFoundException

logger = logging.getLogger(__name__)


class ProfileService:
    """
    Service class for profile-related business logic.
    """
    
    @staticmethod
    def get_profile(user: User) -> Profile:
        """
        Get the profile for a user.
        
        Args:
            user: The user whose profile to retrieve
        
        Returns:
            Profile instance
        
        Raises:
            ResourceNotFoundException: If the user has no profile
        """
        try:
            return Profile.objects.get(user=user)
        except Profile.DoesNotExist:
            raise ResourceNotFoundException('Profile not found. Please create a profile first.')
    
    @staticmethod
    def get_or_create_profile(user: User) -> tuple[Profile, bool]:
        """
        Get or create a profile for a user.
        
        Args:
            user: The user whose profile to get/create
        
        Returns:
            Tuple of (Profile, created_bool)
        """
        return Profile.objects.get_or_create(user=user, defaults={'data': {}})
    
    @staticmethod
    def create_or_update_profile(user: User, data: dict, partial: bool = False) -> Profile:
        """
        Create or fully update a user's profile.
        
        Args:
            user: The user whose profile to update
            data: The validated profile data
            partial: If True, merge with existing data; if False, replace completely
        
        Returns:
            Updated Profile instance
        """
        profile, created = Profile.objects.get_or_create(
            user=user,
            defaults={'data': {}}
        )
        
        if partial:
            # Merge new data with existing data
            existing_data = profile.data or {}
            for key, value in data.items():
                existing_data[key] = value
            profile.data = existing_data
        else:
            # Full replacement
            profile.data = data
        
        profile.save()
        
        action = 'created' if created else 'updated'
        logger.info("Profile %s for user: %s", action, user.id)
        
        return profile
    
    @staticmethod
    def delete_profile(user: User) -> bool:
        """
        Delete a user's profile.
        
        Args:
            user: The user whose profile to delete
        
        Returns:
            True if deleted, False if no profile existed
        """
        try:
            profile = Profile.objects.get(user=user)
            profile.delete()
            logger.info("Profile deleted for user: %s", user.id)
            return True
        except Profile.DoesNotExist:
            return False
    
    @staticmethod
    def get_profile_snapshot(user: User) -> dict:
        """
        Get a snapshot of the user's profile data for resume generation.
        
        This creates a copy of the profile data at the time of generation,
        which is stored with the ResumeGenerationRequest for:
        - Reproducibility
        - Hallucination detection
        
        Args:
            user: The user whose profile to snapshot
        
        Returns:
            Copy of the profile data dict
        
        Raises:
            ResourceNotFoundException: If no profile exists
        """
        profile = ProfileService.get_profile(user)
        
        if not profile.data:
            raise ResourceNotFoundException(
                'Profile is empty. Please complete your profile before generating a resume.'
            )
        
        # Return a deep copy to ensure immutability
        import copy
        return copy.deepcopy(profile.data)

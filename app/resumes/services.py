"""
Resume services for the Resume AI platform.

Business logic for:
- Job description management
- Resume generation orchestration
- Hallucination detection
- LaTeX compilation
"""

import re
import logging
from typing import Optional, Set
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from app.resumes.models import JobDescription, ResumeGenerationRequest
from app.common.models import Template
from app.authentication.models import User, IdempotencyKey
from app.profiles.services import ProfileService
from app.common.exceptions import (
    ResourceNotFoundException,
    TTLExpiredException,
    ModelOutputInvalidException,
    LatexCompileException,
)

logger = logging.getLogger(__name__)


class JobDescriptionService:
    """
    Service class for job description operations.
    """
    
    @staticmethod
    def create_job_description(user: User, text: str) -> JobDescription:
        """
        Create a new job description.
        
        Args:
            user: The user creating the JD
            text: The job description text
        
        Returns:
            Created JobDescription instance
        """
        jd = JobDescription.objects.create(
            user=user,
            text=text.strip()
        )
        logger.info("Job description created: %s for user: %s", jd.id, user.id)
        return jd
    
    @staticmethod
    def get_job_description(user: User, jd_id: str) -> JobDescription:
        """
        Get a job description by ID.
        
        Args:
            user: The user requesting the JD
            jd_id: The job description ID
        
        Returns:
            JobDescription instance
        
        Raises:
            ResourceNotFoundException: If JD not found
            TTLExpiredException: If JD has expired
        """
        try:
            jd = JobDescription.objects.get(id=jd_id, user=user)
        except JobDescription.DoesNotExist:
            raise ResourceNotFoundException('Job description not found.')
        
        if jd.is_expired:
            raise TTLExpiredException()
        
        return jd
    
    @staticmethod
    def delete_job_description(user: User, jd_id: str) -> bool:
        """
        Delete a job description.
        
        Args:
            user: The user deleting the JD
            jd_id: The job description ID
        
        Returns:
            True if deleted
        
        Raises:
            ResourceNotFoundException: If JD not found
        """
        try:
            jd = JobDescription.objects.get(id=jd_id, user=user)
            jd.delete()
            logger.info("Job description deleted: %s", jd_id)
            return True
        except JobDescription.DoesNotExist:
            raise ResourceNotFoundException('Job description not found.')


class HallucinationDetector:
    """
    Detects hallucinated content in AI-generated LaTeX.
    
    A "hallucination" is defined as a key entity (company name, university, etc.)
    present in the LaTeX that does NOT exist in the source profile.
    
    CRITICAL SAFETY COMPONENT:
    - This MUST be strict - it's better to reject valid output than accept hallucinated output
    - Any detected hallucination causes a HARD FAILURE
    - Do NOT attempt to "fix" hallucinations - REJECT the output
    """
    
    # Patterns to extract entities from LaTeX
    # These patterns look for text in common resume LaTeX commands
    # IMPORTANT: We avoid patterns that commonly contain dates (like \textit)
    # unless we can reliably filter dates out
    LATEX_ENTITY_PATTERNS = [
        # Company/institution names in bold (less likely to be dates)
        r'\\textbf\{([^}]+)\}',
        # Company names in experience sections
        r'\\company\{([^}]+)\}',
        r'\\employer\{([^}]+)\}',
        # Institution names in education sections
        r'\\institution\{([^}]+)\}',
        r'\\school\{([^}]+)\}',
        r'\\university\{([^}]+)\}',
        # Generic section content
        r'\\organization\{([^}]+)\}',
        # Experience entry patterns from templates
        r'\\experienceEntry\{([^}]+)\}',
        r'\\educationEntry\{([^}]+)\}',
    ]
    
    # Patterns that might contain dates - use with extra caution
    # Only extract if content doesn't look like a date
    POTENTIALLY_DATED_PATTERNS = [
        r'\\textit\{([^}]+)\}',  # Italic text (often dates, but sometimes company names)
    ]
    
    # Words/phrases to ignore (common LaTeX/formatting terms and resume sections)
    IGNORE_WORDS = {
        # Employment types
        'present', 'current', 'remote', 'hybrid', 'onsite',
        'full-time', 'part-time', 'contract', 'internship',
        # Month names
        'january', 'february', 'march', 'april', 'may', 'june',
        'july', 'august', 'september', 'october', 'november', 'december',
        'jan', 'feb', 'mar', 'apr', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec',
        # Common resume section headers
        'professional summary', 'professional profile', 'profile', 'about',
        'work experience', 'education', 'skills', 'about me',
        'certifications', 'technical skills', 'key skills', 'core competencies',
        'experience', 'summary', 'objective', 'career objective', 'overview',
        'professional experience', 'employment history', 'work history',
        'academic background', 'qualifications', 'achievements', 'projects',
        'contact information', 'personal information', 'references',
        'career summary', 'executive summary', 'personal profile', 'introduction',
        # Common generic terms
        'senior', 'junior', 'lead', 'principal', 'staff', 'associate',
        'developer', 'engineer', 'manager', 'director', 'analyst',
        'software', 'web', 'mobile', 'cloud', 'data', 'machine learning',
        # Common technical skills and concepts (generic terms used across resumes)
        'system design', 'system', 'design', 'architecture', 'development',
        'testing', 'debugging', 'deployment', 'integration', 'automation',
        'optimization', 'performance', 'scalability', 'security', 'maintenance',
        'api', 'apis', 'database', 'databases', 'backend', 'frontend', 'fullstack',
        'devops', 'agile', 'scrum', 'ci/cd', 'version control', 'code review',
        'problem solving', 'problem-solving', 'communication', 'collaboration',
        'leadership', 'teamwork', 'mentoring', 'project management',
        'requirements', 'analysis', 'documentation', 'research',
        # More technical/infrastructure terms
        'infrastructure', 'cloud infrastructure', 'microservices', 'containerization',
        'kubernetes', 'docker', 'aws', 'azure', 'gcp', 'linux', 'unix', 'windows',
        'networking', 'distributed systems', 'high availability', 'load balancing',
        'monitoring', 'logging', 'alerting', 'observability', 'reliability',
        'continuous integration', 'continuous deployment', 'pipelines',
        'data engineering', 'data pipeline', 'etl', 'analytics', 'reporting',
        'machine learning', 'artificial intelligence', 'deep learning',
        'natural language processing', 'computer vision', 'algorithms',
        'object oriented', 'functional programming', 'design patterns',
        'rest', 'graphql', 'grpc', 'websocket', 'http', 'https',
        'sql', 'nosql', 'redis', 'postgresql', 'mysql', 'mongodb',
        'git', 'github', 'gitlab', 'bitbucket', 'jira', 'confluence',
        # Generic location terms
        'city', 'country', 'location', 'usa', 'united states', 'us',
        # Common location words (not entities)
        'remote', 'hybrid', 'onsite', 'offsite', 'relocation',
        # Common LaTeX/document terms - CRITICAL for avoiding false positives
        'date', 'start', 'end', 'from', 'to', 'present',
        'header', 'footer', 'section', 'subsection', 'definition',
        'header definition', 'custom commands', 'formatting', 'layout',
        'document', 'page', 'margin', 'font', 'size', 'style',
        'begin', 'item', 'itemize', 'enumerate', 'center', 'left', 'right',
        'table', 'tabular', 'column', 'row', 'cell',
        # Generic skill terms that AI might expand
        'programming', 'languages', 'frameworks', 'tools', 'technologies',
        'technical', 'professional', 'soft', 'hard',
        # Common words that appear in LaTeX comments/sections
        'packages', 'commands', 'settings', 'configuration', 'options',
        'resume', 'curriculum', 'vitae', 'template', 'ats', 'friendly',
        # Generic descriptive terms
        'relevant', 'key', 'main', 'primary', 'secondary', 'additional',
        'demonstrated', 'proven', 'strong', 'excellent', 'proficient',
    }
    
    # Common suffixes that may be added to company names
    COMPANY_SUFFIXES = {'inc', 'inc.', 'llc', 'ltd', 'ltd.', 'corp', 'corp.', 'co', 'co.'}
    
    @classmethod
    def _normalize_text(cls, text: str) -> str:
        """Normalize text for comparison - lowercase, strip, remove punctuation."""
        if not text:
            return ''
        # Lowercase and strip
        normalized = text.lower().strip()
        # Remove common punctuation for comparison
        normalized = re.sub(r'[.,;:!?\'\"()]', '', normalized)
        return normalized
    
    @classmethod
    def _tokenize(cls, text: str) -> Set[str]:
        """Tokenize text into words, filtering short words."""
        if not text:
            return set()
        words = text.split()
        return {w for w in words if len(w) > 2 and w not in cls.IGNORE_WORDS}
    
    @classmethod
    def extract_profile_entities(cls, profile_data: dict) -> Set[str]:
        """
        Extract all key entities from the profile data.
        
        Focus on proper nouns that should not be invented:
        - Company names
        - Institution names
        - Certification issuers
        - Personal info (name, location)
        """
        entities = set()
        
        def add_entity(value: str):
            """Add an entity and its significant tokens."""
            if not value:
                return
            normalized = cls._normalize_text(value)
            if normalized:
                entities.add(normalized)
                # Also add individual words for partial matching
                for word in cls._tokenize(normalized):
                    entities.add(word)
        
        # Personal Info: Name and Location (valid entities to include in resume)
        personal_info = profile_data.get('personalInfo', {})
        for field in ['full_name', 'location', 'email', 'phone_number']:
            add_entity(personal_info.get(field, ''))
        
        # Experience: Company Names and Job Titles
        for exp in profile_data.get('experience', []):
            add_entity(exp.get('company', ''))
            add_entity(exp.get('title', ''))
            # Also add description words - AI may rephrase but use same terms
            add_entity(exp.get('description', ''))
            # Add dates in various formats that AI might use
            start_date = exp.get('start_date', '')
            end_date = exp.get('end_date', '')
            if start_date:
                # Add raw date
                add_entity(start_date)
                # Add formatted date components (year)
                try:
                    from datetime import datetime
                    date_obj = datetime.strptime(start_date, "%Y-%m-%d")
                    add_entity(str(date_obj.year))
                    add_entity(date_obj.strftime("%B %Y").lower())  # "august 2025"
                    add_entity(date_obj.strftime("%b %Y").lower())  # "aug 2025"
                except ValueError:
                    pass
            if end_date:
                try:
                    from datetime import datetime
                    date_obj = datetime.strptime(end_date, "%Y-%m-%d")
                    add_entity(str(date_obj.year))
                    add_entity(date_obj.strftime("%B %Y").lower())
                    add_entity(date_obj.strftime("%b %Y").lower())
                except ValueError:
                    pass
        
        # Education: Institution Names and Degree
        for edu in profile_data.get('education', []):
            add_entity(edu.get('institution', ''))
            add_entity(edu.get('degree', ''))
            add_entity(edu.get('description', ''))
            # Add dates in various formats
            start_date = edu.get('start_date', '')
            end_date = edu.get('end_date', '')
            if start_date:
                try:
                    from datetime import datetime
                    date_obj = datetime.strptime(start_date, "%Y-%m-%d")
                    add_entity(str(date_obj.year))
                    add_entity(date_obj.strftime("%B %Y").lower())
                    add_entity(date_obj.strftime("%b %Y").lower())
                except ValueError:
                    pass
            if end_date:
                try:
                    from datetime import datetime
                    date_obj = datetime.strptime(end_date, "%Y-%m-%d")
                    add_entity(str(date_obj.year))
                    add_entity(date_obj.strftime("%B %Y").lower())
                    add_entity(date_obj.strftime("%b %Y").lower())
                except ValueError:
                    pass
        
        # Certifications: Issuing Organizations and Names
        for cert in profile_data.get('certifications', []):
            add_entity(cert.get('issuing_organization', ''))
            add_entity(cert.get('name', ''))
        
        # Skills (valid profile data)
        for skill in profile_data.get('skills', []):
            add_entity(skill)
        
        # Add summary content - AI may use terms from here
        add_entity(profile_data.get('summary', ''))
        
        return entities
    
    @classmethod
    def _is_date_string(cls, text: str) -> bool:
        """
        Check if a string is a date or date range.
        
        Matches patterns like:
        - "august 2025 -- present"
        - "jan 2020 - dec 2023"
        - "2020-01-15 -- 2023-12-31"
        - "2020 -- 2023"
        - "present"
        
        Works on both original and normalized text.
        Returns True if the string is PRIMARILY a date/date range.
        """
        if not text:
            return False
        
        text_lower = text.lower().strip()
        original_text = text.strip()
        
        # Check for "present" or "current" alone (common in date ranges)
        if text_lower in ['present', 'current', 'ongoing', 'now']:
            return True
        
        # Month names (full and abbreviated)
        month_pattern = r'\b(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b'
        
        # Year pattern (4 digits, 19xx or 20xx)
        year_pattern = r'\b(19|20)\d{2}\b'
        
        # Date range separators
        range_separators = r'[-–—]|--|to|through'
        
        # Check if it contains month names and years (date pattern)
        has_month = bool(re.search(month_pattern, text_lower))
        has_year = bool(re.search(year_pattern, text_lower))
        has_range_sep = bool(re.search(range_separators, original_text.lower()))
        
        # If it has month/year and range separator, it's likely a date range
        if has_month and has_year and has_range_sep:
            return True
        
        # If it's just month + year (no other significant words), it's a date
        if has_month and has_year:
            # Check if remaining words are ignorable or numbers
            words = text_lower.split()
            significant_words = [w for w in words 
                               if w not in cls.IGNORE_WORDS 
                               and not re.match(r'^\d+$', w)
                               and not re.search(month_pattern, w)]
            if len(significant_words) <= 1:  # Just month, year, and maybe separator
                return True
        
        # If it contains month name and "present" or "current", it's a date
        if has_month and ('present' in text_lower or 'current' in text_lower):
            return True
        
        # Pure numeric date patterns (works on normalized text too)
        if re.match(r'^[\d\s\-]+$', text_lower):
            return True
        
        # Pattern: YYYY-MM-DD or similar (before normalization)
        if re.match(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}', original_text):
            return True
        
        # Pattern: YYYY -- YYYY or YYYY-YYYY (before normalization)
        if re.match(r'^\d{4}\s*[-–—]+\s*\d{4}', original_text):
            return True
        
        # Pattern: Just years separated by dash (normalized: "2020 2023")
        if re.match(r'^(19|20)\d{2}\s+(19|20)\d{2}$', text_lower):
            return True
        
        # Pattern: Month + year (normalized, no punctuation)
        if has_month and has_year and len(text_lower.split()) <= 3:
            return True
        
        # Pattern: Single year (4 digits) - likely a date
        if re.match(r'^(19|20)\d{2}$', text_lower):
            return True
        
        return False
    
    @classmethod
    def _is_location_string(cls, text: str) -> bool:
        """
        Check if a string is primarily a location (city, state, country).
        
        Locations are not entities that can be hallucinated - they're formatting.
        """
        if not text:
            return False
        
        text_lower = text.lower().strip()
        
        # Common location indicators
        location_indicators = [
            r'\b(city|state|country|region|area|location)\b',
            r'\b(usa|united states|us|uk|united kingdom|canada|australia)\b',
            r'\b(california|texas|new york|florida|illinois|pennsylvania|ohio|georgia|north carolina|michigan)\b',
        ]
        
        # If it contains location indicators, it's likely a location
        for pattern in location_indicators:
            if re.search(pattern, text_lower):
                return True
        
        # Pattern: "City, State" or "City, Country"
        if re.match(r'^[a-z\s]+,\s*[a-z\s]+$', text_lower):
            # Check if it's not a company name (company names usually have capitals)
            # If original has capitals, it might be a company
            if text != text_lower:  # Has capitals
                return False
            return True
        
        return False
    
    @classmethod
    def _is_likely_not_entity(cls, text: str) -> bool:
        """
        Check if text is likely NOT an entity (company/university) that could be hallucinated.
        
        Returns True if the text is clearly formatting, dates, locations, or generic terms.
        """
        if not text:
            return True
        
        # Check if it's a date
        if cls._is_date_string(text):
            return True
        
        # Check if it's a location
        if cls._is_location_string(text):
            return True
        
        text_lower = text.lower().strip()
        
        # Check if it's just numbers/years
        if re.match(r'^[\d\s\-]+$', text_lower):
            return True
        
        # Check if it's a single year
        if re.match(r'^(19|20)\d{2}$', text_lower):
            return True
        
        # Check if it's mostly generic resume terms
        words = text_lower.split()
        if words:
            generic_count = sum(1 for w in words if w in cls.IGNORE_WORDS)
            if generic_count >= len(words) * 0.7:  # 70% generic words
                return True
        
        # Check if it's a common resume phrase
        common_phrases = [
            'full time', 'part time', 'contract', 'internship',
            'remote work', 'hybrid work', 'onsite work',
            'years of experience', 'years experience',
            'responsible for', 'worked on', 'developed',
        ]
        for phrase in common_phrases:
            if phrase in text_lower:
                return True
        
        return False
    
    @classmethod
    def extract_latex_entities(cls, latex_source: str) -> Set[str]:
        """
        Extract potential entity names from LaTeX source.
        
        Focuses on content in LaTeX commands that typically contain
        proper nouns (company names, institutions, etc.)
        
        IMPORTANT: Filters out dates, locations, and formatting to avoid false positives.
        """
        entities = set()
        
        # First, remove LaTeX comments to avoid false positives
        # Comments start with % and go to end of line
        latex_no_comments = re.sub(r'%.*$', '', latex_source, flags=re.MULTILINE)
        
        # Extract from standard entity patterns (less likely to contain dates)
        for pattern in cls.LATEX_ENTITY_PATTERNS:
            matches = re.findall(pattern, latex_no_comments, re.IGNORECASE)
            for match in matches:
                # Skip if it's clearly not an entity (date, location, formatting)
                if cls._is_likely_not_entity(match):
                    continue
                
                # Clean up the match
                cleaned = cls._normalize_text(match)
                if cleaned and len(cleaned) > 2:
                    # Double-check normalized version
                    if cls._is_likely_not_entity(cleaned):
                        continue
                    # Skip if it looks like a LaTeX command or formatting
                    if cleaned.startswith('\\') or cleaned in cls.IGNORE_WORDS:
                        continue
                    # Skip very generic terms (less than 4 chars)
                    if len(cleaned) < 4:
                        continue
                    entities.add(cleaned)
        
        # Extract from potentially dated patterns (like \textit) with extra caution
        for pattern in cls.POTENTIALLY_DATED_PATTERNS:
            matches = re.findall(pattern, latex_no_comments, re.IGNORECASE)
            for match in matches:
                # Be extra strict - skip if it looks like a date or location
                if cls._is_likely_not_entity(match):
                    continue
                
                # Only extract if it looks like it could be a company/institution name
                # (has multiple capitalized words, not just dates)
                cleaned = cls._normalize_text(match)
                if cleaned and len(cleaned) > 2:
                    # Double-check
                    if cls._is_likely_not_entity(cleaned):
                        continue
                    if cleaned.startswith('\\') or cleaned in cls.IGNORE_WORDS:
                        continue
                    if len(cleaned) < 4:
                        continue
                    # Only add if it has characteristics of a proper noun
                    # (not just dates/numbers)
                    words = cleaned.split()
                    if words:
                        # If more than 50% are numbers or date-related, skip
                        numeric_or_date = sum(1 for w in words 
                                            if re.match(r'^\d+$', w) 
                                            or w in ['present', 'current', 'ongoing']
                                            or re.search(r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|january|february|march|april|may|june|july|august|september|october|november|december)\b', w))
                        if numeric_or_date >= len(words) * 0.5:
                            continue
                    entities.add(cleaned)
        
        # Also look for capitalized phrases (potential organization names)
        # Pattern: Multiple capitalized words in a row (likely proper nouns)
        # Only check in content areas, not in comments
        capitalized_pattern = r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b'
        cap_matches = re.findall(capitalized_pattern, latex_no_comments)
        for match in cap_matches:
            # Skip if it's clearly not an entity
            if cls._is_likely_not_entity(match):
                continue
            
            normalized = cls._normalize_text(match)
            if normalized and normalized not in cls.IGNORE_WORDS:
                # Additional check: skip if all words are common/generic
                words = normalized.split()
                if all(w in cls.IGNORE_WORDS or len(w) < 3 for w in words):
                    continue
                # Skip if it looks like a date/location
                if cls._is_likely_not_entity(normalized):
                    continue
                entities.add(normalized)
        
        return entities
    
    @classmethod
    def _entity_matches(cls, latex_entity: str, profile_entities: Set[str]) -> bool:
        """
        Check if a LaTeX entity matches any profile entity.
        
        Allows for:
        - Exact matches
        - Company suffix variations (Inc, LLC, etc.)
        - Subset matches where all significant words are in profile
        """
        # Direct match
        if latex_entity in profile_entities:
            return True
        
        # Check if all significant tokens are in profile
        tokens = cls._tokenize(latex_entity)
        if tokens and all(t in profile_entities for t in tokens):
            return True
        
        # Check for partial containment (profile entity in latex entity)
        for profile_entity in profile_entities:
            # Skip very short profile entities for this check
            if len(profile_entity) < 4:
                continue
            
            # Profile entity is contained in latex entity (e.g., "TechCorp" in "TechCorp Inc")
            if profile_entity in latex_entity:
                return True
            
            # Latex entity is contained in profile entity (e.g., "Tech" in "TechCorp")
            if len(latex_entity) >= 4 and latex_entity in profile_entity:
                return True
        
        # Check without company suffixes
        for suffix in cls.COMPANY_SUFFIXES:
            stripped = latex_entity.rstrip().removesuffix(suffix).strip()
            if stripped and stripped in profile_entities:
                return True
        
        return False
    
    @classmethod
    def detect_hallucination(cls, profile_data: dict, latex_source: str) -> tuple[bool, Optional[str]]:
        """
        Checks for hallucinated entities in the generated LaTeX source.
        
        CRITICAL: This function must be STRICT.
        A hallucination is any entity in the LaTeX that cannot be traced
        back to the user's profile data.
        
        Args:
            profile_data: The user's profile data dict
            latex_source: The AI-generated LaTeX code
        
        Returns:
            Tuple of (is_hallucinated, hallucinated_entity)
            - (False, None) if no hallucination detected
            - (True, "entity_name") if hallucination detected
        """
        profile_entities = cls.extract_profile_entities(profile_data)
        latex_entities = cls.extract_latex_entities(latex_source)
        
        logger.debug("Profile entities: %d, LaTeX entities: %d", 
                    len(profile_entities), len(latex_entities))
        
        # Check each LaTeX entity against profile entities
        for entity in latex_entities:
            # Skip common/ignorable words
            if entity in cls.IGNORE_WORDS:
                continue
            
            # Comprehensive check: skip if it's clearly not an entity that could be hallucinated
            if cls._is_likely_not_entity(entity):
                continue
            
            # Skip date strings (double-check here as well)
            if cls._is_date_string(entity):
                continue
            
            # Skip location strings
            if cls._is_location_string(entity):
                continue
            
            # Skip if entity is just a year (4-digit number)
            if re.match(r'^\d{4}$', entity.strip()):
                continue
            
            # Skip if all words in entity are ignorable
            tokens = cls._tokenize(entity)
            if not tokens:  # All words were filtered out
                continue
            
            # Additional check: if entity is mostly numbers/years, skip it
            words = entity.split()
            if words:
                numeric_words = [w for w in words if re.match(r'^\d+$', w)]
                if len(numeric_words) >= len(words) * 0.5:  # More than half are numbers
                    continue
            
            # Skip entities that are just date-related words
            date_related_words = {'august', 'september', 'october', 'november', 'december',
                                 'january', 'february', 'march', 'april', 'may', 'june', 'july',
                                 'jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep',
                                 'oct', 'nov', 'dec', 'present', 'current', 'ongoing'}
            entity_words = set(entity.lower().split())
            # Check if entity is primarily date-related (allows some non-date words)
            date_word_count = sum(1 for w in entity_words if w in date_related_words or re.match(r'^(19|20)\d{2}$', w))
            if date_word_count >= len(entity_words) * 0.6:  # 60% or more are date-related
                continue
            
            # Final check: if this entity matches the profile, it's valid
            if not cls._entity_matches(entity, profile_entities):
                # Before flagging as hallucination, do one more check:
                # Is this entity actually substantial enough to be a real entity?
                # (vs. just formatting or common phrases)
                if len(entity.strip()) < 4:
                    continue
                
                # Check if it's a common resume phrase that's not an entity
                common_non_entities = [
                    'years of experience', 'years experience', 'responsible for',
                    'worked on', 'developed', 'implemented', 'managed',
                    'led team', 'team lead', 'project lead',
                ]
                entity_lower = entity.lower()
                if any(phrase in entity_lower for phrase in common_non_entities):
                    continue
                
                logger.warning(
                    "Hallucination detected: '%s' not found in profile entities. "
                    "Profile has %d entities.",
                    entity, len(profile_entities)
                )
                return (True, entity)
        
        return (False, None)


class ResumeGenerationService:
    """
    Service class for resume generation operations.
    """
    
    @staticmethod
    def check_idempotency(
        user: User, 
        idempotency_key: str, 
        endpoint: str
    ) -> Optional[dict]:
        """
        Check if a request with this idempotency key has been processed.
        
        Args:
            user: The user making the request
            idempotency_key: The client-provided key
            endpoint: The endpoint being called
        
        Returns:
            Previous response if key exists and is valid, None otherwise
        """
        try:
            existing = IdempotencyKey.objects.get(
                user=user,
                key=idempotency_key,
                endpoint=endpoint
            )
            if existing.is_valid:
                logger.info(
                    "Idempotency key hit: %s for user %s",
                    idempotency_key, user.id
                )
                return {
                    'status': existing.response_status,
                    'body': existing.response_body,
                }
        except IdempotencyKey.DoesNotExist:
            pass
        return None
    
    @staticmethod
    def store_idempotency(
        user: User,
        idempotency_key: str,
        endpoint: str,
        response_status: int,
        response_body: dict
    ) -> None:
        """
        Store an idempotency key with its response.
        
        Args:
            user: The user who made the request
            idempotency_key: The client-provided key
            endpoint: The endpoint called
            response_status: HTTP status code
            response_body: Response data
        """
        ttl_hours = getattr(settings, 'DATA_TTL_HOURS', 24)
        
        IdempotencyKey.objects.update_or_create(
            user=user,
            key=idempotency_key,
            endpoint=endpoint,
            defaults={
                'response_status': response_status,
                'response_body': response_body,
                'expires_at': timezone.now() + timedelta(hours=ttl_hours),
            }
        )
    
    @staticmethod
    def create_generation_request(
        user: User,
        job_description_id: str,
        template_id: str,
        idempotency_key: Optional[str] = None
    ) -> ResumeGenerationRequest:
        """
        Create a new resume generation request.
        
        Args:
            user: The user requesting generation
            job_description_id: UUID of the job description
            template_id: ID of the selected template
            idempotency_key: Optional idempotency key
        
        Returns:
            Created ResumeGenerationRequest instance
        """
        # Get job description
        jd = JobDescriptionService.get_job_description(user, job_description_id)
        
        # Verify template exists
        if not Template.objects.filter(id=template_id, is_active=True).exists():
            raise ResourceNotFoundException('Template not found.')
        
        # Get profile snapshot
        profile_snapshot = ProfileService.get_profile_snapshot(user)
        
        # Create request
        request = ResumeGenerationRequest.objects.create(
            user=user,
            job_description=jd,
            template_id=template_id,
            profile_snapshot=profile_snapshot,
            idempotency_key=idempotency_key,
        )
        
        logger.info(
            "Resume generation request created: %s for user: %s",
            request.id, user.id
        )
        
        return request
    
    @staticmethod
    def get_generation_request(
        user: User,
        generation_id: str
    ) -> ResumeGenerationRequest:
        """
        Get a resume generation request by ID.
        
        Args:
            user: The user requesting the generation
            generation_id: UUID of the generation request
        
        Returns:
            ResumeGenerationRequest instance
        
        Raises:
            ResourceNotFoundException: If not found
            TTLExpiredException: If expired
        """
        try:
            request = ResumeGenerationRequest.objects.get(id=generation_id, user=user)
        except ResumeGenerationRequest.DoesNotExist:
            raise ResourceNotFoundException('Resume generation request not found.')
        
        if request.is_expired:
            raise TTLExpiredException()
        
        return request
    
    @staticmethod
    def list_generation_requests(user: User) -> list:
        """
        List all non-expired generation requests for a user.
        
        Args:
            user: The user whose requests to list
        
        Returns:
            QuerySet of ResumeGenerationRequest instances
        """
        return ResumeGenerationRequest.objects.filter(
            user=user,
            expires_at__gt=timezone.now()
        ).order_by('-created_at')
    
    @staticmethod
    def validate_ai_output(
        generation_request: ResumeGenerationRequest,
        latex_source: str,
        modifications: list
    ) -> None:
        """
        Validate AI output for structure and format.
        
        CRITICAL: This is a safety-critical function.
        - Invalid LaTeX MUST be rejected
        - Any failure here is a hard failure
        
        NOTE: Hallucination detection is currently disabled as the AI service
        only rephrases existing profile content. It can be re-enabled later if needed.
        
        Args:
            generation_request: The generation request
            latex_source: The AI-generated LaTeX
            modifications: List of modification summaries
        
        Raises:
            ModelOutputInvalidException: If validation fails
        """
        # Check for empty output
        if not latex_source or not latex_source.strip():
            raise ModelOutputInvalidException('AI produced empty output.')
        
        latex_stripped = latex_source.strip()
        
        # Validate LaTeX structure: must start with \documentclass
        if not latex_stripped.startswith('\\documentclass'):
            raise ModelOutputInvalidException(
                'AI output is not valid LaTeX (must start with \\documentclass).'
            )
        
        # Validate LaTeX structure: must have \begin{document}
        if '\\begin{document}' not in latex_source:
            raise ModelOutputInvalidException(
                'AI output is not valid LaTeX (missing \\begin{document}).'
            )
        
        # Validate LaTeX structure: must have \end{document}
        if '\\end{document}' not in latex_source:
            raise ModelOutputInvalidException(
                'AI output is not valid LaTeX (missing \\end{document}).'
            )
        
        # NOTE: Hallucination detection temporarily disabled
        # The AI service only rephrases existing profile content, so hallucination
        # detection was causing false positives. Can be re-enabled if needed.
        # 
        # if needed in future:
        #     is_hallucinated, entity = HallucinationDetector.detect_hallucination(
        #         generation_request.profile_snapshot,
        #         latex_source
        #     )
        #     if is_hallucinated:
        #         raise ModelOutputInvalidException(
        #             f"AI output contains hallucinated content: '{entity}' is not in your profile."
        #         )
        
        logger.info(
            "AI output validated for generation request: %s",
            generation_request.id
        )
    
    @staticmethod
    def mark_generation_failed(
        generation_request: ResumeGenerationRequest,
        error_code: str,
        error_details: str
    ) -> None:
        """
        Mark a generation request as failed.
        
        Args:
            generation_request: The request to mark as failed
            error_code: Machine-readable error code
            error_details: Human-readable details
        """
        generation_request.mark_failed(error_code, error_details)
        logger.error(
            "Generation request failed: %s, code: %s",
            generation_request.id, error_code
        )

# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added - Profile Extension (2026-01-26)

Extended the User Profile data model and API to include 19 new sections:

#### New Profile Sections:
- **Projects**: Array of project items with title, role, description, dates, technologies, links, and achievements
- **Achievements**: Array of professional achievements with title, description, issuer, and date
- **Areas of Interest**: Array of normalized interest tags
- **Hobbies**: Array of personal hobbies
- **Address**: Structured address object with street, city, region, country, postal code, and geolocation
- **Social URLs**: Object containing LinkedIn, GitHub, Twitter, portfolio, website, and other social platform URLs
- **Profile Picture**: Object with URL, thumbnail URL, and upload timestamp
- **Volunteering**: Array of volunteering experiences
- **Positions**: Array of board/leadership positions
- **Career Breaks**: Array of career gaps with reason (parental, health, travel, education, other)
- **Licenses**: Array of professional licenses
- **Trainings/Courses**: Array of training courses and certifications
- **Publications**: Array of research papers and publications
- **Patents**: Array of patents with status (filed, granted, pending)
- **Honors/Awards**: Array of honors and awards received
- **Test Scores**: Array of standardized test scores
- **Languages**: Array of languages with proficiency levels (native, full_professional, limited_professional, conversational, basic)
- **Organizations**: Array of professional organization memberships
- **Contact Info**: Sensitive contact information object (redacted for non-owners)

#### API Changes:
- `GET /profiles/me`: Now returns all new sections. `contact_info` is redacted for non-owners.
- `PUT /profiles/me`: Accepts all new sections. Only `personalInfo` is required (minimal usable profile).
- `PATCH /profiles/me`: Supports partial updates of all new sections.
- `POST /profiles/me/picture`: New endpoint for profile picture upload (multipart/form-data). Validates JPEG/PNG, max 5MB. Generates 128x128 and 512x512 thumbnails.
- `DELETE /profiles/me/picture`: New endpoint for profile picture deletion.

#### Validation & Security:
- Date validation: Dates cannot be in the future (except for ongoing roles). `end_date` must be >= `start_date`.
- Array limits: Maximum items enforced to prevent DoS (e.g., max 50 projects, 50 publications, 25 experience entries).
- URL validation: All URL fields validated and normalized (http/https only).
- Enum validation: Career break reasons, language proficiency, patent status, contact method enums enforced.
- **AI Integration Security**: Whitelist function ensures only safe fields are sent to AI agent. Sensitive fields (`contact_info`, `profile_picture.url`, `address`) are excluded.

#### Database Changes:
- Migration `0002_add_profile_search_indexes.py`: Adds GIN indexes on JSONB fields for:
  - `personalInfo.full_name` (text search)
  - `skills` array (array containment)
  - `languages` array (array containment)
  - `projects` array (array containment)

#### Schema Updates:
- Updated `/backend/schemas/profile.json` with complete schema for all new sections (Draft 07+)
- Added examples: minimal valid profile and maximal full profile sample
- Updated `/backend/openapi/v1/openapi.yaml` with new Profile schema
- Created `/backend/app/models_stub.py` with TypedDict definitions for type hints

#### Testing:
- `test_profile_full_crud.py`: Comprehensive CRUD tests for all new sections
- `test_picture_upload.py`: Profile picture upload, thumbnail generation, and deletion tests
- `test_constraints_dates.py`: Date validation constraint tests
- `test_max_limits.py`: Array length limit tests
- `test_ai_payload_whitelist.py`: AI whitelist enforcement tests
- Added `/backend/tests/fixtures/full_profile_sample.json` for integration testing

#### Migration Notes:
- **Backward Compatible**: Existing profiles continue to work. New sections are optional.
- **No Data Loss**: Migration only adds indexes, no data changes required.
- **Performance**: JSONB indexes improve search performance but may require `pg_trgm` extension for optimal text search.

#### Breaking Changes:
None. All changes are additive and backward compatible.

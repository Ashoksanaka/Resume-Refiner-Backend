# Generated migration for profile search indexes
# 
# Migration Notes:
# - Adds GIN indexes on JSONB fields for common search operations
# - Indexes on: full_name, skills, languages.language, projects.title
# - These indexes improve query performance for profile searches
# - Uses PostgreSQL-specific JSONB operators for efficient searching

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('profiles', '0001_initial'),
    ]

    operations = [
        # Add GIN index on full_name for text search (using simple GIN, not trigram)
        migrations.RunSQL(
            sql="""
                CREATE INDEX IF NOT EXISTS profiles_data_personalinfo_full_name_idx 
                ON profiles ((data->'personalInfo'->>'full_name'));
            """,
            reverse_sql="""
                DROP INDEX IF EXISTS profiles_data_personalinfo_full_name_idx;
            """
        ),
        # Add GIN index on skills array for array containment searches
        migrations.RunSQL(
            sql="""
                CREATE INDEX IF NOT EXISTS profiles_data_skills_gin_idx 
                ON profiles USING GIN ((data->'skills'));
            """,
            reverse_sql="""
                DROP INDEX IF EXISTS profiles_data_skills_gin_idx;
            """
        ),
        # Add GIN index on languages array for language searches
        migrations.RunSQL(
            sql="""
                CREATE INDEX IF NOT EXISTS profiles_data_languages_gin_idx 
                ON profiles USING GIN ((data->'languages'));
            """,
            reverse_sql="""
                DROP INDEX IF EXISTS profiles_data_languages_gin_idx;
            """
        ),
        # Add GIN index on projects array for project title searches
        migrations.RunSQL(
            sql="""
                CREATE INDEX IF NOT EXISTS profiles_data_projects_gin_idx 
                ON profiles USING GIN ((data->'projects'));
            """,
            reverse_sql="""
                DROP INDEX IF EXISTS profiles_data_projects_gin_idx;
            """
        ),
        # Note: For production, consider adding pg_trgm extension for better text search:
        # CREATE EXTENSION IF NOT EXISTS pg_trgm;
        # The above indexes will work but may require the extension for optimal performance.
    ]

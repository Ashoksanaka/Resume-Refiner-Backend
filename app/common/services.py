"""
Common services for the Resume AI platform.

Includes template synchronization from the filesystem template store.
"""

import logging
from datetime import datetime
from typing import Optional
from django.db import transaction
from asgiref.sync import sync_to_async
from app.common.models import Template
from app.common.clients.latex_service import latex_service_client
from app.common.exceptions import LatexServiceException

logger = logging.getLogger(__name__)


class TemplateSyncService:
    """
    Service for synchronizing templates from filesystem to database.

    app/latex/templates/ is the source of truth for templates.
    This service syncs template metadata to the database for:
    - Fast lookups
    - Relational integrity (foreign keys from resume generation requests)
    - Caching with version-based invalidation
    """

    @staticmethod
    async def sync_templates() -> dict:
        """
        Synchronize all templates from filesystem to database.

        Returns:
            Dict with sync results (created, updated, deactivated counts)
        """
        logger.info("Starting template sync from filesystem")

        try:
            templates = await latex_service_client.list_templates()
        except Exception as e:
            logger.error("Failed to load templates from filesystem: %s", str(e))
            raise

        existing_ids = set(await sync_to_async(list)(Template.objects.values_list('id', flat=True)))

        @sync_to_async
        def process_templates_sync(templates_list, existing_template_ids):
            created_count = 0
            updated_count = 0
            deactivated_count = 0
            fetched_ids = set()

            with transaction.atomic():
                for template_info in templates_list:
                    fetched_ids.add(template_info.id)

                    preview_generated_at = None
                    if template_info.preview_generated_at:
                        try:
                            preview_generated_at = datetime.fromisoformat(
                                template_info.preview_generated_at.replace('Z', '+00:00')
                            )
                        except ValueError:
                            pass

                    template, created = Template.objects.update_or_create(
                        id=template_info.id,
                        defaults={
                            'name': template_info.name,
                            'description': template_info.description,
                            'author': template_info.author,
                            'version': template_info.version,
                            'default_filename': template_info.default_filename,
                            'has_preview': template_info.has_preview,
                            'preview_generated_at': preview_generated_at,
                            'is_active': True,
                        }
                    )

                    if created:
                        created_count += 1
                        logger.info("Created template: %s (v%s)", template.id, template.version)
                    else:
                        updated_count += 1
                        logger.debug("Updated template: %s (v%s)", template.id, template.version)

                templates_to_deactivate = existing_template_ids - fetched_ids
                if templates_to_deactivate:
                    deactivated_count = Template.objects.filter(
                        id__in=templates_to_deactivate
                    ).update(is_active=False)
                    logger.info("Deactivated %d templates: %s", deactivated_count, templates_to_deactivate)

            return created_count, updated_count, deactivated_count

        created_count, updated_count, deactivated_count = await process_templates_sync(templates, existing_ids)

        logger.info(
            "Template sync completed: %d created, %d updated, %d deactivated",
            created_count, updated_count, deactivated_count
        )

        return {
            'created': created_count,
            'updated': updated_count,
            'deactivated': deactivated_count,
            'total': len(templates)
        }

    @staticmethod
    async def sync_single_template(template_id: str) -> Optional[Template]:
        """
        Sync a single template from filesystem.

        Args:
            template_id: ID of the template to sync

        Returns:
            Updated Template instance or None if not found
        """
        logger.info("Syncing single template: %s", template_id)

        try:
            template_info = await latex_service_client.get_template(template_id)
        except Exception as e:
            logger.error("Failed to load template %s: %s", template_id, str(e))
            return None

        preview_generated_at = None
        if template_info.preview_generated_at:
            try:
                preview_generated_at = datetime.fromisoformat(
                    template_info.preview_generated_at.replace('Z', '+00:00')
                )
            except ValueError:
                pass

        @sync_to_async
        def update_template():
            return Template.objects.update_or_create(
                id=template_info.id,
                defaults={
                    'name': template_info.name,
                    'description': template_info.description,
                    'author': template_info.author,
                    'version': template_info.version,
                    'default_filename': template_info.default_filename,
                    'has_preview': template_info.has_preview,
                    'preview_generated_at': preview_generated_at,
                    'is_active': True,
                }
            )

        template, created = await update_template()

        action = "Created" if created else "Updated"
        logger.info("%s template: %s (v%s)", action, template.id, template.version)

        return template

    @staticmethod
    async def generate_preview(template_id: str) -> dict:
        """
        Generate preview for a template.

        Preview generation via FormaTeX is not implemented; add preview files
        to app/latex/templates/<id>/ manually or implement FormaTeX preview compile.
        """
        logger.info("Preview generation requested for template: %s", template_id)
        raise LatexServiceException(
            "Template preview generation is not available without the LaTeX microservice. "
            "Place preview.pdf and preview.png in the template directory, or implement "
            "FormaTeX-based preview generation."
        )

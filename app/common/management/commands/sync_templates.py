"""
Django management command to sync templates from filesystem.

Usage:
    python manage.py sync_templates
    python manage.py sync_templates --generate-previews
    python manage.py sync_templates --template-id=main
"""

import asyncio
import logging
from django.core.management.base import BaseCommand, CommandError
from app.common.services import TemplateSyncService
from app.common.models import Template

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Sync templates from filesystem to database'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--generate-previews',
            action='store_true',
            help='Generate previews for templates that don\'t have them',
        )
        parser.add_argument(
            '--template-id',
            type=str,
            help='Sync a specific template by ID',
        )
        parser.add_argument(
            '--force-preview',
            action='store_true',
            help='Force regenerate previews even if they exist',
        )
    
    def handle(self, *args, **options):
        template_id = options.get('template_id')
        generate_previews = options.get('generate_previews')
        force_preview = options.get('force_preview')
        
        try:
            # Ensure we're not in an async context - create a new event loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    raise RuntimeError("Cannot run async code in running event loop")
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            try:
                if template_id:
                    # Sync single template
                    self.stdout.write(f"Syncing template: {template_id}")
                    result = loop.run_until_complete(self._sync_single(template_id, generate_previews or force_preview))
                else:
                    # Sync all templates
                    self.stdout.write("Syncing all templates from filesystem...")
                    result = loop.run_until_complete(self._sync_all(generate_previews, force_preview))
                
                self.stdout.write(self.style.SUCCESS(
                    f"Sync completed: {result}"
                ))
            finally:
                loop.close()
            
        except Exception as e:
            raise CommandError(f"Template sync failed: {str(e)}")
    
    async def _sync_all(self, generate_previews: bool, force_preview: bool) -> dict:
        """Sync all templates."""
        from asgiref.sync import sync_to_async
        
        result = await TemplateSyncService.sync_templates()
        
        if generate_previews:
            # Get templates using sync_to_async
            @sync_to_async
            def get_active_templates():
                return list(Template.objects.filter(is_active=True).values_list('id', 'has_preview', flat=False))
            
            templates_data = await get_active_templates()
            preview_results = []
            
            for template_id, has_preview in templates_data:
                if force_preview or not has_preview:
                    self.stdout.write(f"  Generating preview for: {template_id}")
                    try:
                        await TemplateSyncService.generate_preview(template_id)
                        preview_results.append((template_id, True))
                        self.stdout.write(self.style.SUCCESS(f"    Preview generated for {template_id}"))
                    except Exception as e:
                        preview_results.append((template_id, False))
                        self.stdout.write(self.style.ERROR(f"    Failed: {str(e)}"))
            
            result['previews_generated'] = len([r for r in preview_results if r[1]])
            result['previews_failed'] = len([r for r in preview_results if not r[1]])
        
        return result
    
    async def _sync_single(self, template_id: str, generate_preview: bool) -> dict:
        """Sync a single template."""
        template = await TemplateSyncService.sync_single_template(template_id)
        
        if not template:
            raise CommandError(f"Template '{template_id}' not found on filesystem")
        
        result = {
            'template_id': template.id,
            'name': template.name,
            'version': template.version,
            'has_preview': template.has_preview
        }
        
        if generate_preview:
            self.stdout.write(f"  Generating preview for: {template_id}")
            try:
                await TemplateSyncService.generate_preview(template_id)
                result['preview_generated'] = True
                self.stdout.write(self.style.SUCCESS(f"    Preview generated"))
            except Exception as e:
                result['preview_generated'] = False
                result['preview_error'] = str(e)
                self.stdout.write(self.style.ERROR(f"    Failed: {str(e)}"))
        
        return result

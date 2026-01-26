# Generated manually for Template model updates

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='template',
            name='latex_file',
        ),
        migrations.RemoveField(
            model_name='template',
            name='thumbnail_url',
        ),
        migrations.AddField(
            model_name='template',
            name='author',
            field=models.CharField(blank=True, help_text='Template author', max_length=255),
        ),
        migrations.AddField(
            model_name='template',
            name='version',
            field=models.CharField(default='1.0.0', help_text='Semantic version (X.Y.Z) for cache invalidation', max_length=20),
        ),
        migrations.AddField(
            model_name='template',
            name='default_filename',
            field=models.CharField(default='resume', help_text='Default filename for generated PDFs', max_length=100),
        ),
        migrations.AddField(
            model_name='template',
            name='has_preview',
            field=models.BooleanField(default=False, help_text='Whether preview images are available'),
        ),
        migrations.AddField(
            model_name='template',
            name='preview_generated_at',
            field=models.DateTimeField(blank=True, help_text='When the preview was last generated', null=True),
        ),
    ]

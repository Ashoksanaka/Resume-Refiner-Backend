from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('resumes', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='jobdescription',
            name='role_name',
            field=models.CharField(
                default='',
                help_text='Target role title for this job description',
                max_length=200,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='resumegenerationrequest',
            name='selected_sections',
            field=models.JSONField(
                blank=True,
                default=list,
                help_text='Profile section keys included in this generation',
            ),
        ),
        migrations.AddField(
            model_name='resumegenerationrequest',
            name='celery_task_id',
            field=models.CharField(
                blank=True,
                help_text='Celery task ID for cancellation',
                max_length=255,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name='resumegenerationrequest',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('processing', 'Processing'),
                    ('success', 'Success'),
                    ('failed', 'Failed'),
                    ('cancelled', 'Cancelled'),
                ],
                db_index=True,
                default='pending',
                max_length=20,
            ),
        ),
    ]

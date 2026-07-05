import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('profiles', '0002_add_profile_search_indexes'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProfileSaveEvent',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('sections', models.JSONField(help_text='Top-level profile section keys saved in this event')),
                ('saved_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='profile_save_events', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'profile_save_events',
                'ordering': ['-saved_at'],
                'indexes': [models.Index(fields=['user', '-saved_at'], name='profile_sav_user_id_6a8f2d_idx')],
            },
        ),
    ]

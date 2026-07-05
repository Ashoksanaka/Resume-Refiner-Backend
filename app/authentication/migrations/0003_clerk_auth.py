# Generated manually for Clerk migration

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('authentication', '0002_passwordresettoken'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='clerk_id',
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text='Clerk user ID (sub claim from session JWT).',
                max_length=255,
                null=True,
                unique=True,
            ),
        ),
        migrations.AddIndex(
            model_name='user',
            index=models.Index(fields=['clerk_id'], name='users_clerk_i_8a1b2c_idx'),
        ),
        migrations.DeleteModel(
            name='EmailVerificationToken',
        ),
        migrations.DeleteModel(
            name='PasswordResetToken',
        ),
    ]

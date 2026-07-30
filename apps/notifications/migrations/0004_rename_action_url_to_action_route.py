from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0003_alter_notification_type"),
    ]

    operations = [
        migrations.RenameField(
            model_name="notification",
            old_name="action_url",
            new_name="action_route",
        ),
    ]

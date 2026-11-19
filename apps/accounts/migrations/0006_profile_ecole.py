from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0005_profile_phone_unique"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="ecole",
            field=models.CharField(
                blank=True, default="", help_text="École de l'apprenant", max_length=150
            ),
        ),
    ]

from django.db import migrations


def seed_url_base_frontend(apps, schema_editor):
    """
    P2.1 : `Repetiteur.lien_whatsapp` doit inclure un lien vers le profil de
    l'enseignant. Aucune convention de lien de profil (web ou deep link)
    n'existe encore côté frontend — la base d'URL est donc, elle aussi, un
    paramètre configurable sans redéploiement plutôt qu'une valeur en dur.
    Valeur volontairement vide : à renseigner par l'administrateur général
    une fois le schéma de lien de profil défini côté frontend.
    """
    ParametreSysteme = apps.get_model('core', 'ParametreSysteme')
    ParametreSysteme.objects.get_or_create(
        cle='url_base_frontend',
        defaults={
            'valeur': '',
            'description': (
                "Base d'URL du frontend (ex: https://yeki-84b1a.web.app) "
                "utilisée pour construire des liens de profil "
                "(`{url_base_frontend}/profil/<id>`). À renseigner par "
                "l'administrateur général."
            ),
        },
    )


def revert_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_parametresysteme'),
    ]

    operations = [
        migrations.RunPython(seed_url_base_frontend, revert_noop),
    ]

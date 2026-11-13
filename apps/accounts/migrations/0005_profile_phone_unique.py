"""
Numéro de téléphone unique (identifiant de connexion).

Avant d'ajouter la contrainte, les numéros existants sont normalisés
(chiffres seuls, sans indicatif +237 / 00237), comme le fait désormais
l'inscription. Si deux comptes avaient le même numéro, seul le plus ancien
le garde ; il est retiré des autres (ils peuvent toujours se connecter
avec leur nom d'utilisateur ou leur e-mail, et le saisir à nouveau depuis
leur profil).
"""

from django.db import migrations, models


def _normaliser(numero):
    chiffres = "".join(c for c in (numero or "") if c.isdigit())
    for prefixe in ("00237", "237"):
        if chiffres.startswith(prefixe) and len(chiffres) > 9:
            return chiffres[len(prefixe) :]
    return chiffres


def normaliser_et_dedoublonner(apps, schema_editor):
    Profile = apps.get_model("accounts", "Profile")
    vus = set()
    for profil in Profile.objects.exclude(phone="").order_by("id"):
        numero = _normaliser(profil.phone)
        if numero in vus:
            numero = ""
        elif numero:
            vus.add(numero)
        if numero != profil.phone:
            profil.phone = numero
            profil.save(update_fields=["phone"])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_profile_date_naissance"),
    ]

    operations = [
        migrations.RunPython(normaliser_et_dedoublonner, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="profile",
            constraint=models.UniqueConstraint(
                condition=~models.Q(phone=""),
                fields=("phone",),
                name="yeki_profile_phone_unique",
                violation_error_message="Ce numéro de téléphone est déjà utilisé.",
            ),
        ),
    ]

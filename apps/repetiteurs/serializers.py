from rest_framework import serializers

from apps.accounts.services import _nom_profil
from apps.repetiteurs.models import Repetiteur


class RepetiteurSerializer(serializers.ModelSerializer):
    """P9.5 : sérialiseur CRUD pour la gestion des fiches répétiteur par le
    Service Client (basculer is_repetiteur, ajouter/retirer d'un cours,
    éditer ville et tarif) — n'existait pas avant ce ticket."""

    nom = serializers.SerializerMethodField()
    cours_titre = serializers.CharField(source="cours.titre", read_only=True)
    matiere = serializers.CharField(source="cours.matiere", read_only=True)

    class Meta:
        model = Repetiteur
        fields = [
            "id",
            "enseignant",
            "nom",
            "cours",
            "cours_titre",
            "matiere",
            "ville",
            "telephone",
            "disponible",
            "tarif_mensuel",
            "note_moyenne",
            "created_at",
        ]
        read_only_fields = ["id", "note_moyenne", "created_at"]

    def get_nom(self, obj):
        return _nom_profil(obj.enseignant)

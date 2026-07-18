from rest_framework import serializers

from apps.accounts.serializers import EnseignantSerializer, EnseignantCadreLightSerializer
from apps.accounts.models import Profile
from apps.formation.models import Parcours, Departement, DemandeAccesFormation, Cours, Module, Lecon


class LeconSerializer(serializers.ModelSerializer):
    fichier_pdf = serializers.SerializerMethodField()
    created_by = EnseignantSerializer(read_only=True)

    class Meta:
        model = Lecon
        fields = [
            "id",
            "titre",
            "description",
            "fichier_pdf",
            "video",
            "module",
            "created_by",
            "cours",
            "created_at",
        ]

    def get_fichier_pdf(self, obj):
        if obj.fichier_pdf:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.fichier_pdf.url)
            return obj.fichier_pdf.url
        return None


class LeconCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lecon
        fields = [
            "titre",
            "description",
            "fichier_pdf",
            "video",
            "module",
        ]

    def validate_fichier_pdf(self, value):
        if not value.name.endswith(".pdf"):
            raise serializers.ValidationError("Seuls les fichiers PDF sont autorisés.")
        return value


class CoursSerializer(serializers.ModelSerializer):
    enseignant_principal = EnseignantSerializer(read_only=True)
    enseignants = EnseignantSerializer(many=True, read_only=True)
    lecons = LeconSerializer(many=True, read_only=True)

    class Meta:
        model = Cours
        fields = [
            "id",
            "titre",
            "niveau",
            # UI / Présentation
            "description_brief",
            "color_code",
            "icon_name",
            # Stats
            "nb_lecons",
            "nb_devoirs",
            "nb_apprenants",
            # Relations
            "departement",
            "enseignant_principal",
            "enseignants",
            "lecons",
        ]


class CoursCreateSerializer(serializers.ModelSerializer):
    departement = serializers.PrimaryKeyRelatedField(queryset=Departement.objects.all())
    enseignant_principal = serializers.PrimaryKeyRelatedField(
        queryset=Profile.objects.filter(user_type="enseignant_principal"),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Cours
        fields = [
            "titre",
            "niveau",
            "matiere",
            "concours",
            "description_brief",
            "color_code",
            "icon_name",
            "departement",
            "enseignant_principal",
        ]
        extra_kwargs = {
            "titre": {"required": True},
            "niveau": {"required": True},
            "matiere": {"required": False, "allow_blank": True},
            "concours": {"required": False, "allow_blank": True},
            "description_brief": {"required": False, "allow_blank": True, "allow_null": True},
            "color_code": {"required": False},
            "icon_name": {"required": False},
        }

    def validate_departement(self, departement):
        request = self.context.get("request")
        if not request:
            return departement
        try:
            profile = request.user.profile
        except Profile.DoesNotExist:
            raise serializers.ValidationError("Profil introuvable.")
        if profile.user_type == "enseignant_cadre":
            if departement.cadre != profile:
                raise serializers.ValidationError(
                    "Vous ne pouvez créer un cours que dans votre propre département."
                )
        return departement

    def validate_enseignant_principal(self, ep):
        if ep is not None and ep.user_type != "enseignant_principal":
            raise serializers.ValidationError("Cet utilisateur n'est pas un enseignant principal.")
        return ep

    def validate(self, attrs):
        color = attrs.get("color_code", "#008080")
        if color and not color.startswith("#"):
            attrs["color_code"] = f"#{color}"
        return attrs

    def create(self, validated_data):
        return Cours.objects.create(**validated_data)


class CoursListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cours
        fields = [
            "id",
            "titre",
            "niveau",
            "description_brief",
            "color_code",
            "icon_name",
            "nb_lecons",
            "nb_devoirs",
        ]


class CursusApprenantSerializer(serializers.ModelSerializer):
    enseignant_principal = serializers.SerializerMethodField()
    title = serializers.CharField(source="titre")
    description = serializers.CharField(source="description_brief")
    lessons = serializers.IntegerField(source="nb_lecons")
    assignments = serializers.IntegerField(source="nb_devoirs")
    icon = serializers.CharField(source="icon_name")
    color = serializers.CharField(source="color_code")

    class Meta:
        model = Cours
        fields = [
            "id",
            "title",
            "description",
            "enseignant_principal",
            "lessons",
            "assignments",
            "icon",
            "color",
        ]

    def get_enseignant_principal(self, obj):
        if obj.enseignant_principal:
            return obj.enseignant_principal.user.username
        return "—"


class ModuleCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Module
        fields = ["titre", "ordre", "description"]


class ModuleListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Module
        fields = ["id", "titre", "ordre", "description"]


class DepartementSerializer(serializers.ModelSerializer):
    cadre = EnseignantCadreLightSerializer(read_only=True)
    cours = CoursSerializer(many=True, read_only=True)
    niveaux_accessibles = serializers.SerializerMethodField()
    demandes_acces = serializers.SerializerMethodField()

    class Meta:
        model = Departement
        fields = [
            "id",
            "nom",
            "parcours",
            "cadre",
            "cours",
            "niveaux_accessibles",
            "niveaux_cibles",
            "description",
            "image",
            "couleur",
            "est_actif",
            "prix",
            "prix_presentiel",
            "created_at",
            "est_prepa_concours",
            "nom_concours",
            "organisme_concours",
            "date_limite_inscription",
            "date_examen",
            "arrete_ministeriel",
            "places_disponibles",
            "debouches",
            "mode",
            "est_formation_metier",
            "est_formation_classique",
            "duree_formation",
            "certificat_delivre",
            "prerequis",
            "objectifs",
            "domaine",
            "ville",
            "est_certifiante",
            "acces_restreint",
            "apprenants_autorises",
            "demandes_acces",
            "niveau_formation",
        ]

    def get_niveaux_accessibles(self, obj):
        return obj.get_niveaux_accessibles_list()

    def get_demandes_acces(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            try:
                profile = request.user.profile
                if profile.user_type == "enseignant_cadre":
                    demandes = DemandeAccesFormation.objects.filter(
                        departement=obj, statut="en_attente"
                    ).select_related("apprenant")
                    return [
                        {
                            "id": d.id,
                            "apprenant_id": d.apprenant.id,
                            "apprenant_nom": f"{d.apprenant.first_name} {d.apprenant.last_name}".strip()
                            or d.apprenant.username,
                            "apprenant_username": d.apprenant.username,
                            "message": d.message,
                            "cree_le": d.cree_le.isoformat(),
                        }
                        for d in demandes
                    ]
            except Profile.DoesNotExist:
                pass
        return []


class DepartementUpdateSerializer(serializers.ModelSerializer):
    niveaux_accessibles = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=True,
        help_text="Liste des niveaux accessibles",
    )

    date_limite_inscription = serializers.DateField(
        required=False,
        allow_null=True,
        input_formats=["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ", ""],
    )
    date_examen = serializers.DateField(
        required=False,
        allow_null=True,
        input_formats=["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ", ""],
    )

    class Meta:
        model = Departement
        fields = [
            "nom",
            "description",
            "prix",
            "prix_presentiel",
            "est_prepa_concours",
            "nom_concours",
            "organisme_concours",
            "date_limite_inscription",
            "date_examen",
            "arrete_ministeriel",
            "places_disponibles",
            "debouches",
            "mode",
            "est_formation_metier",
            "est_formation_classique",
            "duree_formation",
            "certificat_delivre",
            "prerequis",
            "objectifs",
            "domaine",
            "ville",
            "est_certifiante",
            "acces_restreint",
            "niveaux_accessibles",
            "niveau_formation",
        ]
        extra_kwargs = {
            "nom": {"required": False, "allow_blank": False},
            "description": {"required": False, "allow_blank": True},
            "prix": {"required": False, "min_value": 0},
            "prix_presentiel": {"required": False, "min_value": 0},
            "est_prepa_concours": {"required": False},
            "est_formation_metier": {"required": False},
            "est_formation_classique": {"required": False},
            "acces_restreint": {"required": False},
            "mode": {"required": False, "allow_blank": True},
            "niveau_formation": {"required": False, "allow_blank": True},
            "nom_concours": {"required": False, "allow_blank": True},
            "organisme_concours": {"required": False, "allow_blank": True},
            "arrete_ministeriel": {"required": False, "allow_blank": True},
            "places_disponibles": {"required": False, "allow_null": True},
            "debouches": {"required": False, "allow_blank": True},
            "duree_formation": {"required": False, "allow_blank": True},
            "certificat_delivre": {"required": False, "allow_blank": True},
            "prerequis": {"required": False, "allow_blank": True},
            "objectifs": {"required": False, "allow_blank": True},
            "domaine": {"required": False, "allow_blank": True},
            "ville": {"required": False, "allow_blank": True},
            "est_certifiante": {"required": False},
        }

    def validate(self, data):
        instance = self.instance
        if instance and instance.parcours.type_parcours == "formation":
            est_metier = data.get("est_formation_metier", instance.est_formation_metier)
            est_classique = data.get("est_formation_classique", instance.est_formation_classique)
            if not est_metier and not est_classique:
                raise serializers.ValidationError(
                    "Veuillez sélectionner au moins un type de formation (Métier ou Classique)"
                )
            if est_metier:
                niveau = data.get("niveau_formation", instance.niveau_formation)
                if niveau and niveau not in ["debutant", "intermediaire", "avance"]:
                    raise serializers.ValidationError(
                        "Niveau de formation invalide. Choisissez: debutant, intermediaire, avance"
                    )
        return data

    def update(self, instance, validated_data):
        niveaux_accessibles = validated_data.pop("niveaux_accessibles", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        if niveaux_accessibles is not None:
            if isinstance(niveaux_accessibles, list):
                instance.niveaux_accessibles = ",".join(niveaux_accessibles)
            else:
                instance.niveaux_accessibles = niveaux_accessibles
        instance.save()
        return instance


class DemandeAccesSerializer(serializers.ModelSerializer):
    apprenant_nom = serializers.SerializerMethodField()
    apprenant_username = serializers.CharField(source="apprenant.username", read_only=True)

    class Meta:
        model = DemandeAccesFormation
        fields = [
            "id",
            "apprenant",
            "apprenant_nom",
            "apprenant_username",
            "departement",
            "statut",
            "message",
            "reponse_cadre",
            "cree_le",
            "traite_le",
        ]

    def get_apprenant_nom(self, obj):
        return (
            f"{obj.apprenant.first_name} {obj.apprenant.last_name}".strip()
            or obj.apprenant.username
        )


class DepartementCreateSerializer(serializers.ModelSerializer):
    niveaux_accessibles = serializers.ListField(
        child=serializers.CharField(), required=False, default=[]
    )

    class Meta:
        model = Departement
        fields = [
            "nom",
            "description",
            "couleur",
            "prix",
            "prix_presentiel",
            "parcours",
            "image",
            "est_prepa_concours",
            "nom_concours",
            "organisme_concours",
            "date_limite_inscription",
            "date_examen",
            "arrete_ministeriel",
            "places_disponibles",
            "debouches",
            "mode",
            "est_formation_metier",
            "est_formation_classique",
            "duree_formation",
            "certificat_delivre",
            "prerequis",
            "objectifs",
            "domaine",
            "ville",
            "est_certifiante",
            "acces_restreint",
            "niveaux_accessibles",
            "niveau_formation",
            "periode",
        ]
        extra_kwargs = {
            "description": {"required": False, "allow_blank": True},
            "couleur": {"required": False, "default": "#2884A0"},
            "prix": {"required": False, "default": 0},
            "prix_presentiel": {"required": False, "default": 0},
            "image": {"required": False},
            "mode": {"required": False, "default": "hybride"},
            "est_prepa_concours": {"required": False, "default": False},
            "est_formation_metier": {"required": False, "default": False},
            "est_formation_classique": {"required": False, "default": False},
            "acces_restreint": {"required": False, "default": False},
            "niveau_formation": {"required": False, "allow_blank": True, "default": "debutant"},
            # P2.3 (CDC §6.4/§7.4) : « obligatoire lors de la création » —
            # le default=6 du modèle est conservé pour ne pas casser les
            # lignes existantes, mais l'API exige désormais une valeur
            # explicite à la création.
            "periode": {"required": True},
        }

    def validate(self, data):
        parcours = data.get("parcours")
        if parcours and parcours.type_parcours == "formation":
            est_metier = data.get("est_formation_metier", False)
            est_classique = data.get("est_formation_classique", False)
            if not est_metier and not est_classique:
                raise serializers.ValidationError(
                    "Veuillez sélectionner au moins un type de formation (Métier ou Classique)"
                )
            if est_metier:
                niveau = data.get("niveau_formation", "debutant")
                if niveau not in ["debutant", "intermediaire", "avance"]:
                    raise serializers.ValidationError(
                        "Niveau de formation invalide. Choisissez: debutant, intermediaire, avance"
                    )
        return data

    def create(self, validated_data):
        niveaux_accessibles = validated_data.pop("niveaux_accessibles", [])
        departement = Departement.objects.create(**validated_data)
        if niveaux_accessibles:
            departement.niveaux_accessibles = ",".join(niveaux_accessibles)
            departement.save(update_fields=["niveaux_accessibles"])
        return departement

    def update(self, instance, validated_data):
        niveaux_accessibles = validated_data.pop("niveaux_accessibles", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        if niveaux_accessibles is not None:
            instance.niveaux_accessibles = ",".join(niveaux_accessibles)
        instance.save()
        return instance


class ApprenantDepartementDetailSerializer(serializers.ModelSerializer):
    est_accessible = serializers.SerializerMethodField()
    demande_statut = serializers.SerializerMethodField()

    class Meta:
        model = Departement
        fields = [
            "id",
            "nom",
            "description",
            "image",
            "couleur",
            "prix",
            "prix_presentiel",
            "est_prepa_concours",
            "nom_concours",
            "organisme_concours",
            "date_limite_inscription",
            "date_examen",
            "arrete_ministeriel",
            "places_disponibles",
            "debouches",
            "mode",
            "est_formation_metier",
            "est_formation_classique",
            "duree_formation",
            "certificat_delivre",
            "prerequis",
            "objectifs",
            "domaine",
            "ville",
            "est_certifiante",
            "acces_restreint",
            "niveaux_accessibles",
            "est_accessible",
            "demande_statut",
        ]

    def get_est_accessible(self, obj):
        user = self.context.get("request").user
        if not user.is_authenticated:
            return False
        if not obj.acces_restreint:
            return True
        return user in obj.apprenants_autorises.all()

    def get_demande_statut(self, obj):
        user = self.context.get("request").user
        if not user.is_authenticated:
            return None
        try:
            demande = DemandeAccesFormation.objects.get(apprenant=user, departement=obj)
            return demande.statut
        except DemandeAccesFormation.DoesNotExist:
            return None


class ParcoursSerializer(serializers.ModelSerializer):
    admin = EnseignantSerializer(read_only=True)
    departements = DepartementSerializer(many=True, read_only=True)

    class Meta:
        model = Parcours
        fields = ["id", "nom", "admin", "departements", "type_parcours"]


class LeconLightSerializer(serializers.ModelSerializer):
    fichier_pdf = serializers.SerializerMethodField()
    video = serializers.SerializerMethodField()

    class Meta:
        model = Lecon
        fields = [
            "id",
            "titre",
            "description",
            "fichier_pdf",
            "video",
        ]

    def get_fichier_pdf(self, obj):
        if obj.fichier_pdf:
            request = self.context.get("request")
            return request.build_absolute_uri(obj.fichier_pdf.url)
        return None

    def get_video(self, obj):
        if obj.video:
            request = self.context.get("request")
            return request.build_absolute_uri(obj.video.url)
        return None


class ModuleAvecLeconsSerializer(serializers.ModelSerializer):
    lecons = LeconLightSerializer(many=True, read_only=True)

    class Meta:
        model = Module
        fields = [
            "id",
            "titre",
            "description",
            "ordre",
            "lecons",
        ]


class ModuleUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Module
        fields = ["titre", "description", "ordre"]
        extra_kwargs = {
            "titre": {"required": False},
            "description": {"required": False},
            "ordre": {"required": False},
        }

    def validate_ordre(self, value):
        if value < 1:
            raise serializers.ValidationError("L'ordre doit être supérieur ou égal à 1.")
        return value

    def update(self, instance, validated_data):
        nouvel_ordre = validated_data.get("ordre")
        if nouvel_ordre and nouvel_ordre != instance.ordre:
            conflit = (
                Module.objects.filter(cours=instance.cours, ordre=nouvel_ordre)
                .exclude(pk=instance.pk)
                .first()
            )
            if conflit:
                conflit.ordre = instance.ordre
                conflit.save(update_fields=["ordre"])
        return super().update(instance, validated_data)


class LeconUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lecon
        fields = [
            "titre",
            "description",
            "module",
            "fichier_pdf",
            "video",
        ]
        extra_kwargs = {
            "titre": {"required": False},
            "description": {"required": False},
            "module": {"required": False, "allow_null": True},
            "fichier_pdf": {"required": False, "allow_null": True},
            "video": {"required": False, "allow_null": True},
        }

    def validate_fichier_pdf(self, value):
        if value and not value.name.lower().endswith(".pdf"):
            raise serializers.ValidationError("Seuls les fichiers PDF sont autorisés.")
        return value

    def validate_video(self, value):
        ALLOWED = [".mp4", ".mov", ".avi", ".mkv", ".webm"]
        if value and not any(value.name.lower().endswith(ext) for ext in ALLOWED):
            raise serializers.ValidationError(
                f"Format vidéo non supporté. Formats acceptés : {', '.join(ALLOWED)}"
            )
        return value

    def validate_module(self, module):
        if module is None:
            return module
        lecon = self.instance
        if lecon and module.cours_id != lecon.cours_id:
            raise serializers.ValidationError(
                "Le module cible doit appartenir au même cours que cette leçon."
            )
        return module

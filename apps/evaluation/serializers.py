from rest_framework import serializers
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone

from apps.evaluation.validators import valider_pas_de_0_25, valider_pas_de_cycle_epreuve
from apps.evaluation.models import (
    Exercice,
    SessionExercice,
    Question,
    Choix,
    EvaluationExercice,
    Devoir,
    EnonceDevoir,
    QuestionDevoir,
    ChoixReponse,
    SoumissionDevoir,
    Olympiade,
    InscriptionOlympiade,
    ClassementOlympiade,
)


class ChoixSerializer(serializers.ModelSerializer):
    class Meta:
        model = Choix
        fields = ["id", "texte"]


class QuestionSerializer(serializers.ModelSerializer):
    type = serializers.CharField(source="type_question")
    choix = serializers.SerializerMethodField()

    class Meta:
        model = Question
        fields = ["id", "text", "type", "points", "choix", "explication"]

    def get_choix(self, obj):
        # P6.3 : liste COMPLÈTE (id + texte + est_correct, pas juste le
        # texte) et ORDONNÉE (Choix.Meta.ordering = ["ordre"]) — la page
        # d'ajout d'exercices a besoin de savoir quel choix est correct
        # pour afficher/éditer un QCM existant.
        if obj.type_question.lower() == "qcm":
            return [
                {"id": c.id, "texte": c.texte, "est_correct": c.est_correct}
                for c in obj.choix.all()
            ]
        return []


class ChoixCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Choix
        fields = ["texte", "est_correct"]


class QuestionCreateSerializer(serializers.ModelSerializer):
    """
    P2.2 : la bonne réponse d'un QCM est désormais portée par
    `Choix.est_correct` (source de vérité), pas par une comparaison
    texte-à-texte contre `bonne_reponse` (fragile — casse/espaces/accents,
    cause confirmée du bug de création QCM échouant silencieusement).
    `bonne_reponse` reste obligatoire pour les questions de type 'texte' ;
    pour un QCM elle devient un mirroir dérivé, auto-rempli à la création
    (voir `create()`), conservé pour compatibilité descendante d'affichage.
    """

    choix = ChoixCreateSerializer(many=True, required=False, default=[])

    class Meta:
        model = Question
        fields = ["text", "type_question", "points", "bonne_reponse", "choix", "explication"]
        extra_kwargs = {
            "points": {"required": False, "default": 1},
            "bonne_reponse": {"required": False, "allow_blank": True},
            "explication": {"required": False, "allow_blank": True},
        }

    def validate_points(self, value):
        # P6.3 : le validateur de modèle (MinValueValidator(0.25) +
        # valider_pas_de_0_25) n'est jamais invoqué via l'API sans
        # `full_clean()` explicite (jamais appelé dans les vues) — un
        # `validate_<champ>` de serializer est, lui, systématiquement
        # exécuté par DRF pendant `is_valid()`.
        try:
            valider_pas_de_0_25(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)
        return value

    def validate(self, attrs):
        type_q = attrs.get("type_question", "texte")
        choix = attrs.get("choix", [])

        if type_q == "qcm":
            if len(choix) < 2:
                raise serializers.ValidationError({"choix": "Un QCM doit avoir au moins 2 choix."})
            nb_corrects = sum(1 for c in choix if c.get("est_correct"))
            if nb_corrects == 0:
                raise serializers.ValidationError(
                    {"choix": "Un QCM doit avoir un choix marqué comme correct (est_correct=True)."}
                )
            if nb_corrects > 1:
                raise serializers.ValidationError(
                    {"choix": "Un QCM ne peut avoir qu'un seul choix correct."}
                )
        else:
            if not attrs.get("bonne_reponse", "").strip():
                raise serializers.ValidationError(
                    {"bonne_reponse": "Ce champ est obligatoire pour une question de type texte."}
                )
        return attrs

    def create(self, validated_data):
        choix_data = validated_data.pop("choix", [])
        question = Question.objects.create(**validated_data)

        choix_correct_texte = None
        for ordre, c in enumerate(choix_data, start=1):
            choix = Choix.objects.create(
                question=question,
                texte=c["texte"],
                est_correct=c.get("est_correct", False),
                ordre=ordre,
            )
            if choix.est_correct:
                choix_correct_texte = choix.texte

        # Mirroir de compatibilité descendante (voir docstring de la classe)
        if question.type_question == "qcm" and choix_correct_texte is not None:
            question.bonne_reponse = choix_correct_texte
            question.save(update_fields=["bonne_reponse"])

        return question


class ExerciceSerializer(serializers.ModelSerializer):
    questions = QuestionSerializer(many=True, read_only=True)
    module_nom = serializers.CharField(source="module.titre", read_only=True, allow_null=True)
    lecon_nom = serializers.CharField(source="lecon.titre", read_only=True, allow_null=True)
    enonce_image_url = serializers.SerializerMethodField()
    exercices_composes_details = serializers.SerializerMethodField()
    est_epreuve = serializers.BooleanField(read_only=True)
    nb_questions = serializers.SerializerMethodField()

    class Meta:
        model = Exercice
        fields = [
            "id",
            "titre",
            "enonce",
            "etoiles",
            "questions",
            "duree_minutes",
            "tentatives_max",
            "module",
            "module_nom",
            "lecon",
            "lecon_nom",
            "type_exercice",
            "est_epreuve",
            "exercices_composes",
            "exercices_composes_details",
            "enonce_image_url",
            "nb_questions",
        ]

    def get_enonce_image_url(self, obj):
        if obj.enonce_image:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.enonce_image.url)
            return obj.enonce_image.url
        return None

    def get_exercices_composes_details(self, obj):
        if not obj.est_epreuve:
            return []
        return [
            {"id": ex.id, "titre": ex.titre, "nb_questions": ex.questions.count()}
            for ex in obj.exercices_composes.all()
        ]

    def get_nb_questions(self, obj):
        return obj.questions.count()


class ExerciceCreateSerializer(serializers.ModelSerializer):
    enonce_image = serializers.ImageField(required=False, allow_null=True)
    exercices_composes = serializers.PrimaryKeyRelatedField(
        queryset=Exercice.objects.all(), many=True, required=False
    )

    class Meta:
        model = Exercice
        fields = [
            "titre",
            "enonce",
            "etoiles",
            "duree_minutes",
            "tentatives_max",
            "module",
            "lecon",
            "type_exercice",
            "est_epreuve",
            "exercices_composes",
            "enonce_image",
        ]
        extra_kwargs = {
            "type_exercice": {"required": False, "default": "general"},
            "est_epreuve": {"required": False, "default": False},
            "enonce": {"required": True},
        }

    def validate(self, data):
        enonce = data.get("enonce", "").strip()
        if not enonce:
            raise serializers.ValidationError({"enonce": "L'énoncé est obligatoire."})

        # P2.2 : sur un PATCH partiel qui ne renvoie pas `est_epreuve`, se
        # rabattre sur la valeur déjà en base (`self.instance`) — sinon la
        # vérification ci-dessous était silencieusement sautée pour une
        # épreuve existante (cause confirmée du bug « la modification d'une
        # épreuve ne fonctionne pas »).
        est_epreuve = data.get("est_epreuve", getattr(self.instance, "est_epreuve", False))
        if est_epreuve:
            exercices = data.get("exercices_composes", [])
            if not exercices:
                raise serializers.ValidationError(
                    {"exercices_composes": "Une épreuve doit contenir au moins un exercice."}
                )
            # Anti-cycle (P2.2) : une épreuve ne peut pas se contenir
            # elle-même, ni directement ni transitivement.
            try:
                valider_pas_de_cycle_epreuve(self.instance, exercices)
            except DjangoValidationError as exc:
                raise serializers.ValidationError({"exercices_composes": exc.messages})
        return data

    def create(self, validated_data):
        exercices_composes = validated_data.pop("exercices_composes", [])
        enonce_image = validated_data.pop("enonce_image", None)
        exercice = Exercice.objects.create(**validated_data)
        if enonce_image:
            exercice.enonce_image = enonce_image
            exercice.save()
        if exercices_composes:
            exercice.exercices_composes.set(exercices_composes)
        return exercice


class SessionSerializer(serializers.ModelSerializer):
    temps_restant = serializers.SerializerMethodField()

    class Meta:
        model = SessionExercice
        fields = ["id", "exercice", "debut", "termine", "temps_restant"]

    def get_temps_restant(self, obj):
        return obj.temps_restant()


class EvaluationSerializer(serializers.ModelSerializer):
    titre = serializers.CharField(source="exercice.titre", read_only=True)
    etoiles = serializers.IntegerField(source="exercice.etoiles", read_only=True)

    class Meta:
        model = EvaluationExercice
        fields = ["id", "titre", "etoiles", "score", "total", "date"]


class ChoixReponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChoixReponse
        fields = ["id", "texte"]


class ChoixReponseAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChoixReponse
        fields = ["id", "texte", "est_correct"]


class ChoixReponseCreateSerializer(serializers.ModelSerializer):
    """P7.1 : miroir exact de `ChoixCreateSerializer` (côté exercice) —
    remplace le `ListField(DictField)` bruit utilisé jusqu'ici pour
    `QuestionDevoirCreateUpdateSerializer.choix`, qui ne validait ni la
    forme ni le nombre de choix corrects."""

    class Meta:
        model = ChoixReponse
        fields = ["texte", "est_correct"]


class QuestionDevoirSerializer(serializers.ModelSerializer):
    """Vue apprenant/générique — questions d'un devoir avec leurs choix
    ORDONNÉS (`ChoixReponse.Meta.ordering`). Fusionne l'ancien doublon
    `QuestionDevoirDetailSerializer` (champs strictement identiques,
    signalé dans un TODO depuis l'éclatement de yeki/serializers.py)."""

    choix = ChoixReponseSerializer(many=True, read_only=True)

    class Meta:
        model = QuestionDevoir
        fields = ["id", "enonce", "type_question", "points", "ordre", "choix"]


class QuestionDevoirAdminSerializer(serializers.ModelSerializer):
    choix = ChoixReponseAdminSerializer(many=True, read_only=True)

    class Meta:
        model = QuestionDevoir
        fields = [
            "id",
            "enonce",
            "type_question",
            "points",
            "ordre",
            "choix",
            "reponse_attendue",
            "reponse_exemple",
            # P7.4 : indispensable pour regrouper les questions PAR
            # énoncé côté frontend (ListeQuestionsDevoirView renvoie les
            # questions à plat, sans ce champ impossible de savoir à
            # quel EnonceDevoir chacune appartient).
            "enonce_devoir",
        ]


class QuestionDevoirCreateUpdateSerializer(serializers.ModelSerializer):
    """P7.1 : `choix` devient un serializer imbriqué (`ChoixReponseCreateSerializer`)
    au lieu d'un `ListField(DictField)` brut, et `validate()` impose la
    même règle QCM que `QuestionCreateSerializer` (côté exercice, P6.3) :
    un QCM doit avoir exactement un choix marqué `est_correct=True` —
    jusqu'ici aucune validation de ce type n'existait côté devoir, et
    `ChoixReponse` était créé sans `ordre` explicite (retombait sur le
    défaut `1` pour tous les choix, ordre non déterministe)."""

    choix = ChoixReponseCreateSerializer(many=True, required=False, default=[])

    class Meta:
        model = QuestionDevoir
        fields = [
            "enonce",
            "type_question",
            "points",
            "ordre",
            "choix",
            "reponse_attendue",
            "reponse_exemple",
        ]
        extra_kwargs = {
            "points": {"required": False, "default": 1},
            "ordre": {"required": False},
        }

    def validate_points(self, value):
        # P6.3 : même correctif que QuestionCreateSerializer — le
        # validateur de modèle n'est jamais invoqué via l'API sans
        # `full_clean()` explicite.
        try:
            valider_pas_de_0_25(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)
        return value

    def validate(self, attrs):
        # P7.2 : en modification partielle (PATCH, ex. ModifierQuestionDevoirView,
        # routée pour la première fois), ces règles ne doivent s'appliquer
        # QUE si le champ concerné fait effectivement partie de CETTE
        # requête — sans quoi un simple `PATCH {"enonce": "..."}` sur une
        # question texte existante levait à tort « réponse attendue
        # obligatoire », `reponse_attendue` n'étant jamais renvoyé par un
        # appelant qui ne modifie que l'énoncé.
        type_q = attrs.get(
            "type_question",
            self.instance.type_question if self.partial and self.instance else "texte",
        )
        # P7.3 : QCM interdit sur un devoir à correction manuelle — texte
        # libre uniquement (l'enseignant corrige lui-même, pas de choix à
        # cocher). Ne se déclenche que si le type QCM est effectivement
        # visé par CETTE requête (création, ou modification qui le fixe
        # explicitement) — cohérent avec la garde partial ci-dessus.
        if type_q == "qcm" and self.context.get("type_correction") == "manuel":
            raise serializers.ValidationError(
                {"type_question": "Le QCM n'est pas autorisé pour un devoir à correction manuelle."}
            )
        if type_q == "qcm" and ("choix" in attrs or not self.partial):
            choix = attrs.get("choix", [])
            if len(choix) < 2:
                raise serializers.ValidationError({"choix": "Un QCM doit avoir au moins 2 choix."})
            nb_corrects = sum(1 for c in choix if c.get("est_correct"))
            if nb_corrects == 0:
                raise serializers.ValidationError(
                    {"choix": "Un QCM doit avoir un choix marqué comme correct (est_correct=True)."}
                )
            if nb_corrects > 1:
                raise serializers.ValidationError(
                    {"choix": "Un QCM ne peut avoir qu'un seul choix correct."}
                )
        if type_q == "texte" and ("reponse_attendue" in attrs or not self.partial):
            if self.context.get("type_correction") == "auto":
                if not attrs.get("reponse_attendue", "").strip():
                    raise serializers.ValidationError(
                        {
                            "reponse_attendue": "La réponse attendue est obligatoire pour la correction automatique."
                        }
                    )
        return attrs

    def create(self, validated_data):
        choix_data = validated_data.pop("choix", [])
        question = QuestionDevoir.objects.create(**validated_data)
        for ordre, c in enumerate(choix_data, start=1):
            ChoixReponse.objects.create(
                question=question,
                texte=c["texte"],
                est_correct=c.get("est_correct", False),
                ordre=ordre,
            )
        return question

    def update(self, instance, validated_data):
        choix_data = validated_data.pop("choix", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.save()
        if choix_data is not None:
            instance.choix.all().delete()
            for ordre, c in enumerate(choix_data, start=1):
                ChoixReponse.objects.create(
                    question=instance,
                    texte=c["texte"],
                    est_correct=c.get("est_correct", False),
                    ordre=ordre,
                )
        return instance


class DevoirListSerializer(serializers.ModelSerializer):
    statut_apprenant = serializers.SerializerMethodField()
    note_apprenant = serializers.SerializerMethodField()
    temps_restant_jours = serializers.SerializerMethodField()
    est_ouvert = serializers.BooleanField(read_only=True)
    est_expire = serializers.BooleanField(read_only=True)
    peut_modifier_questions = serializers.BooleanField(read_only=True)
    nb_sorties = serializers.SerializerMethodField()
    sorties_max = serializers.IntegerField(source="tentatives_max", read_only=True)

    class Meta:
        model = Devoir
        fields = [
            "id",
            "titre",
            "description",
            "type_devoir",
            "date_debut",
            "date_limite",
            "duree_minutes",
            "note_sur",
            "coefficient",
            "concours_lie",
            "formation_liee",
            "est_publie",
            "est_ouvert",
            "est_expire",
            "statut_apprenant",
            "note_apprenant",
            "temps_restant_jours",
            "type_correction",
            "peut_modifier_questions",
            "nb_sorties",
            "sorties_max",
        ]

    def get_statut_apprenant(self, obj):
        user = self.context["request"].user
        soum = SoumissionDevoir.objects.filter(utilisateur=user, devoir=obj).first()
        if not soum:
            return "non_commence"
        return soum.statut

    def get_note_apprenant(self, obj):
        user = self.context["request"].user
        soum = SoumissionDevoir.objects.filter(utilisateur=user, devoir=obj).first()
        if soum and soum.note is not None:
            return soum.note
        return None

    def get_temps_restant_jours(self, obj):
        delta = obj.date_limite - timezone.now()
        return max(0, delta.days)

    def get_nb_sorties(self, obj):
        user = self.context["request"].user
        soum = SoumissionDevoir.objects.filter(utilisateur=user, devoir=obj).first()
        if soum:
            return soum.sorties
        return 0


class EnonceDevoirSerializer(serializers.ModelSerializer):
    """
    P2.3 : un énoncé de devoir avec ses propres questions (remplace
    `Devoir.enonces_supplementaires`, @deprecated). Questions ORDONNÉES
    (`QuestionDevoir.Meta.ordering`) — P7.1.
    """

    questions = QuestionDevoirSerializer(many=True, read_only=True)

    class Meta:
        model = EnonceDevoir
        fields = ["id", "contenu", "ordre", "questions"]


class EnonceDevoirUpdateSerializer(serializers.ModelSerializer):
    """P7.1 : édition du contenu d'un énoncé (`PATCH /devoirs/enonces/<id>/`)
    — `ordre` reste géré par le serveur (création/suppression), pas
    éditable via ce serializer."""

    class Meta:
        model = EnonceDevoir
        fields = ["contenu"]
        extra_kwargs = {"contenu": {"required": True, "allow_blank": False}}


class DevoirDetailSerializer(serializers.ModelSerializer):
    questions = QuestionDevoirSerializer(many=True, read_only=True)
    enonces = EnonceDevoirSerializer(many=True, read_only=True)
    peut_modifier_questions = serializers.BooleanField(read_only=True)
    nb_sorties = serializers.SerializerMethodField()
    sorties_max = serializers.IntegerField(source="tentatives_max", read_only=True)

    class Meta:
        model = Devoir
        fields = [
            "id",
            "titre",
            "description",
            "type_devoir",
            "enonce",
            "enonces",
            "date_debut",
            "date_limite",
            "duree_minutes",
            "note_sur",
            "coefficient",
            "tentatives_max",
            "concours_lie",
            "formation_liee",
            "questions",
            "type_correction",
            "peut_modifier_questions",
            "nb_sorties",
            "sorties_max",
        ]

    def get_nb_sorties(self, obj):
        user = self.context["request"].user
        soum = SoumissionDevoir.objects.filter(utilisateur=user, devoir=obj).first()
        if soum:
            return soum.sorties
        return 0


class DevoirCreateSerializer(serializers.ModelSerializer):
    """P7.2 : `est_publie` n'est PLUS un champ de ce serializer — un devoir
    naît toujours non publié (défaut du modèle). La publication ne passe
    QUE par `PublierDevoirView` (`POST .../publier/`), seule à même de
    renvoyer l'avertissement explicite exigé (« vous ne pourrez plus
    ajouter ni modifier de question ni d'énoncé »)."""

    enonces_supplementaires = serializers.ListField(
        child=serializers.CharField(), required=False, default=[]
    )
    fichier_correction = serializers.FileField(required=False, allow_null=True)

    class Meta:
        model = Devoir
        fields = [
            "titre",
            "description",
            "type_devoir",
            "enonce",
            "date_debut",
            "date_limite",
            "duree_minutes",
            "note_sur",
            "coefficient",
            "tentatives_max",
            "concours_lie",
            "formation_liee",
            "cours_lie",
            "acces_restreint",
            "type_correction",
            "fichier_correction",
            "enonces_supplementaires",
            "source_devoir",
        ]
        extra_kwargs = {
            "enonce": {"required": True},
            "type_correction": {"required": False, "default": "auto"},
            "enonces_supplementaires": {"required": False},
        }

    def validate(self, data):
        enonce = data.get("enonce", "").strip()
        if not enonce:
            raise serializers.ValidationError({"enonce": "L'énoncé est obligatoire."})
        if data.get("date_limite") and data.get("date_debut"):
            if data["date_limite"] <= data["date_debut"]:
                raise serializers.ValidationError(
                    "La date limite doit être postérieure à la date de début."
                )
        if data.get("type_correction") == "manuel":
            if not data.get("fichier_correction"):
                raise serializers.ValidationError(
                    {
                        "fichier_correction": "Un fichier PDF de correction est requis pour la correction manuelle."
                    }
                )
        return data

    def create(self, validated_data):
        enonces_supp = validated_data.pop("enonces_supplementaires", [])
        validated_data.pop("source_devoir", None)  # retiré de validated_data, valeur non utilisée
        devoir = Devoir.objects.create(**validated_data)

        # P2.3 : alimente EnonceDevoir en coulisses — contrat de création
        # inchangé pour le frontend (toujours `enonce` + éventuellement
        # `enonces_supplementaires`), mais la source de vérité devient
        # EnonceDevoir dès la création.
        EnonceDevoir.objects.create(devoir=devoir, contenu=devoir.enonce, ordre=1)
        if enonces_supp:
            devoir.enonces_supplementaires = enonces_supp
            devoir.save(update_fields=["enonces_supplementaires"])
            for i, contenu in enumerate(enonces_supp, start=2):
                EnonceDevoir.objects.create(devoir=devoir, contenu=contenu, ordre=i)
        return devoir


class DevoirUpdateSerializer(serializers.ModelSerializer):
    """P7.2 : `est_publie` retiré (voir `DevoirCreateSerializer`, même
    raison — passe uniquement par `PublierDevoirView`). Le blocage
    « aucune modification si publié » (CDC §7.2.2, point 4 : « même
    contrôle » que les questions) est désormais géré au niveau de
    `ModifierDevoirView` (garde globale, tous champs), pas ici champ par
    champ — cette classe ne garde qu'un contrôle propre à son domaine :
    `enonce` non-vide s'il est fourni."""

    enonces_supplementaires = serializers.ListField(
        child=serializers.CharField(), required=False, default=[]
    )
    fichier_correction = serializers.FileField(required=False, allow_null=True)

    class Meta:
        model = Devoir
        fields = [
            "titre",
            "description",
            "type_devoir",
            "enonce",
            "date_debut",
            "date_limite",
            "duree_minutes",
            "note_sur",
            "coefficient",
            "tentatives_max",
            "concours_lie",
            "formation_liee",
            "cours_lie",
            "acces_restreint",
            "type_correction",
            "fichier_correction",
            "enonces_supplementaires",
        ]
        extra_kwargs = {
            "titre": {"required": False},
            "enonce": {"required": False},
            "type_correction": {"required": False},
        }

    def validate(self, data):
        # P7.2, point 1 : `enonce` obligatoire — déjà vrai à la création
        # (DevoirCreateSerializer), manquait ici pour la modification.
        if "enonce" in data and not data["enonce"].strip():
            raise serializers.ValidationError({"enonce": "L'énoncé est obligatoire."})
        # P7.3 : deuxième porte d'entrée pour « QCM interdit en correction
        # manuelle » — `QuestionDevoirCreateUpdateSerializer` bloque déjà la
        # création/modification d'une question QCM sur un devoir manuel,
        # mais rien n'empêchait de repasser un devoir déjà pourvu de
        # questions QCM de `auto` à `manuel` via ce serializer-ci.
        if (
            data.get("type_correction") == "manuel"
            and self.instance
            and self.instance.questions.filter(type_question="qcm").exists()
        ):
            raise serializers.ValidationError(
                {
                    "type_correction": "Impossible de passer en correction manuelle : ce devoir contient déjà des questions QCM."
                }
            )
        return data


class ReponseSubmitSerializer(serializers.Serializer):
    reponses = serializers.DictField(child=serializers.CharField(allow_blank=True))


class SoumissionDetailSerializer(serializers.ModelSerializer):
    devoir_titre = serializers.CharField(source="devoir.titre", read_only=True)
    temps_restant = serializers.SerializerMethodField()
    sorties = serializers.IntegerField(read_only=True)
    sorties_max = serializers.IntegerField(source="devoir.tentatives_max", read_only=True)

    class Meta:
        model = SoumissionDevoir
        fields = [
            "id",
            "devoir",
            "devoir_titre",
            "statut",
            "debut",
            "soumis_le",
            "note",
            "commentaire",
            "temps_restant",
            "nb_focus_perdu",
            "est_suspecte",
            "sorties",
            "sorties_max",
        ]

    def get_temps_restant(self, obj):
        return obj.temps_restant_secondes()


class SoumissionResultatSerializer(serializers.ModelSerializer):
    devoir_titre = serializers.CharField(source="devoir.titre", read_only=True)
    # P7.6 : dénominateur de la note, absent jusqu'ici — le frontend du
    # résultat devait sinon deviner `note_sur` (aucun appelant de la route
    # ne le transmettait), même patron que `sorties_max` juste au-dessus.
    note_sur = serializers.IntegerField(source="devoir.note_sur", read_only=True)
    questions_detail = serializers.SerializerMethodField()
    fichier_correction_url = serializers.SerializerMethodField()

    class Meta:
        model = SoumissionDevoir
        fields = [
            "id",
            "devoir_titre",
            "statut",
            "note",
            "note_sur",
            "commentaire",
            "soumis_le",
            "corrige_le",
            "est_en_retard",
            "est_suspecte",
            "questions_detail",
            "fichier_correction_url",
        ]

    def get_questions_detail(self, obj):
        # P7.3 : `choix` (snapshot complet des options, pas seulement celle
        # sélectionnée) — même patron que `_corriger_reponses_exercice`
        # (apps/evaluation/views/exercices.py), absent jusqu'ici côté
        # devoir. Sans lui, un apprenant sur une question QCM ne voyait
        # QUE le texte de son propre choix, sans jamais voir LES options ni
        # laquelle était correcte — cause la plus probable du bug signalé
        # « l'apprenant ne voit pas la réponse correcte ».
        reponses = obj.reponses.select_related("question", "choix").prefetch_related(
            "question__choix"
        )
        result = []
        for rep in reponses:
            question = rep.question
            result.append(
                {
                    "question_id": question.id,
                    "question_enonce": question.enonce,
                    "type_question": question.type_question,
                    "reponse_utilisateur": rep.reponse,
                    "choix_selectionne": rep.choix.texte if rep.choix else None,
                    "choix": (
                        [
                            {"id": c.id, "texte": c.texte, "est_correct": c.est_correct}
                            for c in question.choix.all()
                        ]
                        if question.type_question == "qcm"
                        else []
                    ),
                    "est_correct": rep.est_correct,
                    "points_obtenus": rep.points_obtenus,
                    "points_max": question.points,
                    "bonne_reponse": (
                        question.reponse_attendue
                        if question.type_question == "texte"
                        else (
                            question.choix.filter(est_correct=True).first().texte
                            if question.choix.filter(est_correct=True).exists()
                            else None
                        )
                    ),
                    "reponse_exemple": question.reponse_exemple,
                    # P7.3 : pas de commentaire PAR question dans le modèle
                    # (seul `SoumissionDevoir.commentaire` existe, décision
                    # actée — voir docs/ecarts ou le plan P7.3) — recopié
                    # ici pour que chaque question du résultat porte le mot
                    # justificatif de l'enseignant sans nouveau champ/migration.
                    "commentaire_enseignant": obj.commentaire or "",
                }
            )
        return result

    def get_fichier_correction_url(self, obj):
        if obj.devoir.fichier_correction:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.devoir.fichier_correction.url)
            return obj.devoir.fichier_correction.url
        return None


class OlympiadeListSerializer(serializers.ModelSerializer):
    statut = serializers.SerializerMethodField()
    est_inscrit = serializers.SerializerMethodField()
    nb_inscrits = serializers.SerializerMethodField()
    inscription_ouverte = serializers.SerializerMethodField()
    devoir_id = serializers.IntegerField(source="devoir.id", read_only=True, allow_null=True)
    mon_inscription = serializers.SerializerMethodField()
    niveaux_accessibles = serializers.SerializerMethodField()
    prix_global = serializers.IntegerField(read_only=True)
    recompense = serializers.CharField(read_only=True)
    demande_paiement_participants = serializers.BooleanField(read_only=True)

    class Meta:
        model = Olympiade
        fields = [
            "id",
            "titre",
            "description",
            "edition",
            "date_ouverture_inscription",
            "date_cloture_inscription",
            "date_debut_olympiade",
            "date_fin_olympiade",
            "duree_minutes",
            "nb_questions",
            "note_sur",
            "recompense",
            "prix_global",
            "prix_participation",
            "demande_paiement_participants",
            "statut",
            "est_inscrit",
            "nb_inscrits",
            "inscription_ouverte",
            "devoir_id",
            "mon_inscription",
            "niveaux_accessibles",
        ]

    def get_niveaux_accessibles(self, obj):
        return obj.get_niveaux_accessibles_list()

    def get_statut(self, obj):
        return obj.statut_auto

    def get_est_inscrit(self, obj):
        user = self.context["request"].user
        return InscriptionOlympiade.objects.filter(olympiade=obj, apprenant=user).exists()

    def get_nb_inscrits(self, obj):
        return obj.inscriptions.count()

    def get_inscription_ouverte(self, obj):
        now = timezone.now()
        return obj.date_ouverture_inscription <= now <= obj.date_cloture_inscription

    def get_mon_inscription(self, obj):
        user = self.context["request"].user
        insc = InscriptionOlympiade.objects.filter(olympiade=obj, apprenant=user).first()
        if not insc:
            return None
        return {
            "id": insc.id,
            "note": float(insc.note) if insc.note is not None else None,
            "classement": insc.classement,
            "soumis": insc.soumis,
            "statut": insc.statut,
        }


class OlympiadeDetailSerializer(OlympiadeListSerializer):
    questions = serializers.SerializerMethodField()

    class Meta(OlympiadeListSerializer.Meta):
        fields = OlympiadeListSerializer.Meta.fields + ["questions"]

    def get_questions(self, obj):
        user = self.context["request"].user
        inscription = InscriptionOlympiade.objects.filter(
            olympiade=obj, apprenant=user, soumis=False
        ).first()
        if not inscription or not inscription.session_demarree:
            return []
        if obj.statut_auto != "en_cours":
            return []
        questions = obj.devoir.questions.all() if obj.devoir else []
        data = QuestionDevoirSerializer(questions, many=True).data
        if obj.melanger_questions:
            import random

            data_list = list(data)
            random.seed(str(user.id) + str(obj.id))
            random.shuffle(data_list)
            return data_list
        return data


class OlympiadeCreateSerializer(serializers.ModelSerializer):
    niveaux_accessibles = serializers.ListField(
        child=serializers.CharField(), required=False, default=[]
    )
    recompense = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Olympiade
        fields = [
            "titre",
            "description",
            "edition",
            "date_ouverture_inscription",
            "date_cloture_inscription",
            "date_debut_olympiade",
            "date_fin_olympiade",
            "duree_minutes",
            "nb_questions",
            "note_sur",
            "melanger_questions",
            "melanger_choix",
            "une_seule_session",
            "max_focus_perdu",
            "recompense",
            "prix_participation",
            "demande_paiement_participants",
            "niveaux_accessibles",
        ]
        extra_kwargs = {
            "titre": {"required": True},
            "date_ouverture_inscription": {"required": True},
            "date_cloture_inscription": {"required": True},
            "date_debut_olympiade": {"required": True},
            "date_fin_olympiade": {"required": True},
            "duree_minutes": {"required": False, "default": 120},
            "nb_questions": {"required": False, "default": 30},
            "note_sur": {"required": False, "default": 20},
            "recompense": {"required": False, "allow_blank": True},
            "prix_participation": {"required": False, "default": 0},
            "demande_paiement_participants": {"required": False, "default": False},
        }

    def validate(self, data):
        date_ouv_insc = data.get("date_ouverture_inscription")
        date_clo_insc = data.get("date_cloture_inscription")
        date_debut = data.get("date_debut_olympiade")
        date_fin = data.get("date_fin_olympiade")
        if date_clo_insc >= date_debut:
            raise serializers.ValidationError(
                "La clôture des inscriptions doit être avant le début de l'olympiade."
            )
        if date_debut >= date_fin:
            raise serializers.ValidationError("Le début de l'olympiade doit être avant sa fin.")
        if date_ouv_insc >= date_clo_insc:
            raise serializers.ValidationError(
                "L'ouverture des inscriptions doit être avant leur clôture."
            )
        return data


class InscriptionOlympiadeSerializer(serializers.ModelSerializer):
    olympiade_titre = serializers.CharField(source="olympiade.titre", read_only=True)
    statut_olympiade = serializers.SerializerMethodField()
    temps_restant = serializers.SerializerMethodField()

    class Meta:
        model = InscriptionOlympiade
        fields = [
            "id",
            "olympiade",
            "olympiade_titre",
            "statut",
            "inscrit_le",
            "session_demarree",
            "heure_debut_compo",
            "soumis",
            "soumis_automatique",
            "note",
            "classement",
            "nb_focus_perdu",
            "est_suspecte",
            "statut_olympiade",
            "temps_restant",
        ]

    def get_statut_olympiade(self, obj):
        return obj.olympiade.statut_auto

    def get_temps_restant(self, obj):
        return obj.temps_restant_secondes()


class ClassementOlympiadeSerializer(serializers.ModelSerializer):
    nom_complet = serializers.SerializerMethodField()
    username = serializers.CharField(source="apprenant.username", read_only=True)
    note_sur_20 = serializers.SerializerMethodField()

    class Meta:
        model = ClassementOlympiade
        fields = ["rang", "nom_complet", "username", "note", "note_sur_20", "mention"]

    def get_nom_complet(self, obj):
        u = obj.apprenant
        full = f"{u.first_name} {u.last_name}".strip()
        return full or u.username

    def get_note_sur_20(self, obj):
        # La note d'une olympiade est toujours sur 20 (note_sur=20 fixé à
        # la création, cf. CreerOlympiadeParCadreView) : `note` est déjà
        # directement exploitable, exposé explicitement ici pour que le
        # frontend n'ait pas à connaître cette convention.
        return round(obj.note or 0, 1)

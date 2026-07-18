from rest_framework import serializers
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone

from apps.evaluation.validators import valider_pas_de_cycle_epreuve
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
        fields = ["id", "text", "type", "points", "choix"]

    def get_choix(self, obj):
        if obj.type_question.lower() == "qcm":
            return [c.texte for c in obj.choix.all()]
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
        fields = ["text", "type_question", "points", "bonne_reponse", "choix"]
        extra_kwargs = {
            "points": {"required": False, "default": 1},
            "bonne_reponse": {"required": False, "allow_blank": True},
        }

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
        for c in choix_data:
            choix = Choix.objects.create(
                question=question, texte=c["texte"], est_correct=c.get("est_correct", False)
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


class QuestionDevoirSerializer(serializers.ModelSerializer):
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
        ]


class QuestionDevoirCreateUpdateSerializer(serializers.ModelSerializer):
    choix = serializers.ListField(child=serializers.DictField(), required=False, default=[])

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

    def validate(self, attrs):
        type_q = attrs.get("type_question", "texte")
        choix = attrs.get("choix", [])
        if type_q == "qcm" and len(choix) < 2:
            raise serializers.ValidationError("Un QCM doit avoir au moins 2 choix.")
        if type_q == "texte":
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
        for c in choix_data:
            ChoixReponse.objects.create(
                question=question, texte=c.get("texte", ""), est_correct=c.get("est_correct", False)
            )
        return question

    def update(self, instance, validated_data):
        choix_data = validated_data.pop("choix", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.save()
        if choix_data is not None:
            instance.choix.all().delete()
            for c in choix_data:
                ChoixReponse.objects.create(
                    question=instance,
                    texte=c.get("texte", ""),
                    est_correct=c.get("est_correct", False),
                )
        return instance


# TODO(correction): QuestionDevoirDetailSerializer et QuestionDevoirSerializer
# (ci-dessus) sont strictement identiques (même modèle, mêmes champs) — doublon
# exact découvert lors de l'éclatement de yeki/serializers.py, non documenté
# dans docs/AUDIT_BACKEND.md. Non fusionnés ici pour respecter la règle
# "déplacer, ne pas réécrire" ; à fusionner dans une tâche de correction dédiée
# après confirmation (voir docs/SPLIT_VIEWS.md).
class QuestionDevoirDetailSerializer(serializers.ModelSerializer):
    choix = ChoixReponseSerializer(many=True, read_only=True)

    class Meta:
        model = QuestionDevoir
        fields = ["id", "enonce", "type_question", "points", "ordre", "choix"]


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
    `Devoir.enonces_supplementaires`, @deprecated).
    """

    questions = QuestionDevoirDetailSerializer(many=True, read_only=True)

    class Meta:
        model = EnonceDevoir
        fields = ["id", "contenu", "ordre", "questions"]


class DevoirDetailSerializer(serializers.ModelSerializer):
    questions = QuestionDevoirDetailSerializer(many=True, read_only=True)
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
            "est_publie",
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
            "est_publie",
            "acces_restreint",
            "type_correction",
            "fichier_correction",
            "enonces_supplementaires",
        ]
        extra_kwargs = {
            "titre": {"required": False},
            "enonce": {"required": False},
            "type_correction": {"required": False},
            "est_publie": {"required": False},
        }

    def validate(self, data):
        if self.instance and self.instance.est_publie:
            if "enonce" in data:
                raise serializers.ValidationError(
                    {"enonce": "Un devoir publié ne peut pas être modifié."}
                )
            if "enonces_supplementaires" in data:
                raise serializers.ValidationError(
                    {
                        "enonces_supplementaires": "Un devoir publié ne peut pas avoir de nouveaux énoncés."
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
    questions_detail = serializers.SerializerMethodField()
    fichier_correction_url = serializers.SerializerMethodField()

    class Meta:
        model = SoumissionDevoir
        fields = [
            "id",
            "devoir_titre",
            "statut",
            "note",
            "commentaire",
            "soumis_le",
            "corrige_le",
            "est_en_retard",
            "est_suspecte",
            "questions_detail",
            "fichier_correction_url",
        ]

    def get_questions_detail(self, obj):
        reponses = obj.reponses.select_related("question", "choix").all()
        result = []
        for rep in reponses:
            result.append(
                {
                    "question_id": rep.question.id,
                    "question_enonce": rep.question.enonce,
                    "type_question": rep.question.type_question,
                    "reponse_utilisateur": rep.reponse,
                    "choix_selectionne": rep.choix.texte if rep.choix else None,
                    "est_correct": rep.est_correct,
                    "points_obtenus": rep.points_obtenus,
                    "points_max": rep.question.points,
                    "bonne_reponse": (
                        rep.question.reponse_attendue
                        if rep.question.type_question == "texte"
                        else (
                            rep.question.choix.filter(est_correct=True).first().texte
                            if rep.question.choix.filter(est_correct=True).exists()
                            else None
                        )
                    ),
                    "reponse_exemple": rep.question.reponse_exemple,
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

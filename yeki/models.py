from gettext import translation
import uuid

from django.db import models
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import timedelta
import random
from django.db import transaction
import string


# Profile + PasswordResetOTP : déplacés vers apps/accounts (voir
# docs/MIGRATIONS_APPS.md). Ré-exportés pour ne rien casser.
from apps.accounts.models import Profile, PasswordResetOTP  # noqa: F401,E402


# Parcours, Departement, DemandeAccesFormation, Cours, Module, Lecon,
# SupplementCours, ProgressionLecon, LeconLike + COURSE_COLOR_PALETTE/
# COURSE_COLOR_CHOICES : déplacés vers apps/formation (voir
# docs/MIGRATIONS_APPS.md). Ré-exportés pour ne rien casser.
from apps.formation.models import (  # noqa: F401,E402
    Parcours, Departement, DemandeAccesFormation, Cours, Module, Lecon,
    SupplementCours, ProgressionLecon, LeconLike,
    COURSE_COLOR_PALETTE, COURSE_COLOR_CHOICES,
)


# Exercice, SessionExercice, Question, Choix, ExerciceTentative,
# EvaluationExercice, ReponseExercice, Devoir, QuestionDevoir, ChoixReponse,
# SoumissionDevoir, ReponseDevoir, Olympiade, InscriptionOlympiade,
# ReponseOlympiade, ClassementOlympiade, RangApprenant, ScoreDetail :
# déplacés vers apps/evaluation (voir docs/MIGRATIONS_APPS.md). Ré-exportés
# pour ne rien casser.
from apps.evaluation.models import (  # noqa: F401,E402
    Exercice, SessionExercice, Question, Choix, ExerciceTentative,
    EvaluationExercice, ReponseExercice, Devoir, QuestionDevoir, ChoixReponse,
    SoumissionDevoir, ReponseDevoir, Olympiade, InscriptionOlympiade,
    ReponseOlympiade, ClassementOlympiade, RangApprenant, ScoreDetail,
)


# QuestionForum, ReponseQuestion, LikeReponse, ReponseImage : déplacés vers
# apps/forum (voir docs/MIGRATIONS_APPS.md). Ré-exportés pour ne rien casser.
from apps.forum.models import (  # noqa: F401,E402
    QuestionForum, ReponseQuestion, LikeReponse, ReponseImage,
)


# HistoriqueActivite + enregistrer_activite : déplacés vers apps/core (voir
# docs/MIGRATIONS_APPS.md). Ré-exportés pour ne rien casser.
from apps.core.models import HistoriqueActivite, enregistrer_activite  # noqa: F401,E402


# Paiement, PaiementOlympiade, AbonnementPremium, YekiWallet,
# WalletTransaction, YekiCompteIA, CinetPayTransaction : déplacés vers
# apps/paiement (voir docs/MIGRATIONS_APPS.md). Ré-exportés pour ne rien
# casser.
from apps.paiement.models import (  # noqa: F401,E402
    Paiement, PaiementOlympiade, AbonnementPremium, YekiWallet,
    WalletTransaction, YekiCompteIA, CinetPayTransaction,
)


# YekiIAPersonalite, YekiIAChatHistorique : déplacés vers apps/ia (voir
# docs/MIGRATIONS_APPS.md). Ré-exportés pour ne rien casser.
from apps.ia.models import YekiIAPersonalite, YekiIAChatHistorique  # noqa: F401,E402


# AppVersion : déplacé vers apps/core (voir docs/MIGRATIONS_APPS.md).
from apps.core.models import AppVersion  # noqa: F401,E402


# Notification + creer_notification : déplacés vers apps/notifications
# (voir docs/MIGRATIONS_APPS.md). Ré-exportés pour ne rien casser.
from apps.notifications.models import Notification, creer_notification  # noqa: F401,E402

# Repetiteur : déplacé vers apps/repetiteurs (voir docs/MIGRATIONS_APPS.md).
from apps.repetiteurs.models import Repetiteur  # noqa: F401,E402

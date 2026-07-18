from django.urls import path

from apps.evaluation.views import (
    ListeExercicesCoursView,
    SoumettreEvaluationView,
    HistoriqueEvaluationsView,
    ExerciceDetailView,
    DemarrerExerciceView,
    AjouterExerciceView,
    ListeQuestionsExerciceView,
    AjouterQuestionView,
    ResultatExerciceView,
    SortirExerciceView,
    HistoriqueTentativesExerciceView,
    ExercicesParModuleView,
    VerifierProgressionRangView,
    ModifierExerciceView,
    SupprimerExerciceView,
    ListeDevoirsView,
    DetailDevoirView,
    DemarrerDevoirView,
    SoumettreDevoirView,
    SignalerFocusDevoirView,
    MesSoumissionsView,
    ResultatDevoirView,
    DevoirsCoursView,
    CreerDevoirCoursView,
    ModifierDevoirView,
    ListeQuestionsDevoirView,
    AjouterQuestionDevoirView,
    AjouterEnonceDevoirView,
    SoumissionsDevoirEnseignantView,
    DetailSoumissionEnseignantView,
    CorrigerSoumissionView,
    SoumettreDevoirFichierView,
    StatsDevoirEnseignantView,
    CreerOlympiadeParCadreView,
    ListeOlympiadesView,
    DetailOlympiadeView,
    SInscrireOlympiadeView,
    DemarrerOlympiadeView,
    SoumettreOlympiadeView,
    FocusPeduOlympiadeView,
    ClassementOlympiadeView,
    CalculerClassementView,
    MonInscriptionOlympiadeView,
    OlympiadesPourMoiView,
    ClassementDepartementView,
    MonScoreGlobalView,
    RecalculerClassementView,
    CadreOlympiadesView,
    CadreDevoirsView,
    LierDevoirOlympiadeView,
    CadreModifierOlympiadeView,
    PayerOlympiadeView,
    PayerParticipationOlympiadeView,
)

urlpatterns = [
    # ── EXERCICES ─────────────────────────────────────────────────
    path("cours/<int:cours_id>/exercices/", ListeExercicesCoursView.as_view()),
    path("exercices/<int:exercice_id>/evaluer/", SoumettreEvaluationView.as_view()),
    path("evaluations/historique/", HistoriqueEvaluationsView.as_view()),
    path("exercices/<int:exercice_id>/", ExerciceDetailView.as_view()),
    path("exercices/<int:exercice_id>/demarrer/", DemarrerExerciceView.as_view()),
    path(
        "cours/<int:cours_id>/exercices/ajouter/",
        AjouterExerciceView.as_view(),
        name="exercice-ajouter",
    ),
    path(
        "exercices/<int:exercice_id>/questions/",
        ListeQuestionsExerciceView.as_view(),
        name="question-liste",
    ),
    path(
        "exercices/<int:exercice_id>/questions/ajouter/",
        AjouterQuestionView.as_view(),
        name="question-ajouter",
    ),
    path(
        "evaluations/exercice/<int:exercice_id>/",
        ResultatExerciceView.as_view(),
        name="resultat-exercice",
    ),
    path(
        "exercices/<int:exercice_id>/sortir/", SortirExerciceView.as_view(), name="exercice-sortir"
    ),
    path(
        "evaluations/exercice/<int:exercice_id>/historique/",
        HistoriqueTentativesExerciceView.as_view(),
        name="historique-tentatives-exercice",
    ),
    path(
        "modules/<int:module_id>/exercices/",
        ExercicesParModuleView.as_view(),
        name="exercices-par-module",
    ),
    path(
        "classement/verifier-progression/",
        VerifierProgressionRangView.as_view(),
        name="verifier-progression-rang",
    ),
    path(
        "exercices/<int:exercice_id>/modifier/",
        ModifierExerciceView.as_view(),
        name="exercice-modifier",
    ),
    path(
        "exercices/<int:exercice_id>/supprimer/",
        SupprimerExerciceView.as_view(),
        name="exercice-supprimer",
    ),
    # ── DEVOIRS ───────────────────────────────────────────────────
    path("devoirs/", ListeDevoirsView.as_view(), name="liste-devoirs"),
    path("devoirs/<int:devoir_id>/", DetailDevoirView.as_view(), name="detail-devoir"),
    path("devoirs/<int:devoir_id>/demarrer/", DemarrerDevoirView.as_view(), name="demarrer-devoir"),
    path(
        "devoirs/<int:devoir_id>/soumettre/", SoumettreDevoirView.as_view(), name="soumettre-devoir"
    ),
    path(
        "devoirs/<int:devoir_id>/focus-perdu/",
        SignalerFocusDevoirView.as_view(),
        name="focus-devoir",
    ),
    path("devoirs/mes-soumissions/", MesSoumissionsView.as_view(), name="mes-soumissions"),
    path("devoirs/<int:devoir_id>/resultat/", ResultatDevoirView.as_view(), name="resultat-devoir"),
    path("cours/<int:cours_id>/devoirs/", DevoirsCoursView.as_view(), name="devoirs-cours"),
    path(
        "cours/<int:cours_id>/devoirs/creer/", CreerDevoirCoursView.as_view(), name="devoir-creer"
    ),
    path("devoirs/<int:devoir_id>/modifier/", ModifierDevoirView.as_view(), name="devoir-modifier"),
    path(
        "devoirs/<int:devoir_id>/questions/",
        ListeQuestionsDevoirView.as_view(),
        name="devoir-questions-liste",
    ),
    path(
        "devoirs/<int:devoir_id>/questions/ajouter/",
        AjouterQuestionDevoirView.as_view(),
        name="devoir-question-ajouter",
    ),
    path(
        "devoirs/<int:devoir_id>/enonces/ajouter/",
        AjouterEnonceDevoirView.as_view(),
        name="devoir-enonce-ajouter",
    ),
    path(
        "devoirs/<int:devoir_id>/soumissions/",
        SoumissionsDevoirEnseignantView.as_view(),
        name="devoir-soumissions",
    ),
    path(
        "soumissions/<int:soumission_id>/detail/",
        DetailSoumissionEnseignantView.as_view(),
        name="soumission-detail",
    ),
    path(
        "soumissions/<int:soumission_id>/corriger/",
        CorrigerSoumissionView.as_view(),
        name="soumission-corriger",
    ),
    path(
        "devoirs/<int:devoir_id>/soumettre-fichier/",
        SoumettreDevoirFichierView.as_view(),
        name="devoir-soumettre-fichier",
    ),
    path(
        "devoirs/<int:devoir_id>/stats/", StatsDevoirEnseignantView.as_view(), name="devoir-stats"
    ),
    path("devoirs/cadre/mes-devoirs/", CadreDevoirsView.as_view(), name="cadre-devoirs"),
    # ── OLYMPIADES ────────────────────────────────────────────────
    path(
        "olympiades/cadre/creer/",
        CreerOlympiadeParCadreView.as_view(),
        name="olympiade-creer-cadre",
    ),
    path("olympiades/", ListeOlympiadesView.as_view(), name="liste-olympiades"),
    path("olympiades/<int:olympiade_id>/", DetailOlympiadeView.as_view(), name="detail-olympiade"),
    path(
        "olympiades/<int:olympiade_id>/inscrire/",
        SInscrireOlympiadeView.as_view(),
        name="inscrire-olympiade",
    ),
    path(
        "olympiades/<int:olympiade_id>/demarrer/",
        DemarrerOlympiadeView.as_view(),
        name="demarrer-olympiade",
    ),
    path(
        "olympiades/<int:olympiade_id>/soumettre/",
        SoumettreOlympiadeView.as_view(),
        name="soumettre-olympiade",
    ),
    path(
        "olympiades/<int:olympiade_id>/focus-perdu/",
        FocusPeduOlympiadeView.as_view(),
        name="focus-olympiade",
    ),
    path(
        "olympiades/<int:olympiade_id>/classement/",
        ClassementOlympiadeView.as_view(),
        name="classement-olympiade",
    ),
    path(
        "olympiades/<int:olympiade_id>/calculer-classement/",
        CalculerClassementView.as_view(),
        name="calculer-classement",
    ),
    path(
        "olympiades/<int:olympiade_id>/mon-inscription/",
        MonInscriptionOlympiadeView.as_view(),
        name="mon-inscription-olympiade",
    ),
    path("olympiades/pour-moi/", OlympiadesPourMoiView.as_view(), name="olympiades-pour-moi"),
    path(
        "olympiades/cadre/mes-olympiades/", CadreOlympiadesView.as_view(), name="cadre-olympiades"
    ),
    path(
        "olympiades/<int:olympiade_id>/lier-devoir/",
        LierDevoirOlympiadeView.as_view(),
        name="lier-devoir-olympiade",
    ),
    path(
        "olympiades/<int:olympiade_id>/modifier/",
        CadreModifierOlympiadeView.as_view(),
        name="modifier-olympiade",
    ),
    path(
        "olympiades/<int:olympiade_id>/payer/", PayerOlympiadeView.as_view(), name="payer-olympiade"
    ),
    path(
        "olympiades/<int:olympiade_id>/payer-participation/",
        PayerParticipationOlympiadeView.as_view(),
        name="payer-participation-olympiade",
    ),
    # ── CLASSEMENT ────────────────────────────────────────────────
    path(
        "classement/departement/<int:departement_id>/",
        ClassementDepartementView.as_view(),
        name="classement-departement",
    ),
    path("classement/mon-score/", MonScoreGlobalView.as_view(), name="mon-score"),
    path(
        "classement/recalculer/", RecalculerClassementView.as_view(), name="recalculer-classement"
    ),
]

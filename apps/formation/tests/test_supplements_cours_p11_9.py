"""
Test P11.9 : suppléments de cours — CRUD créé de zéro (le modèle
existait, sans aucune vue/serializer). Arbitrage tranché avec
l'utilisateur : rattaché au cours (obligatoire) + à une leçon
(facultative) — si une leçon est renseignée, le supplément n'apparaît
que sur cette leçon.
"""

import pytest

from apps.formation.models import Module, Lecon, SupplementCours


@pytest.fixture
def cours_avec_principal(cours, user_enseignant_principal):
    cours.enseignant_principal = user_enseignant_principal.profile
    cours.save()
    return cours


@pytest.fixture
def module(cours_avec_principal):
    return Module.objects.create(cours=cours_avec_principal, titre="Module 1", ordre=1)


@pytest.fixture
def lecon(module, cours_avec_principal):
    return Lecon.objects.create(titre="Leçon 1", description="d", module=module, cours=cours_avec_principal)


@pytest.mark.django_db
def test_creer_supplement_cours_par_principal_reussit(client_enseignant_principal, cours_avec_principal):
    reponse = client_enseignant_principal.post(
        f"/api/cours/{cours_avec_principal.id}/supplements/creer/",
        {"titre": "Fiche de révision", "type_contenu": "lien", "url": "https://example.com/fiche"},
        format="json",
    )
    assert reponse.status_code == 201, reponse.data
    assert reponse.data["cours"] == cours_avec_principal.id
    assert reponse.data["lecon"] is None


@pytest.mark.django_db
def test_creer_supplement_par_non_principal_refuse(client_enseignant, cours_avec_principal):
    reponse = client_enseignant.post(
        f"/api/cours/{cours_avec_principal.id}/supplements/creer/",
        {"titre": "Fiche", "type_contenu": "lien", "url": "https://example.com/x"},
        format="json",
    )
    assert reponse.status_code == 403


@pytest.mark.django_db
def test_creer_supplement_type_lien_sans_url_rejete(client_enseignant_principal, cours_avec_principal):
    reponse = client_enseignant_principal.post(
        f"/api/cours/{cours_avec_principal.id}/supplements/creer/",
        {"titre": "Fiche", "type_contenu": "lien"},
        format="json",
    )
    assert reponse.status_code == 400


@pytest.mark.django_db
def test_supplement_avec_lecon_dun_autre_cours_rejete(client_enseignant_principal, cours_avec_principal, departement, user_enseignant_principal):
    autre_cours = cours_avec_principal.__class__.objects.create(
        titre="Autre cours", niveau="Terminale", departement=departement, enseignant_principal=user_enseignant_principal.profile
    )
    autre_module = Module.objects.create(cours=autre_cours, titre="M", ordre=1)
    autre_lecon = Lecon.objects.create(titre="L", description="d", module=autre_module, cours=autre_cours)

    reponse = client_enseignant_principal.post(
        f"/api/cours/{cours_avec_principal.id}/supplements/creer/",
        {"titre": "Fiche", "type_contenu": "lien", "url": "https://x.com", "lecon": autre_lecon.id},
        format="json",
    )
    assert reponse.status_code == 400


@pytest.mark.django_db
def test_lister_supplements_cours_sans_lecon_id_ne_montre_que_ceux_du_cours(client_enseignant_principal, cours_avec_principal, lecon):
    SupplementCours.objects.create(cours=cours_avec_principal, titre="Cours-wide", type_contenu="lien", url="https://a.com")
    SupplementCours.objects.create(cours=cours_avec_principal, lecon=lecon, titre="Lecon-only", type_contenu="lien", url="https://b.com")

    reponse = client_enseignant_principal.get(f"/api/cours/{cours_avec_principal.id}/supplements/")

    assert reponse.status_code == 200
    titres = [s["titre"] for s in reponse.data]
    assert titres == ["Cours-wide"]


@pytest.mark.django_db
def test_lister_supplements_avec_lecon_id_montre_cours_wide_et_lecon(client_enseignant_principal, cours_avec_principal, lecon):
    SupplementCours.objects.create(cours=cours_avec_principal, titre="Cours-wide", type_contenu="lien", url="https://a.com")
    SupplementCours.objects.create(cours=cours_avec_principal, lecon=lecon, titre="Lecon-only", type_contenu="lien", url="https://b.com")

    reponse = client_enseignant_principal.get(
        f"/api/cours/{cours_avec_principal.id}/supplements/", {"lecon_id": lecon.id}
    )

    assert reponse.status_code == 200
    titres = {s["titre"] for s in reponse.data}
    assert titres == {"Cours-wide", "Lecon-only"}


@pytest.mark.django_db
def test_lister_supplements_apprenant_gratuit_refuse(client_apprenant, cours_avec_principal):
    """
    Rectification (demande explicite) : les suppléments de cours sont
    désormais réservés Premium — un apprenant sans abonnement actif dans
    ce département reçoit un 403, plus un accès libre.
    """
    SupplementCours.objects.create(cours=cours_avec_principal, titre="Cours-wide", type_contenu="lien", url="https://a.com")

    reponse = client_apprenant.get(f"/api/cours/{cours_avec_principal.id}/supplements/")

    assert reponse.status_code == 403


@pytest.mark.django_db
def test_lister_supplements_apprenant_premium_reussit(client_apprenant_premium, cours_avec_principal):
    SupplementCours.objects.create(cours=cours_avec_principal, titre="Cours-wide", type_contenu="lien", url="https://a.com")

    reponse = client_apprenant_premium.get(f"/api/cours/{cours_avec_principal.id}/supplements/")

    assert reponse.status_code == 200
    assert len(reponse.data) == 1


@pytest.mark.django_db
def test_supprimer_supplement_par_principal_reussit(client_enseignant_principal, cours_avec_principal):
    supplement = SupplementCours.objects.create(
        cours=cours_avec_principal, titre="À retirer", type_contenu="lien", url="https://a.com"
    )

    reponse = client_enseignant_principal.delete(f"/api/supplements/{supplement.id}/supprimer/")

    assert reponse.status_code == 204
    assert not SupplementCours.objects.filter(id=supplement.id).exists()


@pytest.mark.django_db
def test_supprimer_supplement_par_non_principal_refuse(client_enseignant, cours_avec_principal):
    supplement = SupplementCours.objects.create(
        cours=cours_avec_principal, titre="Protégé", type_contenu="lien", url="https://a.com"
    )

    reponse = client_enseignant.delete(f"/api/supplements/{supplement.id}/supprimer/")

    assert reponse.status_code == 403
    assert SupplementCours.objects.filter(id=supplement.id).exists()

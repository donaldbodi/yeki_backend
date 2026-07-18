from django.conf import settings

from apps.formation.models import Lecon, Cours, ProgressionLecon


def _progression_cours(user, cours_qs):
    """Calcule le % de progression par cours pour cet apprenant."""
    progressions = ProgressionLecon.objects.filter(
        apprenant=user,
        cours__in=cours_qs,
    ).values("cours_id", "terminee")

    prog_map = {}
    for c in cours_qs:
        total = c.nb_lecons or Lecon.objects.filter(cours=c).count()
        if total == 0:
            prog_map[c.id] = 0.0
            continue
        terminees = sum(1 for p in progressions if p["cours_id"] == c.id and p["terminee"])
        prog_map[c.id] = round((terminees / total) * 100, 1)
    return prog_map


def _serialise_cours(c, prog_map):
    """Sérialise un Cours au format attendu par Flutter."""
    ep_nom = "—"
    if c.enseignant_principal:
        ep = c.enseignant_principal
        ep_nom = f"{ep.user.first_name} {ep.user.last_name}".strip() or ep.user.username
    dept = c.departement
    return {
        "id": c.id,
        "title": c.titre,
        "description": c.description_brief or "",
        "enseignant_principal": ep_nom,
        "lessons": c.nb_lecons,
        "assignments": c.nb_devoirs,
        "icon": c.icon_name or "school",
        "color": c.color_code or "#2884A0",
        "progression": prog_map.get(c.id, 0.0),
        # Infos département (= concours/formation)
        "departement_id": dept.id,
        "departement_nom": dept.nom,
        "parcours_nom": dept.parcours.nom if dept.parcours else "",
    }


def _serialise_departement_detail(dept, prog_map=None, include_cours=False, user=None):
    """Sérialise un Departement avec tous les champs enrichis selon son type."""
    from apps.accounts.services import _nom_profil

    cadre_data = None
    if dept.cadre:
        cadre_data = {
            "id": dept.cadre.id,
            "nom": _nom_profil(dept.cadre),
            "email": dept.cadre.user.email,
        }

    image_url = None
    if dept.image:
        image_url = settings.MEDIA_URL + str(dept.image)

    base = {
        "id": dept.id,
        "nom": dept.nom,
        "description": dept.description,
        "image_url": image_url,
        "couleur": dept.couleur,
        "prix": dept.prix,
        "prix_presentiel": dept.prix_presentiel,  # ✅ Ajout
        "type": dept.type_departement,
        "parcours_id": dept.parcours_id,
        "parcours_nom": dept.parcours.nom if dept.parcours else "",
        "parcours_type": dept.parcours.type_parcours if dept.parcours else "",
        "cadre": cadre_data,
        "created_at": dept.created_at.isoformat() if dept.created_at else None,
        "acces_restreint": dept.acces_restreint,
        "est_actif": dept.est_actif,
    }

    # Champs prépa concours
    if dept.est_prepa_concours:
        base.update(
            {
                "est_prepa_concours": True,
                "nom_concours": dept.nom_concours,
                "organisme_concours": dept.organisme_concours,
                "date_limite_inscription": (
                    dept.date_limite_inscription.isoformat()
                    if dept.date_limite_inscription
                    else None
                ),
                "date_examen": dept.date_examen.isoformat() if dept.date_examen else None,
                "arrete_ministeriel": dept.arrete_ministeriel,
                "niveaux_cibles": dept.niveaux_cibles,
                "places_disponibles": dept.places_disponibles,
                "debouches": dept.debouches,
            }
        )
    else:
        base["est_prepa_concours"] = False

    # Champs formation
    if dept.est_formation_metier or dept.est_formation_classique:
        base.update(
            {
                "est_formation_metier": dept.est_formation_metier,
                "est_formation_classique": dept.est_formation_classique,
                "duree_formation": dept.duree_formation,
                "mode": dept.mode,
                "certificat_delivre": dept.certificat_delivre,
                "prerequis": dept.prerequis,
                "objectifs": dept.objectifs,
                "domaine": dept.domaine,
                "ville": dept.ville,
                "est_certifiante": dept.est_certifiante,
            }
        )
    else:
        base["est_formation_metier"] = False
        base["est_formation_classique"] = False

    if include_cours:
        cours_qs = Cours.objects.filter(departement=dept).select_related(
            "enseignant_principal__user"
        )
        pm = prog_map or (_progression_cours(user, cours_qs) if user else {})
        base["cours"] = [_serialise_cours(c, pm) for c in cours_qs]
        base["nb_cours"] = cours_qs.count()
        progs = [_serialise_cours(c, pm)["progression"] for c in cours_qs]
        base["progression_moyenne"] = round(sum(progs) / len(progs), 1) if progs else 0.0
    else:
        nb = Cours.objects.filter(departement=dept).count()
        base["nb_cours"] = nb

    return base

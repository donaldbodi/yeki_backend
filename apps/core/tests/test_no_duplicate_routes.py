from collections import Counter

from django.test import SimpleTestCase

from apps.core.urls import urlpatterns as core_urlpatterns
from apps.accounts.urls import urlpatterns as accounts_urlpatterns
from apps.formation.urls import urlpatterns as formation_urlpatterns
from apps.evaluation.urls import urlpatterns as evaluation_urlpatterns
from apps.forum.urls import urlpatterns as forum_urlpatterns
from apps.paiement.urls import urlpatterns as paiement_urlpatterns
from apps.ia.urls import urlpatterns as ia_urlpatterns
from apps.notifications.urls import urlpatterns as notifications_urlpatterns
from apps.repetiteurs.urls import urlpatterns as repetiteurs_urlpatterns

# Toutes les routes API vivent désormais dans les urls.py des 9 apps
# (éclatement de yeki/urls.py, voir docs/SPLIT_VIEWS.md) — regroupées ici
# pour reproduire exactement le même contrôle qu'avant l'éclatement, sur
# l'ensemble des routes réellement montées sous /api/ par config/urls.py.
# Déplacé depuis yeki/tests.py vers apps/core/tests/ (P1.6 — collecte pytest
# unifiée), logique inchangée.
urlpatterns = (
    core_urlpatterns
    + accounts_urlpatterns
    + formation_urlpatterns
    + evaluation_urlpatterns
    + forum_urlpatterns
    + paiement_urlpatterns
    + ia_urlpatterns
    + notifications_urlpatterns
    + repetiteurs_urlpatterns
)


class UrlPatternsSansDoublonsTest(SimpleTestCase):
    """
    Garde-fou anti-régression : un chemin ou un nom dupliqué dans urls.py
    casse silencieusement (Django ne route jamais que vers la première
    correspondance ; un nom dupliqué rend reverse() imprévisible). Voir
    l'audit des routes dupliquées du 2026-07-16.
    """

    def _chemins_et_noms(self):
        chemins, noms = [], []
        for p in urlpatterns:
            pattern = getattr(p, "pattern", None)
            if pattern is None:  # entrées ajoutées par static(), pas des path()
                continue
            chemins.append(str(pattern))
            if p.name:
                noms.append(p.name)
        return chemins, noms

    def test_aucun_chemin_duplique(self):
        chemins, _ = self._chemins_et_noms()
        doublons = sorted(c for c, n in Counter(chemins).items() if n > 1)
        self.assertEqual(doublons, [], f"Chemins dupliqués dans urls.py : {doublons}")

    def test_aucun_nom_duplique(self):
        _, noms = self._chemins_et_noms()
        doublons = sorted(n for n, c in Counter(noms).items() if c > 1)
        self.assertEqual(doublons, [], f"Noms dupliqués dans urls.py : {doublons}")

"""Stockage de fichiers statiques — migration hébergement (Railway/WhiteNoise).

`CompressedManifestStaticFilesStorage` (le stockage WhiteNoise par défaut,
utilisé via `STORAGES["staticfiles"]`) est STRICT par construction : il
lève une `ValueError` à l'exécution dès qu'un template référence, via
`{% static %}`, un fichier absent du manifeste — donc absent du disque au
moment de `collectstatic`. Révélé en migrant vers Railway (1er hébergement
où `DEBUG=False` ET ce stockage strict cohabitent réellement) : la page
d'accueil (`yeki/templates/landing-page.html`) référence une image
décorative (`images/about-illustration.svg`) qui n'a jamais existé dans le
dépôt — un lien mort resté invisible sous l'ancien stockage non-manifeste
(silencieux, jamais vérifié).

Solution documentée par Django lui-même pour ce cas précis
(`ManifestStaticFilesStorage.manifest_strict`) : `False` fait retomber sur
l'URL non hachée plutôt que de lever une exception — un fichier
statique manquant devient un 404 ciblé sur cette seule ressource, pas une
page 500 entière en panne. Ne masque pas la classe de bug (toujours
visible dans les logs/DevTools réseau), la rend juste non bloquante.
"""

from whitenoise.storage import CompressedManifestStaticFilesStorage


class LenientManifestStaticFilesStorage(CompressedManifestStaticFilesStorage):
    manifest_strict = False

    def hashed_name(self, name, content=None, filename=None):
        # `manifest_strict = False` seul ne suffit pas : il couvre seulement
        # « absent du manifeste mais présent sur le disque ». Ici le fichier
        # est absent du disque LUI-MÊME (jamais livré) — `hashed_name()`
        # (calculé le hash à partir du contenu réel) lève sa propre
        # `ValueError` de façon INCONDITIONNELLE dans ce cas, sans jamais
        # consulter `manifest_strict`. Confirmé en production (Railway,
        # 1er hébergement où ce chemin de code est réellement exercé).
        try:
            return super().hashed_name(name, content, filename)
        except ValueError:
            return name

# Éclatement de yeki/views.py + yeki/serializers.py + yeki/urls.py

Date : 2026-07-16. Résumé de l'éclatement des deux fichiers monolithiques
(`yeki/views.py`, 412 Ko / 10 268 lignes / 188 classes-fonctions ;
`yeki/serializers.py`, 64 Ko / 1 679 lignes / 61 classes) vers les 9 apps
déjà créées (`apps/{core,accounts,formation,evaluation,forum,paiement,ia,
notifications,repetiteurs}`), plus `yeki/views_ia.py` (500 lignes, fichier
séparé contenant tout le code IA — inclus dans cet éclatement, confirmé par
l'utilisateur). Méthode : **déplacement pur, aucune réécriture de logique**
— seuls les imports ont été adaptés vers les nouveaux modules `apps.*`.

## Répartition finale

| App | Fichiers | Contenu |
|---|---|---|
| `core` | `views.py`, `serializers.py`, `urls.py`, `services.py` | `landing`, `HistoriqueActiviteView`/`HistoriqueStatsView`, `LatestVersionView`/`CheckUpdateView`/`AdminVersion*View` (AppVersion) ; `check_role`/`_get_client_ip` (helpers génériques sans modèle) |
| `accounts` | `views/{auth,profil,admin_enseignants,dashboards}.py`, `serializers.py`, `urls.py`, `services.py` | Auth (Register/Login/ForgotPassword/VerifyOTP/ResetPassword/Logout/ChangePassword), Profil, gestion enseignants (AdminGeneral*), dashboards par rôle |
| `formation` | `views/{cours,departements,parcours,dashboards}.py`, `serializers.py`, `services.py`, `urls.py` | Cours/Module/Leçon, Département, Parcours, dashboards cadre/principal |
| `evaluation` | `views/{exercices,devoirs,olympiades,classement}.py`, `serializers.py`, `urls.py`, `management/commands/update_rankings.py` | Exercices, Devoirs, Olympiades, Classement (RankingService) |
| `forum` | `views.py`, `serializers.py`, `urls.py` | Questions/réponses forum, sondage incrémental (repli WebSocket) |
| `paiement` | `views.py`, `urls.py` | CinetPay, Wallet, Abonnement (aucun sérialiseur dans le fichier d'origine) |
| `ia` | `views.py`, `services.py`, `urls.py` | Chat Yéki IA (déplacé depuis `yeki/views_ia.py`, hors périmètre initial de la tâche mais nécessaire pour que l'app `ia` soit fonctionnelle) |
| `notifications` | `views.py`, `serializers.py`, `urls.py` | Notifications in-app |
| `repetiteurs` | `views.py`, `urls.py` | Recherche de répétiteurs (aucun sérialiseur) |

3 apps dépassaient 1500 lignes une fois leurs vues regroupées et ont été
converties en **package** `views/` (comme le shim déjà utilisé pour
`models.py`) : `accounts`, `formation`, `evaluation`. Chaque sous-module
vérifié < 1500 lignes (le plus gros, `apps/evaluation/views/devoirs.py`,
fait 1336 lignes). `forum`, `paiement`, `ia`, `notifications`, `core`,
`repetiteurs` restent des fichiers `views.py` simples.

`config/urls.py` n'inclut plus que les `urls.py` des 9 apps (plus `landing`
importé directement depuis `apps.core.views`) :
```python
urlpatterns = [
    path('', landing, name='landing'),
    path('admin/', admin.site.urls),
    path('api/', include('apps.core.urls')),
    path('api/', include('apps.accounts.urls')),
    path('api/', include('apps.formation.urls')),
    path('api/', include('apps.evaluation.urls')),
    path('api/', include('apps.forum.urls')),
    path('api/', include('apps.paiement.urls')),
    path('api/', include('apps.ia.urls')),
    path('api/', include('apps.notifications.urls')),
    path('api/', include('apps.repetiteurs.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
```

## Chemins publics — aucun changement

Les 163 chemins réels de l'ancien `yeki/urls.py` (hors les 3 lignes
commentées `#path('ia/generer-exercices/', ...)` etc., jamais actives
puisque du code Python commenté) ont été comparés caractère pour caractère
à l'union des 9 nouveaux `urls.py` : **160 chemins réels, tous identiques,
aucun manquant, aucun ajouté.** Le frontend continue d'appeler exactement
les mêmes chemins `/api/...`.

## `yeki/views.py`, `yeki/serializers.py`, `yeki/urls.py`, `yeki/views_ia.py`

Réduits à des stubs documentés (pas supprimés — règle « ne rien perdre ») :
- `yeki/views.py` : ré-exporte uniquement `landing` depuis `apps.core.views`,
  car l'ancien urlconf racine (non actif) `yeki_backend/urls.py` en dépend
  encore (`from yeki.views import landing`).
- `yeki/urls.py` : ré-inclut les 9 apps (même contenu que `config/urls.py`),
  pour la même raison (`yeki_backend/urls.py` fait `include('yeki.urls')`).
- `yeki/serializers.py`, `yeki/views_ia.py` : plus aucun fichier du projet
  ne les importe (vérifié par grep) — laissés vides avec un commentaire
  explicatif.
- `yeki/tests.py` (`UrlPatternsSansDoublonsTest`, créé lors d'une tâche
  précédente) : adapté pour importer les `urlpatterns` des 9 apps au lieu
  de `yeki.urls`, afin de continuer à détecter tout chemin/nom dupliqué à
  l'échelle du projet.

⚠️ **`yeki_backend/urls.py` et `yeki_backend/settings.py`** (l'ancien
urlconf/settings racine, antérieur à la restructuration en `config/`)
existent toujours en parallèle de `config/`. `manage.py` pointe par défaut
sur `config.settings.development` — c'est donc `config/urls.py` qui est
actif localement. Si la production utilise encore `yeki_backend.wsgi`
(configuration WSGI PythonAnywhere non vérifiable depuis cet
environnement), le bascule vers `config.*` doit être confirmée séparément
avant toute suppression de `yeki_backend/{settings,urls}.py` — hors
périmètre de cette tâche, signalé ici pour visibilité.

## Doublon supprimé (autorisé explicitement, P1.1)

`AdminGeneralChangerTypeEnseignantView` était définie deux fois dans
`views.py` (L356-443 morte/écrasée silencieusement, L745-822 active et
routée — confirmé par `docs/AUDIT_BACKEND.md` §2.1). **Version morte
supprimée**, version active conservée telle quelle dans
`apps/accounts/views/admin_enseignants.py`. Comportement perdu par rapport
à la version morte (documenté en commentaire sur place) :
- garde-fou anti no-op (refus si `ancien_type == nouveau_type`) ;
- email de notification à l'enseignant (`_envoyer_email_changement_type_enseignant`,
  conservée dans `apps/accounts/services.py`, actuellement non appelée).

Décision produit à trancher séparément : réintégrer ce comportement ou
non — non fait ici (« déplacer, ne pas réécrire »).

## Bugs pré-existants découverts et *volontairement non corrigés*

Conformément à la règle « déplacer, ne pas réécrire la logique », tous les
bugs suivants ont été déplacés **tels quels**, avec un commentaire
`# TODO(...)` à l'endroit concerné :

1. **`ClassementDepartementView.get()` définie deux fois** dans la même
   classe (`apps/evaluation/views/classement.py`) — découverte nouvelle,
   non documentée dans `docs/AUDIT_BACKEND.md`. La seconde définition
   écrase silencieusement la première (seule celle qui calcule `mon_rang`
   s'exécute réellement).
2. **`ModifierDevoirView`/`PublierDevoirView`** (`apps/evaluation/views/devoirs.py`)
   référencent une variable `cours` jamais définie dans leur méthode →
   `NameError` systématique à chaque appel réel. Bug présent tel quel avant
   l'éclatement.
3. **`CadreModifierOlympiadeView`/`CadreOlympiadesView`** (confirmés dans
   `docs/AUDIT_BACKEND.md` §5.1) : champs `prix_1er`/`prix_2eme`/`prix_3eme`
   supprimés du modèle `Olympiade` mais toujours référencés → perte
   silencieuse de données côté modification, 500 systématique côté listing.
4. **`DepartementUpdateView`** (confirmé dans `docs/AUDIT_BACKEND.md` §5.2) :
   compare `user_type` sur `User` (Django auth) au lieu de `Profile` —
   fonctionnalité cassée à 100 %.
5. **`RankingService`** : `from yeki.ranking_service import RankingService`
   échoue (le fichier ne contient plus la classe — modification locale non
   commitée de l'utilisateur, pré-existante, ne pas toucher). C'est la
   cause exacte du blocage nécessitant `--skip-checks` tout au long de
   cette session. Déplacé tel quel vers `apps/evaluation/views/classement.py`
   — l'échec est désormais **isolé à `apps.evaluation`** au lieu de casser
   le chargement de tout `yeki/views.py` comme avant. La commande de
   management associée (`Command(BaseCommand)`, mal placée dans
   `views.py` à l'origine) a été relogée dans son emplacement Django
   idiomatique : `apps/evaluation/management/commands/update_rankings.py`
   (le commentaire de `ranking_service.py` demandait lui-même cet
   emplacement — pur repositionnement de fichier, aucune logique changée).
6. **`AdminRefuserOlympiadeView`** : la route utilise `<int:pk>` mais la
   méthode `post()` attend un paramètre `olympiade_id` — mismatch
   pré-existant entre `urls.py` et la vue, conservé à l'identique des deux
   côtés.

## Doublon de sérialiseur découvert (non fusionné)

`QuestionDevoirSerializer` et `QuestionDevoirDetailSerializer`
(`apps/evaluation/serializers.py`) sont strictement identiques (même
modèle, mêmes champs). Non documenté dans l'audit. Les deux conservés tels
quels avec un commentaire `# TODO(correction)` — fusion à faire dans une
tâche de correction dédiée après confirmation, cette tâche-ci étant
strictement un déplacement.

## Extraction vers `services.py`

Règle explicite de cette tâche : toute logique de vue de plus de ~30
lignes hors validation d'entrée/formatage de sortie → extraite dans
`services.py`. Appliquée aux helpers déjà factorisés dans le code source
d'origine (`_corriger_reponses_exercice`, `_enregistrer_evaluation_finale`,
`_progression_cours`, `_serialise_cours`, `_serialise_departement_detail`,
les helpers d'email, les helpers Yéki IA `call_claude_api`/
`get_system_prompt`/`get_cours_contexte_complet`/`check_and_debit_wallet`,
etc.) — tous déplacés vers le `services.py` de leur app respective. Les
vues elles-mêmes (classes `APIView`) sont restées dans `views.py`/`views/`
: la totalité de leur code constituait déjà, dans le fichier d'origine, un
mélange indissociable de validation d'entrée/orchestration/formatage de
sortie (pas de bloc de « logique métier pure » isolable sans réécriture),
à l'exception des dashboards volumineux (`PrincipalDashboardAPIView`,
`EnseignantCadreDashboardView`, etc.) qui restent tels quels — leur
extraction aurait constitué une réécriture structurelle allant au-delà du
périmètre « déplacer ».

## Valeurs métier en dur rencontrées, non corrigées

Conformément à « déplacer, ne pas réécrire », ces valeurs restent en l'état
(candidates pour une tâche `ParametreSysteme` séparée) :
- `apps/repetiteurs/views.py` : `tarif: 5000` (FCFA/mois), déjà signalé
  dans `docs/AUDIT_BACKEND.md` §6.
- `apps/ia/services.py` : tarification Claude (`INPUT_TOKEN_PRICE_USD`,
  `OUTPUT_TOKEN_PRICE_USD`, `USD_TO_XAF`, `COMMISSION_YEKI_IA`,
  `MIN_WALLET_BALANCE`).
- `apps/paiement/views.py` : `TARIF_IA_FCFA_PAR_1K_TOKENS`,
  `COMMISSION_YEKI_IA_FCFA`, `TARIF_IA_MIN` (constantes parallèles,
  indépendantes de celles de `apps/ia/services.py` — déjà signalé comme
  tel dans la tâche précédente de déplacement des modèles).
- `apps/evaluation/views/olympiades.py` : tarification progressive des
  olympiades (paliers 50/100/200 apprenants, taux 100 %/80 %/60 %/50 %) et
  split 80/20 cadre/Yéki.

## Vérification

- `wc -l` sur chaque fichier/sous-module `views.py` : toutes < 1500 lignes
  (le plus gros : `apps/evaluation/views/devoirs.py`, 1336 lignes).
- `python -m py_compile` sur tous les fichiers créés/modifiés : aucune
  erreur de syntaxe.
- Import Python direct de chaque module `apps.<app>.{views,serializers,
  urls,services}` (`django.setup()` + `importlib.import_module`) : 25/25
  modules hors `evaluation` importent sans erreur ; `apps.evaluation`
  échoue exactement sur l'`ImportError` `RankingService` attendu et déjà
  documenté (pré-existant, isolé, pas une régression).
- Diff des chemins littéraux `path(...)` : 163 chemins réels dans l'ancien
  `yeki/urls.py` (dont 3 lignes commentées, jamais actives) → 160 chemins
  réels retrouvés à l'identique dans l'union des 9 nouveaux `urls.py`,
  aucun manquant, aucun ajouté.
- `git status` : aucune suppression de fichier constatée en dehors de
  `.gitignore.txt` (issu d'une tâche antérieure, sans rapport) ; `yeki/
  {views,serializers,urls,views_ia,tests}.py` apparaissent modifiés (pas
  supprimés) ; tout le nouveau contenu sous `apps/` et `config/` apparaît
  en fichiers non suivis (`??`), rien n'a été commité (comme demandé).

# Fondations de la couche API — exceptions, pagination, throttling, i18n

Date : 2026-07-17. Avant cette tâche, aucun `EXCEPTION_HANDLER`, aucune
pagination, aucun throttling n'existaient nulle part dans le projet.
`LANGUAGE_CODE`/`TIME_ZONE`/`USE_TZ`/`LocaleMiddleware` étaient déjà
correctement configurés (voir `config/settings/base.py`), sauf un vrai bug
de fuseau horaire caché dans une vue (§5).

## 1. Enveloppe d'erreur unique

`apps/core/exceptions.py` : `custom_exception_handler`, câblé dans
`REST_FRAMEWORK.EXCEPTION_HANDLER` (`config/settings/base.py`). Produit
**toujours** :

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Le formulaire contient des erreurs.",
    "fields": { "enonce": ["Ce champ est obligatoire."] },
    "request_id": "a3f1c9e2"
  }
}
```

`fields` est ce qui permet à `YkForm` (frontend) d'afficher l'erreur sous
le bon champ plutôt qu'un SnackBar générique.

### Codes

| Code | Origine DRF/interne | Status HTTP |
|---|---|---|
| `VALIDATION_ERROR` | `serializers.ValidationError` (via `raise_exception=True`) | 400 |
| `NOT_FOUND` | `Http404` / `NotFound` | 404 |
| `PERMISSION_DENIED` | `PermissionDenied` (DRF ou Django) | 403 |
| `NOT_AUTHENTICATED` | `NotAuthenticated` / `AuthenticationFailed` | 401 |
| `THROTTLED` | `Throttled` (`fields.retry_after` en secondes) | 429 |
| `CONFLICT` | `apps.core.exceptions.ConflictError` (nouveau) | 409 |
| `PAYMENT_REQUIRED` | `apps.core.exceptions.PaymentRequiredError` (nouveau) | 402 |
| `INSUFFICIENT_BALANCE` | `apps.core.exceptions.InsufficientBalanceError` (nouveau) | 402 |
| `SERVER_ERROR` | Tout le reste (non reconnu par DRF) | 500 |

`ConflictError`/`PaymentRequiredError`/`InsufficientBalanceError` héritent
de `YekiAPIException`, qui accepte un `fields=` optionnel pour transporter
des données structurées au-delà du message (ex :
`PaymentRequiredError("...", fields={"prix_participation": 100,
"olympiade_id": 5, "need_payment": True})`) — nécessaire partout où
l'ancienne réponse manuelle incluait des données exploitées par le
frontend en plus du message d'erreur.

### `request_id`

Généré une fois par le handler (`uuid.uuid4().hex[:8]`, même format que les
références CinetPay existantes) et utilisé pour corréler la réponse client
avec le `logger.exception(...)` côté serveur en cas de `SERVER_ERROR`.

### Erreurs "genuinement attrape-tout"

Plutôt que d'ajouter un `raise ServerError(...)` à chaque site, la règle
appliquée partout dans `apps/` : soit le `try/except` est retiré (l'erreur
remonte naturellement au handler), soit il est réduit à
`logger.exception(...)` sans capturer / avec un commentaire expliquant
pourquoi la capture large est volontaire (ex : un envoi d'email qui ne doit
jamais bloquer l'action métier déjà appliquée). Le handler journalise
**lui-même**, une seule fois, toute exception qu'il ne reconnaît pas — pas
besoin de dupliquer ce réflexe dans chaque vue.

### Sweep `raise_exception=True`

Pour que `VALIDATION_ERROR` passe systématiquement par le handler, les 15
sites qui faisaient `if serializer.is_valid(): ... ; return
Response(serializer.errors, 400)` ont été convertis en
`serializer.is_valid(raise_exception=True)`. Comportement de validation
inchangé — seul le mécanisme de transport de l'erreur change.

## 2. Pagination

`apps/core/pagination.py` :
- `YekiPageNumberPagination(PageNumberPagination)` — `page_size=20`,
  `page_size_query_param='page_size'`, `max_page_size=100`. Câblée en
  `DEFAULT_PAGINATION_CLASS`.
- `PaginatedListMixin` — reproduit `paginate_queryset()`/
  `get_paginated_response()` de `generics.GenericAPIView` pour les `APIView`
  brutes (aucune vue de liste du projet n'utilisait `ListAPIView`, donc
  `DEFAULT_PAGINATION_CLASS` seul n'aurait rien paginé automatiquement).
  Pour les vues fonction (`@api_view`), le même résultat s'obtient en
  instanciant directement `YekiPageNumberPagination()`.

Toutes les vues de liste identifiées (~40, listées ci-dessous) reçoivent la
pagination réelle, y compris celles qui étaient plafonnées à la main
(`limit` query param ou `[:N]` codé en dur) — migrées vers le vrai mécanisme
`count`/`next`/`previous`/`results`.

### Vues paginées (par app)

- **evaluation** : `ListeDevoirsView`, `MesSoumissionsView`,
  `DevoirsCoursView`, `ListeQuestionsDevoirView`,
  `SoumissionsDevoirEnseignantView`, `CadreDevoirsView`,
  `ListeOlympiadesView`, `ClassementOlympiadeView`, `CadreOlympiadesView`,
  `OlympiadesPourMoiView`, `AdminOlympiadesAValiderView`,
  `ListeExercicesCoursView`, `ExercicesParModuleView`,
  `HistoriqueTentativesExerciceView`, `HistoriqueEvaluationsView`,
  `ListeQuestionsExerciceView`.
- **formation** : `ModuleListByCoursView`, `liste_cours`,
  `ApprenantCursusAPIView`, `CoursParDepartementView`,
  `LecturesRecentesView`, `liste_parcours`,
  `ApprenantConcoursFormationsView`, `departements_par_parcours`,
  `DemandesAccesDepartementView`, `ApprenantsParDepartementView`.
- **accounts** : `AdminGeneralEnseignantsListView`,
  `AdminGeneralEnseignantsAttenteView`, `liste_enseignants_cadres`,
  `liste_enseignants_secondaires`, `liste_enseignants`,
  `ListeEnseignantsParRoleView`, `liste_enseignants_principaux`,
  `AdminGeneralSearchEnseignantsView` (migrée depuis sa pagination manuelle
  offset/limit maison).
- **forum** : `ListeQuestionsView`.
- **core** : `HistoriqueActiviteView`, `AdminVersionListView`.
- **notifications** : `NotificationsView`.
- **paiement** : `HistoriquePaiementsView`.
- **ia** : `YekiIAChatHistoriqueView`.

### Vues volontairement exclues de la pagination

- **Listes de référence fixes**, pas une ressource métier paginable :
  `ListeNiveauxView`, `PaletteCouleursCoursView` (constante à 12 couleurs),
  `DepartementNiveauxAPIView`. Consommées telles quelles par les dropdowns
  Flutter.
- **`ClassementDepartementView`** (`apps/evaluation/views/classement.py`) :
  bloquée par `RankingService` cassé (pré-existant, non lié à cette tâche —
  voir `docs/MIGRATIONS_APPS.md`), et sa réponse est un objet composite
  (`departement`/`mon_rang`/`classement`/`stats`), pas une liste pure.
- **`ForumMessagesPollingView`** : mécanisme de polling incrémental
  ("nouveaux messages depuis `since`") — le contrat page/next/previous ne
  correspond pas à un flux "tout ce qui est nouveau depuis X".
- **Dashboards composites** (`AdminGeneralDashboardView`,
  `EnseignantCadreDashboardView`, `EnseignantAdminDashboardView`,
  `PrincipalDashboardAPIView` et apparentés) : chacun retourne un instantané
  multi-champs (stats + plusieurs listes imbriquées) consommé atomiquement
  par le frontend, pas une collection homogène unique — paginer un seul
  champ interne casserait la cohérence de l'instantané.
- **`WalletSoldeView`** : `transactions` y est un aperçu récent plafonné
  (`[:30]`) à l'intérieur d'un instantané de solde, pas la ressource
  d'historique — celle-ci existe déjà, correctement paginée, via
  `HistoriquePaiementsView`.

## 3. Throttling

`REST_FRAMEWORK.DEFAULT_THROTTLE_CLASSES` inclut `AnonRateThrottle`,
`UserRateThrottle` (taux globaux `anon`/`user`) et `ScopedRateThrottle`
(sans effet sur une vue qui ne définit pas `throttle_scope` — donc sans
risque d'appliquer un des 4 scopes nommés par erreur).

`DEFAULT_THROTTLE_RATES` (CDC_BACKEND §2.5, taux exacts) :

| Scope | Taux | Vues |
|---|---|---|
| `anon` | 30/min | Global (toute vue non authentifiée) |
| `user` | 120/min | Global (toute vue authentifiée) |
| `login` | 5/min | `LoginView` |
| `otp` | 3/10min | `ForgotPasswordView` (envoi de l'email OTP — pas `VerifyOTPView`, qui a déjà son propre verrou 5-tentatives au niveau modèle `PasswordResetOTP`) |
| `ia` | 10/min | `YekiIAChatAvecHistoriqueView` (l'endpoint facturé — pas `YekiIAChatHistoriqueView`, simple lecture) |
| `paiement` | 10/min | `InitierPaiementCinetPayView`, `WalletRechargerView`, `WalletPayerView`, `PayerParticipationOlympiadeView` |

**`CinetPayWebhookView` est explicitement exclue** de tout throttle scope :
appelée par les serveurs CinetPay (pas un utilisateur), la throttler
risquerait de perdre des confirmations de paiement légitimes en cas de pic
de trafic.

## 4. i18n / fuseau horaire

`LANGUAGE_CODE='fr-fr'`, `TIME_ZONE='Africa/Douala'`, `USE_TZ=True`,
`USE_I18N=True`, `LocaleMiddleware` bien positionné : **déjà corrects avant
cette tâche**, aucun changement nécessaire.

**Décision** : les champs date des réponses JSON de l'API restent en
ISO 8601 (format DRF par défaut, ex. `"2026-08-01T09:00:00+01:00"`) — le
format français ne s'applique qu'à l'admin Django et aux templates serveur
(déjà actif nativement via `LANGUAGE_CODE`). Changer `DATETIME_FORMAT` DRF
casserait `DateTime.parse()` côté Flutter sans bénéfice ; ISO 8601 est le
choix standard pour une API consommée par un client mobile.

### Bug de fuseau horaire corrigé

`CadreModifierOlympiadeView` (`apps/evaluation/views/olympiades.py`) parsait
ses 4 champs date (`date_ouverture_inscription`, `date_cloture_inscription`,
`date_debut_olympiade`, `date_fin_olympiade`) via `parse_datetime()` **sans**
`timezone.make_aware()`, contrairement à `CreerOlympiadeParCadreView`
(`_parse_date` helper) qui le faisait déjà correctement. Une date naïve
envoyée par le frontend (ex. `"2026-08-01T09:00:00"`, sans offset) était
alors traitée comme UTC par Django (`USE_TZ=True`), provoquant un décalage
silencieux d'1h (Douala = UTC+1) entre une olympiade créée et la même
modifiée. **Corrigé** : même garde `is_naive`/`make_aware` que la vue de
création, factorisée en helper local `_parse_date_aware`.

### Bug repéré, hors périmètre (recommandation de suite)

`Olympiade.statut_auto` (propriété du modèle) retourne `"terminée"`/
`"fermée"` **avec accents**, alors que plusieurs vues comparent à
`"terminee"` **sans accent** (`ClassementOlympiadeView.get`,
`CalculerClassementView.post` : `if olympiade.statut_auto not in
["terminee"]`). Cette comparaison ne matche donc jamais la valeur réelle
`"terminée"` — le classement d'une olympiade réellement terminée reste
inaccessible (403 permanent). Ce n'est pas un problème de fuseau horaire
(la propriété calcule juste sur `timezone.now()` correctement) mais un bug
de chaîne de caractères pré-existant, découvert pendant cette tâche mais
non corrigé ici (hors périmètre explicite).

## 5. Recommandations de suite non traitées ici

- **`django_content_type`** (déjà documenté dans `docs/MIGRATIONS_APPS.md`)
  et le **bug `statut_auto` accents** ci-dessus.
- **8 `except Exception`/`except:` dans `yeki/`** (hors `apps/`, périmètre
  de cette tâche) : `yeki/consumers.py` (6, code WebSocket mort, remplacé
  par le polling forum — fichier hors service) et `yeki/signals.py` (2,
  compteurs `nb_lecons`/`nb_devoirs` laissés périmés en cas d'erreur
  silencieuse sur la suppression d'une leçon/d'un devoir).
- **Comparaison "déjà fait" → `ConflictError`** : appliquée uniquement aux
  cas déjà identifiés (inscription olympiade, paiement participation,
  demande d'accès formation) — pas un audit exhaustif de tous les 400 du
  projet pour d'éventuels autres cas de conflit d'état.

## Vérification

- `POST /api/cours/<id>/devoirs/creer/` sans `enonce` → `400` avec
  `error.fields.enonce` renseigné.
- 6 appels `/api/auth/login/` en moins d'1 minute → le 6ᵉ renvoie `429`
  avec `error.code == "THROTTLED"`.
- `GET /api/cours/` (`liste_cours`) et un échantillon des autres vues
  listées en §2 → réponse avec `count`/`next`/`previous`/`results`.
- Grep de contrôle (`apps/`) : plus aucun `except Exception`/`except:` nu
  hors des sites volontairement larges documentés (avec
  `logger.exception(...)` et commentaire justificatif).
- `CadreModifierOlympiadeView` : PATCH avec une date ISO sans offset →
  heure stockée en base identique à celle produite par
  `CreerOlympiadeParCadreView` pour la même chaîne d'entrée.
- `python manage.py check` : blocage résiduel `RankingService` (pré-existant,
  documenté dans `docs/MIGRATIONS_APPS.md`) — pas de nouvelle erreur liée à
  cette tâche.

## 6. P1.6 — Documentation OpenAPI + tests (2026-07-17)

### drf-spectacular

`/api/schema/` (OpenAPI brut) et `/api/docs/` (Swagger UI) exposés (voir
`config/urls.py`, `config/settings/base.py` `SPECTACULAR_SETTINGS`). Les
~160 vues des 9 apps sont annotées `@extend_schema`/`@extend_schema_view`
(résumé, description, tags, `parameters`, `responses`, `examples` en
français), en réutilisant `apps/core/schema_examples.py` (enveloppe
d'erreur par code, pagination) pour éviter la duplication.

**Blocage résolu (obligatoire pour que `/api/docs/` réponde)** :
`apps/evaluation/serializers.py::SoumissionResultatSerializer` référençait
un champ `en_retard` inexistant sur `SoumissionDevoir` (le vrai nom est la
`@property` `est_en_retard`) — faisait planter *toute* génération de schéma
avec une `ImproperlyConfigured`, pas seulement un avertissement. Corrigé
(renommage du seul nom de champ dans `Meta.fields`, aucune autre logique
touchée).

### Rôle `service_client` et inscription obligatoire (CDC §4.2, §13.2)

- `Profile.USER_TYPES` : ajout de `('service_client', 'Service Client')` +
  whitelist `RegisterSerializer.validate_user_type`. Seulement le rôle —
  aucune des fonctionnalités métier associées (validation répétiteur,
  dashboards paiement/retraits) n'est implémentée ici, hors périmètre P1.6.
- `Profile.departement` (nouveau FK vers `formation.Departement`, nullable
  au niveau modèle) + `RegisterSerializer` : `parcours`/`departement`/
  `niveau` passent de facultatifs/absents à **obligatoires**, avec
  validation croisée (le département doit appartenir au parcours fourni).
  **Changement de comportement assumé** : un appel d'inscription existant
  qui n'envoie pas ces 3 champs échouera désormais en 400. Migration
  `apps/accounts/migrations/0002_profile_departement_alter_profile_user_type.py`.

### Blocage `RankingService` — résolu pour de bon

`apps/evaluation/views/classement.py` faisait un import inconditionnel
`from yeki.ranking_service import RankingService`, qui plantait déjà
(fichier vidé par le chantier en cours de l'utilisateur) — ce qui cassait
**tout** `config/urls.py` dès qu'une app était chargée, donc bloquait
`pytest` pour l'ensemble de l'API, pas seulement l'evaluation. Import retiré ;
la classe locale déjà présente sert de stub minimal (ne reproduit que
`_calculer_score_exercices`, pas `obtenir_classement_departement` ni
`mettre_a_jour_rangs_*`) — `ClassementDepartementView`/`CalculerClassementView`
restent non fonctionnelles à l'exécution réelle (AttributeError → 500),
implémentation complète hors périmètre.

### Migration inter-apps — dépendance manquante corrigée

`apps/accounts/migrations/0002_...` (le nouveau champ `Profile.departement`)
fait un vrai `ALTER TABLE` sur `yeki_profile`/référence `yeki_departement` —
des tables physiquement créées par `yeki.0001_initial` (le monolithe
d'origine), pas par `accounts.0001_initial`/`formation.0001_initial` (qui
sont des `SeparateDatabaseAndState`, état seul, sans DDL réel — ces tables
existaient déjà physiquement quand ces migrations ont été écrites). Sans
dépendance explicite vers `('yeki', '0001_initial')`, l'ordre relatif entre
apps n'était pas garanti par le graphe : invisible sur `db.sqlite3`
(toujours réutilisé, jamais reconstruit), mais provoquait un
`OperationalError: no such table` sur une base fraîche construite depuis
zéro (exactement le cas de la base de test pytest). Dépendance ajoutée.

### pytest-django

- `config/settings/test.py` (SQLite en mémoire, email backend `locmem`),
  `pyproject.toml` (`[tool.pytest.ini_options]`, `[tool.ruff]`,
  `[tool.black]` — `yeki/` exclu du lint, monolithe en cours de suppression).
- `conftest.py` (racine du projet — un conftest.py plus profond ne serait pas
  visible par tous les `apps/*/tests/`) : fixtures `parcours`/`departement`/
  `cours`/`exercice`/`devoir`, un utilisateur + client API authentifié par
  rôle (`apprenant`, `enseignant`, `enseignant_principal`, `enseignant_cadre`,
  `enseignant_admin`, `admin`, `service_client`), et un nettoyage automatique
  du cache Django entre tests (le throttling DRF stocke ses compteurs en
  cache, pas en base — sans ce nettoyage un test de throttling hériterait
  du quota consommé par un test précédent).
- Tests (`apps/*/tests/test_*.py`) : authentification (login + 429 au 6ᵉ
  appel), inscription (champs obligatoires + cohérence parcours/département),
  permissions par rôle (`CreerParcoursView`, `CreerOlympiadeParCadreView`),
  pagination (`liste_parcours`), format d'erreur (tous les codes, testés
  directement contre `custom_exception_handler`). Test anti-doublon de
  routes (P0.3) déplacé de `yeki/tests.py` vers
  `apps/core/tests/test_no_duplicate_routes.py` (logique inchangée),
  `yeki/tests.py` supprimé.
- `requirements.txt` : `Django`/`djangorestframework`/`django-cors-headers`/
  `requests` étaient installés dans le venv mais absents de ce fichier
  (lacune pré-existante — un `pip install -r requirements.txt` sur une
  machine propre n'installait pas Django). Ajoutés, avec `python-dateutil`
  et `Pillow` (utilisés par le code mais non installés jusqu'ici).

### CI GitHub Actions

`.github/workflows/ci.yml` (3 jobs : `lint` = ruff + black --check,
`test` = pytest --cov, `secrets` = gitleaks-action). **Aucun dépôt git
n'existe encore dans le projet** (`Projet_Yeki/` comme `yeki_backend/` n'ont
pas de `.git`) : ce workflow ne peut donc pas encore s'exécuter réellement —
`git init` + un remote GitHub sont nécessaires au préalable.

### Bugs pré-existants découverts et documentés (non corrigés)

Repérés via `ruff` en préparant la CI, préservés avec `# noqa` + commentaire
`TODO` explicite (« déplacer, ne pas réécrire ») plutôt que corrigés :
- `Exercice.__str__` défini deux fois (`apps/evaluation/models.py`) — le
  second écrase le premier silencieusement.
- `ClassementDepartementView.get()` défini deux fois — déjà documenté avant
  P1.6.
- Variable `cours` non définie dans `ModifierDevoirView`/`PublierDevoirView`
  (`apps/evaluation/views/devoirs.py`) — déjà documenté avant P1.6.
- Clés de dictionnaire `date_examen`/`date_limite_inscription` dupliquées
  dans `ApprenantConcoursFormationsView._serialiser_departement`
  (`apps/formation/views/parcours.py`) — la 2ᵉ occurrence écrase la 1ʳᵉ avec
  une valeur non sérialisable JSON (`date`/`datetime` brut au lieu
  d'`.isoformat()`).
- `allowed_fields` (restriction de champs modifiables) calculé puis jamais
  consulté dans `ModifierCoursParCadreView.patch`
  (`apps/formation/views/cours.py`) — la restriction pour
  `enseignant_principal` n'est en pratique pas appliquée.
- Paramètre `niveau` documenté mais jamais utilisé pour filtrer dans
  `RepetiteursSearchView` (`apps/repetiteurs/views.py`).
- `choix_correct` calculé puis jamais utilisé dans
  `SoumettreDevoirView`/logique QCM (`apps/evaluation/views/devoirs.py`).
- `has_texte` assigné mais jamais relu (même fichier) — reliquat probable
  d'un signal « nécessite correction manuelle » jamais branché.

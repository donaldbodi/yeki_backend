# Audit des permissions — YÉKI backend

Contexte : `DEFAULT_PERMISSION_CLASSES` était `AllowAny` avec `IsAuthenticated`
commenté. 158 vues déclaraient déjà `IsAuthenticated` explicitement, ce qui
limitait le dégât, mais toute vue future sans `permission_classes` était
publique EN ÉCRITURE par défaut. Ce document liste : (1) le changement de
défaut, (2) les endpoints désormais `AllowAny` et pourquoi, (3) les vues
trouvées sans permission explicite et leur traitement, (4) l'audit
d'appartenance (IDOR) sur les ressources sensibles.

## 1. Changement de défaut

`yeki_backend/settings.py` :
```python
'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated']
```
Toute vue sans `permission_classes` exige désormais une connexion. Les
exceptions sont déclarées explicitement, vue par vue (liste ci-dessous).

## 2. Endpoints `AllowAny` — liste exhaustive et justification

| Endpoint | Vue | Justification |
|---|---|---|
| POST `/api/auth/register/` | `RegisterView` | Création de compte, avant connexion |
| POST `/api/auth/login/` | `LoginView` | Connexion |
| POST `/api/auth/forgot-password/` | `ForgotPasswordView` | Mot de passe oublié — demande |
| POST `/api/auth/verify-otp/` | `VerifyOTPView` | Mot de passe oublié — vérification OTP |
| POST `/api/auth/reset-password/` | `ResetPasswordView` | Mot de passe oublié — réinitialisation |
| POST `/api/paiements/cinetpay/notify/` | `CinetPayWebhookView` | Webhook serveur-à-serveur CinetPay, aucun token utilisateur possible (`authentication_classes = []`) |
| GET `/api/departements/<id>/niveaux/` | `DepartementNiveauxAPIView` | Consulté depuis `register_page.dart` (formulaire d'inscription), avant connexion |
| GET `/api/parcours/` | `liste_parcours` | Consulté depuis `register_page.dart` (`_fetchCursus`), avant connexion |
| GET `/api/parcours/<id>/departements/` | `departements_par_parcours` | Consulté depuis `register_page.dart` (`_fetchDepartements`), avant connexion |
| GET `/api/latest-version/` | `LatestVersionView` | Vérification de version au lancement, avant connexion |
| GET `/api/check-update/` | `CheckUpdateView` | Idem — variante avec comparaison `current_version`, également appelée par `update_service.dart` avant connexion. Coexiste avec `LatestVersionView` (rôles légèrement différents : l'une renvoie la dernière version, l'autre compare à la version courante) — **pas un doublon à supprimer**, vérifié par lecture des deux implémentations + de leurs deux call sites dans `update_service.dart`. |
| GET `/api/landing/` | `landing` | Vue Django classique (`render()`), pas une `APIView` DRF — non concernée par `DEFAULT_PERMISSION_CLASSES` |

Tout le reste des ~149 vues de `yeki/views.py` (+2 de `yeki/views_ia.py`)
déclare `IsAuthenticated` explicitement et n'est pas dans cette liste.

## 3. Vues trouvées avec `permission_classes` commenté (corrigées)

Trouvées par relecture systématique de `views.py` (149 classes + 11 vues
`@api_view`). Toutes avaient un commentaire `#permission_classes = [...]` ou
`#@permission_classes([...])` — verrouillage commencé puis jamais terminé.
Restaurées à `IsAuthenticated` :

| Vue | Endpoint | Décision | Raison |
|---|---|---|---|
| `HistoriqueEvaluationsView` | GET `evaluations/historique/` | IsAuthenticated | Filtre déjà par `user=request.user` — oubli manifeste |
| `LogoutView` | POST `auth/logout/` | IsAuthenticated | Utilise `request.user.auth_token` |
| `liste_enseignants_cadres` | GET `enseignants_cadres/` | IsAuthenticated | Utilisé uniquement dans les dashboards enseignant (post-connexion) |
| `liste_enseignants_secondaires` | GET `enseignants_secondaires/` | IsAuthenticated | Idem |
| `liste_enseignants` | GET `enseignants/` | IsAuthenticated | Idem |
| `liste_enseignants_principaux` | GET `enseignants_principaux/` | IsAuthenticated | Idem |
| `parcours_unique` | GET `parcours/<id>/` | IsAuthenticated | Idem |
| `liste_parcours` | GET `parcours/` | **AllowAny** (exception, voir §2) | Utilisé par `register_page.dart` avant connexion — verrouiller aurait cassé l'inscription |
| `departements_par_parcours` | GET `parcours/<id>/departements/` | **AllowAny** (exception, voir §2) | Idem |

⚠️ Les deux derniers ont d'abord été mis à `IsAuthenticated` pour coller à la
liste demandée, puis corrigés après vérification du frontend (`Dio().get(...)`
sans en-tête `Authorization` dans `register_page.dart`, lignes 150 et 178).
Toujours vérifier les appelants avant de fermer un endpoint qui "sonne"
interne.

## 4. `yeki/permissions.py` — classes créées

`IsApprenant`, `IsEnseignant`, `IsAdminGeneral` (rôle, via `Profile.user_type`),
`IsOwner` (portée générique, essaie les champs `utilisateur`/`apprenant`/`user`),
`IsCadreDuDepartement`, `IsPrincipalDuCours`, `IsEnseignantAdminDuParcours`
(portée hiérarchique Parcours→Departement→Cours).

`IsServiceClient` : **TODO(arbitrage)**. Demandée dans la tâche mais aucun
rôle « service client » n'existe dans `Profile.USER_TYPES` ni ailleurs dans
le modèle de données (seule trace : le texte affiché à l'apprenant « Contactez
le service client »). Implémentée en fail-closed (refuse tout le monde) en
attendant une réponse sur le mapping réel — décision utilisateur : garder en
fail-closed jusqu'à ce qu'un rôle/process service client soit modélisé.

Remarque de nommage : la tâche demandait `apps/core/permissions.py`, mais le
projet est une app Django unique `yeki/` (pas de dossier `apps/`) — créé à
`yeki/permissions.py` en conséquence.

## 5. Audit d'appartenance (IDOR)

Modèles audités : `YekiWallet`/`WalletTransaction`, `Paiement`/
`PaiementOlympiade`, `SoumissionDevoir`, `Profile`, `ExerciceTentative`
(seul modèle « Tentative* »), `ProgressionLecon`.

| Endpoint | Méthode | Permission | Contrôle d'appartenance | Risque |
|---|---|---|---|---|
| `/api/wallet/solde/` | GET | IsAuthenticated | Oui — toujours `request.user`, aucun id dans l'URL | Aucun |
| `/api/wallet/recharger/` | POST | IsAuthenticated | Oui — `request.user` | Aucun |
| `/api/wallet/payer/` | POST | IsAuthenticated | Oui — `request.user` | Aucun |
| `/api/wallet/verifier-iap/` | POST | IsAuthenticated | Oui — `request.user` | Aucun |
| `/api/paiements/historique/` | GET | IsAuthenticated | Oui — `Paiement.objects.filter(utilisateur=request.user)` | Aucun |
| `/api/paiements/cinetpay/initier/` | POST | IsAuthenticated | Oui — `CinetPayTransaction` lié à `request.user` | Aucun |
| `/api/paiements/cinetpay/verifier/<reference>/` | GET | IsAuthenticated | Oui — `get_object_or_404(..., user=request.user)` | Aucun |
| `/api/paiements/cinetpay/notify/` | POST | AllowAny | N/A (webhook) — retrouve l'utilisateur via `transaction_id`/`reference`, jamais un id fourni par l'appelant | Aucun (par construction) |
| `/api/olympiades/<id>/payer-participation/` | POST | IsAuthenticated | Oui — `apprenant=request.user` | Aucun |
| `/api/olympiades/<id>/inscrire/` (contrôle paiement) | GET | IsAuthenticated | Oui — `filter(apprenant=request.user, ...)` | Aucun |
| `/api/devoirs/<devoir_id>/soumissions/` | GET | IsAuthenticated | Oui — `_profile_autorise_gerer_devoir(devoir, profile)` (prof principal du cours ou organisateur olympiade) | Aucun |
| `/api/soumissions/<soumission_id>/corriger/` | PATCH | IsAuthenticated | Oui — même contrôle avant écriture de la note | Aucun |
| `/api/soumissions/<soumission_id>/detail/` | GET | IsAuthenticated | Oui — même contrôle avant lecture des réponses d'un autre apprenant | Aucun |
| `/api/devoirs/<devoir_id>/stats/` | GET | IsAuthenticated | Oui — même contrôle | Aucun |
| Endpoints apprenant sur devoirs/soumissions propres (`DetailDevoirView`, `DemarrerDevoirView`, `SortirDevoirView`, `SoumettreDevoirView`, `ResultatDevoirView`, `MesSoumissionsView`, `SoumettreDevoirFichierView`) | GET/POST | IsAuthenticated | Oui — `utilisateur=request.user` partout | Aucun |
| `/api/profil/me/`, `/update/`, `/delete/`, `/stats/` | GET/PATCH/DELETE | IsAuthenticated | Oui — `request.user`/`request.user.profile`, aucun id dans l'URL | Aucun |
| `/api/admin-general/enseignants/<profile_id>/modifier/` | PATCH | IsAuthenticated | Oui, mais par rôle : gate `profile_admin.user_type != 'admin'` → 403. Un admin général peut gérer n'importe quel profil enseignant — **voulu**, pas une fuite apprenant→apprenant | Faible (comportement intentionnel) |
| `/api/admin-general/enseignants/<profile_id>/activer/` | POST | IsAuthenticated | Idem | Faible (intentionnel) |
| `/api/admin-general/enseignants/<profile_id>/changer-type/` | PATCH | IsAuthenticated | Idem | Faible (intentionnel) |
| Évaluations d'exercices (`SoumettreEvaluationView`, `HistoriqueTentativesExerciceView`, `ResultatExerciceView`) | GET/POST | IsAuthenticated | Oui — `ExerciceTentative.objects.filter(apprenant=user, exercice=exercice)`, jamais d'id de tentative dans l'URL | Aucun |
| Progression de leçons (`LecturesRecentesView`, `MarquerLeconVueView`, calculs internes) | GET/POST | IsAuthenticated | Oui — toujours `apprenant=request.user` | Aucun |
| `/api/stats/enseignant-admin/<pk>/` | GET | IsAuthenticated | **Corrigé pendant cet audit** — voir ci-dessous | Était : Faible→Moyen (aucune donnée financière, mais fuite de comptage inter-comptes) |

### Correction appliquée : `EnseignantAdminStatsView`

Avant : `IsAuthenticated` seul, `pk` d'un `enseignant_admin` pris tel quel →
n'importe quel utilisateur connecté (y compris un apprenant) pouvait
consulter les statistiques (nombre de départements/cours/leçons) de
n'importe quel enseignant_admin en changeant `pk` dans l'URL.

Après : ajout d'un contrôle explicite avant de calculer les stats —
autorisé uniquement si `request.user == admin_user` (l'intéressé lui-même)
ou si le profil de `request.user` a `user_type == 'admin'` (admin général).
Sinon 403.

### Conclusion de l'audit IDOR

Sur les cinq familles de ressources demandées (wallet, paiement, soumission,
profil, tentative), **aucune fuite apprenant A → apprenant B n'a été
trouvée** : le code existant filtre systématiquement par `request.user` (ou
vérifie un rôle/relation métier explicite) avant de renvoyer ou modifier une
ressource. Le seul gap réel trouvé (`EnseignantAdminStatsView`) est hors des
5 familles demandées mais a été corrigé par prudence (portée : comptages
agrégés, pas de données personnelles ni financières).

## 6. Vérifications

```
GET /api/wallet/solde/ sans token → 401
```
Confirmé — `DEFAULT_PERMISSION_CLASSES` impose désormais `IsAuthenticated` à
toute vue sans permission explicite ; `WalletSoldeView` n'en déclare pas de
plus permissive, donc DRF renvoie 401 avant même d'exécuter `get()`.

```
apprenant A lit le wallet de B → 403
```
Ce scénario tel que décrit ne peut pas être reproduit tel quel : **aucun
endpoint n'accepte un id de wallet/utilisateur en paramètre** — `wallet/solde/`,
`wallet/recharger/`, `wallet/payer/`, `wallet/verifier-iap/` résolvent
toujours le wallet via `request.user`, jamais via un paramètre fourni par
l'appelant. Il n'y a donc pas de 403 à produire ici : la garantie équivalente
est plus forte qu'un contrôle 403 — l'accès à un autre wallet n'est
structurellement pas possible via ces routes, quel que soit le rôle de A.
Si un futur endpoint `GET /api/wallet/<id>/` est ajouté, il DOIT utiliser
`IsOwner` (`yeki/permissions.py`) plutôt qu'`IsAuthenticated` seul.

```
Lister les endpoints AllowAny et vérifier qu'ils sont tous justifiés
```
Voir tableau §2 — 11 vues DRF (+1 vue Django classique `landing`), chacune
justifiée individuellement (flux avant connexion : inscription, connexion,
mot de passe oublié, ou webhook serveur-à-serveur, ou vérification de
version).

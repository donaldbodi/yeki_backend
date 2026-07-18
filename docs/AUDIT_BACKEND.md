# Audit backend YÉKI — état des lieux avant refonte

Date : 2026-07-17. Portée : `yeki_backend/yeki_backend/yeki/` (models.py,
views.py, urls.py, serializers.py). Document de recherche uniquement —
aucun fichier de code n'a été modifié pour le produire.

## Préalable — documents de référence

Les documents cités dans la consigne existent, sous des noms différents :
- `docs/CDC_DESIGN_v4.docx` → en réalité `docs/YEKI_CDC_v4_DESIGN.docx`
- `docs/CDC_BACKEND_v4.docx` → en réalité `docs/YEKI_CDC_v4_BACKEND.docx`
- `docs/maquette/` → présent tel quel (fichiers `.dc.html`, `assets/`,
  `screenshots/`, plus un ancien `Cahier_des_charges_YEKI_v3.docx`/`.txt`
  dans `uploads/`)
- `consigne.docx`, `modif2.docx` → **absents**, introuvables dans les deux
  dépôts (frontend et backend).

Les `.docx` n'ont pas été ouverts (format binaire, hors des outils texte
utilisés pour cet audit). La classification « app cible » ci-dessous est
donc **déduite du code** (nom de modèle/vue, domaine métier manipulé), pas
du CDC — à confronter manuellement au CDC_BACKEND si une classification
officielle existe déjà.

---

## 1. Les 46 modèles de `models.py`

Total confirmé : 46 classes `class X(models.Model)`, correspond exactement
au chiffre annoncé.

| # | Modèle | L. début | L. fin approx. | Relations clés | App cible (déduite) |
|---|---|---|---|---|---|
|1|`Profile`|16|43|O2O→User|auth/profil|
|2|`PasswordResetOTP`|46|85|FK→User `reset_otps`|auth/profil|
|3|`Parcours`|90|118|FK→Profile `parcours_admin` (limit_choices_to enseignant_admin)|cours/pédagogie|
|4|`Departement`|122|368|FK→Parcours `departements`; FK→Profile `departements_cadre` (limit_choices_to enseignant_cadre); M2M→User `formations_autorisees`|cours/pédagogie|
|5|`DemandeAccesFormation`|371|399|FK→User `demandes_acces`; FK→Departement `demandes_acces` (related_name dupliqué entre 2 modèles, toléré)|cours/pédagogie|
|6|`Cours`|429|527|FK→Profile `cours_principal` (enseignant_principal); M2M→Profile `cours_secondaires`; FK→Departement `cours`|cours/pédagogie|
|7|`Module`|530|552|FK→Cours `modules`|cours/pédagogie|
|8|`Lecon`|556|598|FK→Module `lecons`(null); FK→Cours `lecons`; FK→Profile `created_by`|cours/pédagogie|
|9|`SupplementCours`|601|632|FK→Lecon `supplements`|cours/pédagogie|
|10|`ProgressionLecon`|635|652|FK→User `progressions`; FK→Lecon `progressions`; FK→Cours `progressions` — **indentation à 6 espaces, bizarrerie de style**|cours/pédagogie|
|11|`LeconLike`|655|666|FK→User `lecon_likes`; FK→Lecon `likes`|cours/pédagogie|
|12|`Exercice`|669|732|FK→Cours `exercices`; FK→Module(SET_NULL); FK→Lecon(SET_NULL); M2M self `epreuves_parentes`|devoirs/exercices|
|13|`SessionExercice`|735|747|FK→User; FK→Exercice (sans related_name)|devoirs/exercices|
|14|`Question`|750|763|FK→Exercice `questions`|devoirs/exercices|
|15|`Choix`|766|771|FK→Question `choix`|devoirs/exercices|
|16|`ExerciceTentative`|774|814|FK→User `tentatives_exercice`; FK→Exercice `tentatives`|devoirs/exercices|
|17|`EvaluationExercice`|817|837|FK→User; FK→Exercice; FK→ExerciceTentative(SET_NULL)|devoirs/exercices|
|18|`ReponseExercice`|840|856|FK→EvaluationExercice `reponses`; FK→Question|devoirs/exercices|
|19|`Devoir`|863|972|FK→Cours `devoirs`(SET_NULL); FK→Profile `devoirs_crees`(SET_NULL); FK self `duplicatas`(SET_NULL)|devoirs/exercices|
|20|`QuestionDevoir`|975|996|FK→Devoir `questions`|devoirs/exercices|
|21|`ChoixReponse`|999|1005|FK→QuestionDevoir `choix`|devoirs/exercices|
|22|`SoumissionDevoir`|1008|1065|FK→User `soumissions`; FK→Devoir `soumissions`; FK→User `corrections`(SET_NULL)|devoirs/exercices|
|23|`ReponseDevoir`|1068|1080|FK→SoumissionDevoir `reponses`; FK→QuestionDevoir; FK→ChoixReponse(SET_NULL)|devoirs/exercices|
|24|`Olympiade`|1082|1207|O2O→Devoir `olympiade_config`; FK→Profile `olympiades_organisees`(SET_NULL); FK→User(SET_NULL) — **`prix_1er/2eme/3eme` commentés/supprimés L1145-1148, voir §5**|olympiades|
|25|`InscriptionOlympiade`|1210|1253|FK→Olympiade `inscriptions`; FK→User `inscriptions_olympiade`|olympiades|
|26|`ReponseOlympiade`|1256|1266|FK→InscriptionOlympiade `reponses`; FK→QuestionDevoir; FK→ChoixReponse(SET_NULL)|olympiades|
|27|`ClassementOlympiade`|1269|1279|FK→Olympiade `classement`; FK→User|olympiades|
|28|`QuestionForum`|1287|1330|FK→User `questions_forum`|forum|
|29|`ReponseQuestion`|1337|1348|FK→QuestionForum `reponses`; FK→User `reponses_forum`|forum|
|30|`LikeReponse`|1355|1360|FK→ReponseQuestion `likes`; FK→User|forum|
|31|`ReponseImage`|1363|1370|FK→ReponseQuestion `images`|forum|
|32|`HistoriqueActivite`|1378|1462|FK→User `historique_activites`|administration|
|33|`Paiement`|1506|1564|FK→User `paiements`; FK→Olympiade(SET_NULL) — commission 15% en commentaire, voir §6|paiement/wallet|
|34|`PaiementOlympiade`|1571|1609|FK→User `paiements_olympiade`; FK→Olympiade `paiements_participants`|paiement/wallet|
|35|`AbonnementPremium`|1616|1654|O2O→User `abonnement`; FK→Paiement(SET_NULL) — `TARIFS` en dur L1626, voir §6|paiement/wallet|
|36|`YekiIAPersonalite`|1661|1753|FK→Cours `ia_personnalites`|IA/notifications|
|37|`YekiWallet`|1768|1817|O2O→User `wallet`|paiement/wallet|
|38|`WalletTransaction`|1820|1841|FK→YekiWallet `transactions`|paiement/wallet|
|39|`YekiCompteIA`|1844|1864|aucune (singleton pk=1)|paiement/wallet|
|40|`YekiIAChatHistorique`|1867|1910|FK→User `ia_chat_historique`; FK→Cours `ia_chat_messages`|IA/notifications|
|41|`CinetPayTransaction`|1913|1933|FK→User `cinetpay_transactions`|paiement/wallet|
|42|`AppVersion`|1936|1994|aucune|administration|
|43|`RangApprenant`|2001|2042|FK→User `rangs`; FK→Departement `rangs_apprenants`|cours/pédagogie (classement)|
|44|`ScoreDetail`|2045|2071|FK→RangApprenant `details`|cours/pédagogie (classement)|
|45|`Notification`|2078|2126|FK→User `notifications`|notifications|
|46|`Repetiteur`|2160|2197|FK→Profile `fiches_repetiteur` (limit_choices_to user_type__in=['enseignant','enseignant_secondaire'] — **valeur morte, voir §7**); FK→Cours `repetiteurs` — `tarif_mensuel` default=7500 en dur|forum/annexe|

### Champs suspects / contradictoires additionnels (modèles)

- `Devoir` (L879-881) et `Olympiade` (L1114-1116) : champs `matiere`/`niveau`
  commentés (« SUPPRESSION DES CHAMPS ») — cohérent, aucun résidu d'usage
  trouvé côté vues/serializers pour ceux-là (contrairement à prix_1er/2e/3e).
- `Departement.prix` (générique, L171) vs `prix_mensuel`/`prix_annuel`/
  `prix_presentiel_mensuel`/`prix_presentiel_annuel` (L308-319) :
  chevauchement de champs de tarification **assumé explicitement** par un
  commentaire L307 (« restent en base pour compatibilité ascendante »).
- `Departement.couleur` default='#2884A0' (L163) codé en dur, incohérent
  avec le pattern `COURSE_COLOR_PALETTE` utilisé pour `Cours`.
- `Cours.nb_apprenants` (L454) : champ mort/jamais mis à jour par aucun
  signal (contrairement à `nb_lecons`/`nb_devoirs`), **admis explicitement**
  par un commentaire dev dans `views.py:5893` (« jamais mis à jour »).

---

## 2. Endpoints de `views.py` / `urls.py`

**Comptage réel** : 163 appels `path(...)` dans `urls.py` (~162 endpoints
uniques), pas 192. Écart expliqué en bonne partie par le §2.2 ci-dessous
(vues orphelines laissées en place après un nettoyage récent des routes
dupliquées : route supprimée, code mort non retiré).

### 2.1 — Doublon CRITIQUE : classe redéfinie deux fois, comportements différents

**`AdminGeneralChangerTypeEnseignantView`** existe **deux fois** dans
`views.py` :
- 1ʳᵉ définition : L356-441 (**code mort** — en Python, la seconde
  définition écrase silencieusement la première dans le namespace du
  module ; jamais exécutée quelle que soit la requête)
- 2ᵉ définition (active) : L745-815, routée
  `PATCH admin-general/enseignants/<profile_id>/changer-type/`

Comportement perdu par l'écrasement :
- La version morte (L356) refusait un changement de type vers la même
  valeur (`if ancien_type == nouveau_type: return 400`) — **la version
  active ne le fait pas**, elle réécrit `user_type` même sans changement.
- La version morte envoyait un **email de notification** à l'enseignant
  après changement — **la version active n'envoie aucun email** (juste
  `enregistrer_activite(...)`).

À nettoyer en priorité : supprimer la version morte, et décider si le
comportement perdu (garde anti-no-op + email) doit être réintégré dans la
version active — **question ouverte, pas tranchée par cet audit** (c'est un
choix produit, pas un bug de code à corriger seul).

### 2.2 — 8 vues orphelines (code présent, jamais routées)

- `AdminGeneralEnseignantsListView` (L70)
- `AdminGeneralDesactiverEnseignantView` (L215) — à vérifier si une
  fonctionnalité de désactivation d'enseignant est censée être accessible
  côté front et ne l'est plus.
- `CoursUpdateView` (L2191) — remplacée en pratique par
  `ModifierCoursParCadreView` (routée), l'ancienne classe subsiste sans route.
- `SortirDevoirView` (L3818) — doublon fonctionnel quasi certain de
  `SignalerFocusDevoirView` (routée sur `devoirs/<id>/focus-perdu/`), les
  deux gèrent la « sortie de focus » pendant un devoir ; un seul est routé.
- `DupliquerDevoirView` (L4013), `ModifierQuestionDevoirView` (L4112),
  `SupprimerQuestionDevoirView` (L4158), `PublierDevoirView` (L4253) —
  chaîne complète de gestion de devoirs (dupliquer/modifier
  question/supprimer question/publier) codée mais non exposée. Si le
  frontend attend ces actions (boutons « dupliquer », « publier »), elles
  sont **actuellement inaccessibles** malgré du code prêt.

### 2.3 — Alias de route (fonctionnel mais fragile, pas un bug)

`apprenant/prepa-concours/` et `apprenant/formations/` pointent vers la
**même vue** `ApprenantConcoursFormationsView`, qui différencie son
comportement en inspectant `request.path` (L8676-8679). Couplage fragile à
la chaîne d'URL plutôt qu'à un paramètre explicite — à surveiller si l'URL
change un jour côté front.

### 2.4 — Décompte par section (RAS sauf mention)

AUTHENTIFICATION (7, AllowAny pré-connexion cohérent) · PROFIL (4, RAS) ·
ENSEIGNANTS (5, RAS) · DASHBOARD (5, voir §3 L1223) · STATISTIQUES (2, RAS)
· PARCOURS (7+1 admin, RAS) · DÉPARTEMENTS (6+4 accès+1 admin, voir §5.2) ·
COURS (5 routés, `CoursUpdateView` orpheline) · LEÇONS (6, RAS) · MODULES
(4, RAS) · EXERCICES (16, RAS) · DEVOIRS (18 routés + 4 orphelins, voir
§2.2) · OLYMPIADES (~14, voir §2.1/§5.1) · FORUM (8, RAS) · YEKI IA (2
actifs, tarifs en dur §6) · NOTIFICATIONS (4, RAS) · PAIEMENT/WALLET (2+3
CinetPay+4 wallet, `except` avalant des erreurs de vérification §3,
valeurs FCFA en dur §6) · HISTORIQUE (2, RAS) · ADMIN GÉNÉRAL enseignants
(≈8, contient le doublon §2.1) · ADMIN versions (4, RAS) · PRINCIPAL (3+1, RAS).

---

## 3. Les blocs `except Exception` génériques (30 trouvés, proche des 28 annoncés)

| L. | Ce qui est avalé |
|---|---|
| 55 | `_is_premium()` : erreur d'accès à `user.abonnement` → traité comme "pas premium", sans log. |
| 254 | Échec email désactivation enseignant → loggé, désactivation appliquée quand même. |
| 412 | Idem email changement de type (dans la classe **morte** L356). |
| 625 | Idem email activation enseignant → loggé, activation non bloquée. |
| 1179 | Erreur stats d'un devoir dans une boucle dashboard → `print()`, devoir ignoré silencieusement des stats. |
| 1190 | Idem au niveau "cours" englobant → `print()`, cours ignoré silencieusement. |
| 1223 | Erreur générale dashboard cadre → `traceback.print_exc()` (console seulement) puis **données par défaut factices renvoyées en 200** comme si tout allait bien. |
| 1698 | Département du profil apprenant introuvable → 404 propre mais masque la cause réelle. |
| 2396 | Erreur `ProgressionLecon` → liste vide 200, masque l'erreur technique. |
| 2440 | Erreur marquage leçon vue → 500 avec `str(e)` (fuite d'info technique, mais visible). |
| 2981 | Duplicata du pattern L1698. |
| 3561 | Suppression compte : échec suppression token auth → `pass`, compte supprimé quand même. |
| 3669 | Changement mot de passe : échec suppression ancien token → `pass`, nouveau token généré quand même. |
| 5553 | Profil organisateur olympiade introuvable → 400 générique, masque la vraie cause. |
| 6520 | Parsing JSON `niveaux_accessibles` échoue → repli silencieux sur split virgules (voulu, mais avale toute erreur JSON réelle). |
| 6883 | Email changement de type (2ᵉ occurrence, code actif) → loggé, appliqué sans email. |
| 6896 | Email activation enseignant (2ᵉ occurrence) → loggé, appliqué sans email. |
| 7626 | URL image département échoue → `image_url=None`, aucun log. |
| 8020 | `except:` nu — parsing `niveaux_accessibles` création département, identique à 6520 mais sans préciser le type d'exception. |
| 8162 | `except:` nu — même pattern, autre vue de modification département. |
| 8733 | URL absolue image département échoue → `pass` (2ᵉ occurrence du même problème que 7626, code dupliqué). |
| 9228 | Webhook CinetPay : erreur → transaction `failed` sauvegardée, 500 avec message — correctement géré mais tout type d'exception (y compris bug de code) traité comme "erreur CinetPay". |
| 9362 | Vérification paiement CinetPay : erreur parsing réponse → `pass`, statut transaction non mis à jour, appelant non prévenu. |
| 9521 | Vérification achat Google Play (IAP) → exception renvoyée telle quelle en 500 (fuite message technique Google API). |
| 9614 | Vérification interne Google Play → toute exception transformée en "achat invalide" — **peut refuser à tort un achat légitime** sans distinguer erreur technique vs fraude. |
| 9787 | Chargement dashboard générique par rôle → 500 avec `str(e)` (fuite d'info). |
| 9825 | `RegisterView` : erreur après `serializer.save()` → 500 avec `str(e)`. |
| 9928 | Email OTP mot de passe oublié échoue → loggé ; **en mode DEBUG le code OTP est renvoyé en clair dans la réponse HTTP** (acceptable en dev, risqué si DEBUG traîne en prod). |
| 10189 | Email confirmation reset mot de passe → `pass`, aucun log, reset validé quand même. |
| 10266 | `except:` nu — `LogoutView` : échec suppression token → `pass`, déconnexion "réussie" renvoyée même si le token reste valide côté serveur. |

**Synthèse** : pattern dominant (~12 occurrences) = « échec email → log et
continue » (acceptable). Plus préoccupant : 3 occurrences avalent des
erreurs de suppression/invalidation de **token** (L3561, 3669, 10266) — un
logout ou changement de mot de passe peut se déclarer "réussi" avec
l'ancien token toujours valide. Et 2 occurrences (L1223, 9787) masquent une
vraie erreur serveur derrière un 200 avec données par défaut factices.

---

## 4. Endpoints de liste sans `select_related`/`prefetch_related` (risque N+1)

55 usages de `select_related`/`prefetch_related` confirmés pour 27
endroits `many=True` au total. **13 des 27 n'ont aucune optimisation**,
dont ceux à risque confirmé (le serializer traverse réellement une FK) :

| Vue | L. | Route | Risque |
|---|---|---|---|
| `liste_cours` | 2297 | **introuvable dans urls.py** (code mort/orphelin probable) | 3 FK imbriquées si jamais exposée |
| `ListeExercicesCoursView` | 2748 | `cours/<id>/exercices/` | FK `module.titre`/`lecon.titre` par ligne |
| `ExercicesParModuleView` | 3042 | `modules/<id>/exercices/` | idem |
| `HistoriqueEvaluationsView` | 3323 | `evaluations/historique/` | FK `exercice.titre`/`exercice.etoiles` par ligne |
| `ListeDevoirsView` | 3696 | `devoirs/` (**liste la plus consultée de l'app**) | 3 requêtes `.filter().first()` PAR DEVOIR dans le serializer (statut/note/nb_sorties apprenant) — N+1 « méthode », priorité haute |
| `ListeOlympiadesView` | 5121 | `olympiades/` | FK `devoir.id` + `InscriptionOlympiade` interrogée par ligne |
| `liste_enseignants_cadres` | 6803 | `enseignants_cadres/` | pas de `select_related('user')`, serializer imbrique `UserSerializer()` |
| `liste_enseignants_secondaires` | 6813 | `enseignants_secondaires/` | idem |
| `liste_enseignants` | 6821 | `enseignants/` | idem |
| `liste_enseignants_principaux` | 10235 | `enseignants_principaux/` | idem |
| `HistoriqueActiviteView` | 8574 | `historique/` | pas de `select_related('user')` |
| `get_dashboard_data` | 9745 | `enseignant/dashboard/` (**dashboard consulté à chaque connexion**) | **cas le plus sévère** : seule la branche `admin` a `select_related` ; les 4 autres branches (enseignant_admin/cadre/principal/enseignant) n'ont aucune optimisation malgré Parcours→Departement→Cours→enseignant_principal→user (+lecons) imbriqués sur plusieurs niveaux |

Risque faible (scalaire uniquement) : `NotificationsView`,
`AdminVersionListView`. Les 14 autres occurrences `many=True` sont déjà
optimisées.

---

## 5. Incohérences modèle/vue

### 5.1 — `Olympiade.prix_1er`/`prix_2eme`/`prix_3eme` (exemple connu, CONFIRMÉ)

Champs **commentés/supprimés du modèle** (`models.py` L1145-1148, avec
avertissement explicite `# ⚠️ SUPPRESSION DES CHAMPS PRIX_1ER, PRIX_2EME,
PRIX_3EME`). Aucune classe `AdminModifierOlympiadeView` n'existe : la vue
concernée est en réalité **`CadreModifierOlympiadeView`**
(`views.py` L6627-6751, `PATCH olympiades/<id>/modifier/`).

Conséquences concrètes, actives dès aujourd'hui :
- **`CadreModifierOlympiadeView`** (écriture, L6707-6712 + `setattr` L6733) :
  le `setattr` sur un attribut qui n'est plus un champ modèle **ne lève pas
  d'erreur mais ne persiste rien** — perte silencieuse de données ; le
  cadre reçoit un 200 "Olympiade modifiée avec succès" incluant
  `prix_1er` dans la liste des modifications, alors que rien n'est
  sauvegardé en base.
- **`CadreOlympiadesView`** (lecture, `GET olympiades/cadre/mes-olympiades/`,
  L8261-8263, `o.prix_1er` etc.) : lire un attribut absent du modèle
  **lève une `AttributeError`** non rattrapée → **500 systématique** dès
  qu'il y a au moins une olympiade à lister sur cet endpoint.

`CreerOlympiadeParCadreView` (création, L6410+) n'utilise pas ces champs
(utilise `recompense`, cohérent avec le modèle actuel) — la désynchro est
localisée aux vues de **modification/listing** côté cadre uniquement.

Anomalie annexe dans `CadreOlympiadesView` (L8273) :
`"created_at": o.cree_par.isoformat() if hasattr(o, 'cree_par') else None`
— `cree_par` n'existe très probablement pas sur `Olympiade` (le champ
auteur standard observé partout ailleurs est `organisateur`) ; le `hasattr`
masque une absence permanente, `created_at` renvoyé au front est donc
toujours `None`.

### 5.2 — `DepartementUpdateView.partial_update` — comparaison de rôle sur le mauvais modèle

`views.py` L8465-8473 :
```python
cadre = get_object_or_404(User, pk=cadre_id)
if getattr(cadre, "user_type", None) != "enseignant_cadre":
    return Response({"detail": "L'utilisateur choisi n'est pas un enseignant_cadre."}, status=400)
dep.cadre = cadre
```
`Departement.cadre` est une `ForeignKey(Profile, ...)`, **pas vers
`User`** — `User` n'a pas d'attribut `user_type` (c'est un attribut de
`Profile`). `getattr(cadre, "user_type", None)` renvoie donc toujours
`None`, la condition est **toujours vraie** → cet endpoint **refuse
systématiquement** tout changement de cadre, même avec un `cadre_id`
valide. Fonctionnalité vraisemblablement cassée en l'état, indépendamment
de toute question de refonte.

### 5.3 — Autres doutes relevés (non confirmés, à vérifier séparément)

- `type_correction` (`views.py` L1177) :
  `getattr(devoir, 'type_correction', 'auto')  # NOTE: Vérifiez le nom du champ`
  — commentaire du développeur lui-même signalant un doute sur le nom du
  champ côté modèle `Devoir`.
- `SortirDevoirView` (orpheline, §2.2) référence `soum.sorties`/
  `devoir.tentatives_max` — a priori cohérent avec le modèle, mais comme la
  vue n'est plus routée, impossible de confirmer qu'elle reste synchronisée
  avec l'évolution récente de `Devoir`.

---

## 6. Valeurs métier codées en dur à extraire vers un futur `ParametreSysteme`

**`ParametreSysteme` n'existe pas dans le projet** (grep exhaustif négatif
sur `ParametreSysteme`/`SystemConfig`/`Configuration`/`Parametre`, confirmé
indépendamment par deux passages d'audit). Il faudra le créer entièrement
si l'extraction est décidée — aucun modèle existant à réutiliser.

Valeurs identifiées :

- `views.py:40` — `YEKI_COMMISSION_RATE = 0.15` — **jamais réutilisée
  ailleurs dans le fichier** (grep : 1 seule occurrence, la déclaration).
  Soit code mort, soit logique de commission sur formations payantes **non
  implémentée** malgré la constante — à clarifier avec le produit.
- `views.py:41` — `PRIX_MINIMUM_OLYMPIADE = 100` — également jamais
  réutilisée directement (le `default=100` vient du modèle, pas de cette
  constante).
- Split 80/20 codé en dur à **trois endroits différents**, jamais
  mutualisé : `views.py:5302-5304` (participation apprenant), et surtout la
  tarification dégressive du prix global d'une olympiade
  (`views.py` L6417 et L8374-8378) :
  ```python
  if nb_apprenants <= 50:      prix_global = nb_apprenants * 100
  elif nb_apprenants <= 100:   prix_global = int(nb_apprenants * 100 * 0.8)
  elif nb_apprenants <= 200:   prix_global = int(nb_apprenants * 100 * 0.6)
  else:                        prix_global = int(nb_apprenants * 100 * 0.5)
  ```
  Seuils (50/100/200), taux (0.8/0.6/0.5) et tarif de base (100 FCFA) tous
  en dur, dans une vue (`LierDevoirOlympiadeView`), sans configuration.
- `views.py:998` — `"tarif": 5000` (`RepetiteursSearchView`) — valeur
  unique en dur pour **tous** les enseignants renvoyés, indépendamment du
  niveau/matière/enseignant réel.
- `views.py:980-981` — indicatif `+237` (Cameroun) codé en dur pour
  formater les numéros WhatsApp — problème si l'app vise plusieurs pays
  (CinetPay est déjà multi-pays).
- `views.py:9435-9437` — `TARIF_IA_FCFA_PAR_1K_TOKENS=2`,
  `COMMISSION_YEKI_IA_FCFA=5`, `TARIF_IA_MIN=10`.
- `models.py:1763-1765` — quasi-doublon des constantes IA ci-dessus mais
  formulé différemment (`TARIF_IA_PAR_TOKEN=0.002`/token — mathématiquement
  équivalent à 2 FCFA/1000 tokens, mais **dupliqué dans 2 fichiers
  séparés**, aucune source unique).
- `views.py:9482-9489` — `GOOGLE_PLAY_SKUS`, table SKU→FCFA (1000 à 20000,
  plus abonnements 1500/13000) codée en dur dans la vue.
- `views.py:9140` et `9626` — `'Montant minimum: 500 FCFA'` dupliqué à 2
  endroits pour le rechargement wallet.
- `views.py:4492-4493` — repli en dur `if 'tentatives_max' not in data:
  data['tentatives_max'] = 1` à la création d'un devoir — à vérifier contre
  la valeur par défaut du modèle (`Devoir.tentatives_max` default=1,
  cohérent, mais dupliqué).
- `models.py:675` (`Exercice.tentatives_max` default=1) et `models.py:898`
  (`Devoir.tentatives_max` default=1) — même valeur dupliquée sur 2 modèles.
- `models.py:2175` — `Repetiteur.tarif_mensuel` default=7500 FCFA en dur.
- `models.py:1623-1624` — montants FCFA écrits en dur dans les libellés de
  `choices` (`'Mensuel – 1 500 FCFA'`, `'Annuel – 13 000 FCFA'`).
- `models.py:1090-1093` — `Olympiade.prix_participation` default=100,
  split 80/20 documenté en commentaire (`help_text`) seulement, jamais en
  code structuré.
- `views.py:9506` — `package_name = 'com.yeki.app'` en dur (acceptable,
  identifiant d'app stable, mais à surveiller si multi-app/multi-flavor un jour).

---

## 7. Champ référençant une valeur inexistante (contrainte morte confirmée)

`Repetiteur.enseignant.limit_choices_to` (`models.py` L2168) :
```python
limit_choices_to={'user_type__in': ['enseignant', 'enseignant_secondaire']},
```
`'enseignant_secondaire'` **n'existe dans aucune des 6 valeurs** de
`Profile.USER_TYPES` (`admin`, `enseignant_admin`, `enseignant_cadre`,
`enseignant_principal`, `enseignant`, `apprenant`). Contrainte
**partiellement morte** : la branche `'enseignant'` fonctionne, la branche
`'enseignant_secondaire'` ne matchera jamais aucun profil réel. Le
frontend a un écran `secondaire_dashboard_page.dart` suggérant qu'un rôle
« enseignant secondaire » était prévu mais n'a jamais été ajouté à
`USER_TYPES` côté backend — incohérence de nommage probable avec
`'enseignant'` tout court.

**Corrigé en P2.1** (2026-07-18) : clarification actée — « enseignant
secondaire » = le grade de base `'enseignant'`. `limit_choices_to` devient
`{'user_type': 'enseignant', 'is_repetiteur': True}` (nouveau champ
`Profile.is_repetiteur`, validé par le Service Client). `Repetiteur.lien_whatsapp`
réécrit pour pointer vers le numéro WhatsApp du Service Client
(`ParametreSysteme.get('whatsapp_service_client')`, nouveau modèle
clé/valeur créé en P2.1, CDC §7.2) au lieu du téléphone de l'enseignant, et
inclut désormais nom + grade + lien de profil + tarif.

**Non corrigé, signalé** : `RepetiteursSearchView` (la vue réellement
exposée par l'API) n'utilise toujours pas le modèle `Repetiteur` — elle
continue de construire son propre lien WhatsApp et son tarif `5000` en dur
à partir de `Profile`/`Cours` directement (voir §6 ci-dessus), indépendamment
de `Repetiteur.lien_whatsapp`/`tarif_mensuel`. Le filtre `is_repetiteur=True`
a été ajouté à cette vue (P2.1) pour au moins exiger la validation Service
Client, mais tant que la vue n'est pas reliée au modèle `Repetiteur`
(aucune fiche `Repetiteur` n'est d'ailleurs jamais créée nulle part dans le
code), la correction de `lien_whatsapp` reste sans effet visible sur l'API
réelle. Câblage de la vue au modèle (ou inverse) hors périmètre de P2.1.

---

## 8. `Profile.user_type` default='Apprenant' — état et comptage

Confirmé : `USER_TYPES` (`models.py` L17-24) ne contient que des valeurs
**minuscules**, mais `default='Apprenant'` (majuscule, L25) est absent des
choix valides.

Recherche exhaustive dans tout `yeki/` : **100% du code filtre sur la
valeur minuscule `'apprenant'`** — `views.py` (~25 occurrences),
`serializers.py:95`, `permissions.py:48`. **Aucune occurrence de
`'Apprenant'` (majuscule) nulle part** → pas de bug compensatoire.

C'est un bug **dormant, pas encore actif en usage normal** : le seul point
de création de `Profile` actif aujourd'hui
(`RegisterSerializer.create`, `serializers.py:85`) **impose** `user_type`
via `validate_user_type` (L66-71, liste minuscule obligatoire) — donc
l'inscription normale ne peut pas produire l'état invalide. Risque réel :
tout `Profile` créé **hors de ce serializer** (Django admin —
`admin.py:8`, `admin.site.register(Profile)` basique sans formulaire
personnalisé — ou script/shell/migration de données) hériterait
silencieusement de `'Apprenant'` et **n'apparaîtrait dans aucun filtre par
rôle** (ni compteurs stats, ni permissions `IsApprenant`, ni classement).
Un signal `post_save` auto-créateur de `Profile` existe mais est
**commenté/mort** dans `signals.py` L6-9 — s'il était réactivé sans
`user_type` explicite, il déclencherait ce bug à **chaque** inscription.

**Comptage réel en base — nécessite un accès Django shell, non exécuté
dans cet audit** (tâche « ne rien modifier », et une requête shell n'est
pas nécessaire pour documenter le bug) :
```python
python manage.py shell
>>> from yeki.models import Profile
>>> Profile.objects.filter(user_type='Apprenant').count()   # profils affectés par le bug
>>> Profile.objects.filter(user_type='apprenant').count()   # profils correctement filtrables
```

**Corrigé en P2.1** (2026-07-17) : `default='apprenant'` (minuscule),
`db_index=True` ajouté, migration de données (`RunPython`, loggée) pour
normaliser tout `user_type` NULL/`'Apprenant'` existant. 0 ligne affectée
en base de développement (table vide à ce moment).

---

## 9. Corrections de modèles bloquantes — P2.2 (2026-07-18)

- **`Choix.est_correct` ajouté** (`apps/evaluation/models.py`) : la bonne
  réponse d'un QCM était un texte (`Question.bonne_reponse`) comparé au
  libellé du choix — deux points de comparaison **incohérents entre eux**
  (`.strip().lower()` en correction, sensible à la casse en validation de
  création), confirmé comme cause probable du bug « les questions QCM ne
  s'affichent pas » (la création échouait en 400 sur un simple écart de
  casse/espace, la question n'était jamais enregistrée). Migration de
  données : backfill `est_correct` par correspondance normalisée
  (casse/accents/espaces) entre `bonne_reponse` et les choix ; les
  questions à 0 ou plusieurs correspondances sont journalisées
  (`logger.warning`) et laissées inchangées — **0 question qcm en base de
  développement** au moment de la migration (table vide), donc aucune
  exception à signaler ici ; à revérifier sur tout environnement peuplé
  via la requête de contrôle documentée dans le ticket P2.2.
  **Recâblage complet** (validé avec l'utilisateur, au-delà du périmètre
  littéral du ticket) : création (`ChoixCreateSerializer`/
  `QuestionCreateSerializer`) et correction (`exercices.py`, 2 sites)
  utilisent désormais `Choix.est_correct` comme source de vérité.
  `bonne_reponse` conservée, devient un mirroir dérivé auto-rempli pour les
  QCM (compatibilité descendante d'affichage), toujours obligatoire pour
  les questions de type texte. **Impact contrat API** : le frontend doit
  désormais envoyer `est_correct` par choix à la création d'un QCM.
- **`ChoixReponse.ordre` ajouté**, `Meta.ordering=['ordre']` — les choix de
  devoir revenaient dans un ordre non déterministe (cause probable du bug
  « ajout consécutif de questions avec plus de 2 choix »). Migration :
  numérotation des existants par id, par question.
- **Validation de pas 0.25 sur les points** (`Question.points`,
  `QuestionDevoir.points`) : nouveau `apps/evaluation/validators.py`
  (`valider_pas_de_0_25`), attaché comme validateur de champ modèle
  (repris automatiquement par les serializers DRF). `QuestionDevoir`
  n'avait auparavant aucune validation de points (écart de parité avec
  `Question`) — corrigé au passage.
- **`Exercice.exercices_composes` existait déjà** (M2M self, non documenté
  comme tel dans ce ticket avant l'implémentation — vérifié en amont,
  pas ajouté en double). Le vrai travail : validation anti-cycle ajoutée
  (`valider_pas_de_cycle_epreuve`, auto-référence + transitivité), et
  correction d'un bug confirmé — `ExerciceCreateSerializer.validate()`
  sautait silencieusement la vérification « au moins un exercice » sur un
  PATCH partiel ne renvoyant pas `est_epreuve` (cause du bug « la
  modification d'une épreuve ne fonctionne pas »). Vérification
  d'existence par ID morte (déjà résolue par `PrimaryKeyRelatedField`)
  supprimée au passage.

## 10. EnonceDevoir et ClassementHistorique — P2.3 (2026-07-18)

- **Collision de nom découverte et validée avec l'utilisateur** : le CDC
  donne littéralement `enonce = FK(EnonceDevoir, ...)` sur `QuestionDevoir`,
  mais `QuestionDevoir.enonce` existait déjà (`TextField`, texte propre de
  la question, requis, exposé dans 4 serializers + `__str__` + duplication
  de devoir). Le nouveau FK s'appelle `enonce_devoir` — le `TextField`
  existant n'a pas été touché, zéro impact sur l'existant.
- **`EnonceDevoir` créé** (`devoir`, `contenu`, `ordre`,
  `unique_together=('devoir','ordre')`) : un devoir peut désormais avoir
  plusieurs énoncés, chacun avec ses propres questions (CDC §7.2.1 — « un
  énoncé a plusieurs questions, ces questions »). Migration de données
  sans perte : `Devoir.enonce` → `EnonceDevoir(ordre=1)`, toutes les
  `QuestionDevoir` existantes rattachées à cet énoncé 1, chaque string de
  `enonces_supplementaires` éclatée en `EnonceDevoir` d'ordre 2, 3…
  (0 devoir en base de développement au moment de la migration — table
  vide, no-op confirmé ; la logique elle-même vérifiée par un test dédié
  qui la rejoue directement contre des données simulées). `Devoir.enonce`
  et `enonces_supplementaires` conservés (`@deprecated`, pas supprimés).
  **Recâblage minimal validé avec l'utilisateur** (au-delà du périmètre
  littéral du ticket, sinon la règle de verrouillage n'aurait rien à
  verrouiller) : nouvelle vue `AjouterEnonceDevoirView` (409 Conflict si
  devoir publié, conforme au CDC §7.2.2), et `DevoirCreateSerializer.create()`
  alimente automatiquement `EnonceDevoir(ordre=1)` — contrat de création
  du devoir inchangé pour le frontend.
- **`ClassementHistorique` créé** (`departement`, `apprenant`,
  `periode_debut`, `periode_fin`, `rang`, `points`, `detail` JSON,
  `unique_together`, index `(departement, periode_debut, rang)`).
  `Departement.reinitialiser_periode()` **prétendait** archiver le
  classement mais ne faisait qu'écraser les dates — le classement de la
  période précédente (`RangApprenant`/`ScoreDetail`) était purement et
  simplement perdu. **Aucun appelant nulle part dans le repo** (confirmé) :
  aucune régression de comportement visible, uniquement l'ajout de
  l'archivage manquant, dans une transaction atomique.
- **`Departement.periode` obligatoire à la création** (CDC : « obligatoire
  lors de la création ») : `default=6` conservé côté modèle. Découverte en
  cours de tâche — `DepartementCreateSerializer` n'est câblé à **aucune**
  vue réelle (`CreerDepartementView` construit le département à la main
  via `request.data.get(...)`, comme plusieurs autres vues de création déjà
  documentées dans cet audit) ; la validation ajoutée au serializer aurait
  donc été sans effet. Corrigé dans le vrai chemin de création
  (`CreerDepartementView.post`), en plus du serializer (documente
  l'intention si celui-ci devient un jour utilisé).
- **Hors périmètre, non traité ici** : le CDC (§7.1.5) documente un système
  de score par paliers d'étoiles d'exercice (`ParametreClassement`, poids
  `Devoir:20`/`Olympiade:15`/etc.) différent des catégories `ScoreDetail`
  actuelles (`devoirs/notes_devoirs/exercices/lecons/forum/regularite`) —
  écart CDC/code déjà connu (RankingService cassé, documenté P1.6/P2.1),
  `ClassementHistorique.detail` reflète fidèlement les catégories réelles
  actuelles, pas le système cible non implémenté.

---

## 11. Paramétrage et paiement — P2.4 (2026-07-18)

- **`ParametreSysteme` étendu** (`apps/core/models.py`) : `type`
  (`string`/`int`/`float`/`bool`, purement descriptif — le contrat de
  retour de `.get()` reste une string, pour ne rien casser chez les
  appelants existants comme `Repetiteur.lien_whatsapp`) et
  `modifiable_par` (informatif, aucun contrôle d'accès appliqué dans cette
  tâche, non spécifié par le CDC). **Cache mémoire ajouté**
  (`django.core.cache`, `LocMemCache`, première utilisation du framework de
  cache dans le projet — `CACHES` rendu explicite dans
  `config/settings/base.py`) : `.get()` lit le cache en premier, retombe
  sur la DB, remplit le cache sans expiration ; `post_save`/`post_delete`
  (`apps/core/signals.py`) invalident la clé à chaque écriture/suppression
  — « cache invalidé à l'écriture » au sens strict du ticket, pas un TTL.
  15 nouvelles clés semées par migration de données (`get_or_create`, les
  2 clés P2.1 `whatsapp_service_client`/`url_base_frontend` non
  re-semées) : `ussd_orange_money`, `ussd_mtn_momo`,
  `numero_depot_orange`, `numero_depot_mtn`, `nom_affiche_depot`,
  `delai_validation_paiement_minutes=60`, `mode_paiement='manuel'`,
  `usd_to_xaf=600`, `modele_ia='claude-3-5-haiku-20241022'`,
  `commission_ia_pourcent=20`, `solde_min_ia=20`,
  `tarif_repetiteur_mensuel=7500`, `retrait_minimum=1000`,
  `part_yeki_olympiade=80`, `part_yeki_formation=30`.
- **Toutes les valeurs listées par le ticket recâblées**, plus aucune en
  dur dans le code : `apps/ia/services.py`/`views.py` (`modele_ia()`,
  `usd_to_xaf()`, `commission_ia_pourcent()`, `solde_min_ia()` — lectures
  à l'appel, jamais des constantes figées à l'import, condition nécessaire
  pour une édition sans redéploiement) ; `apps/evaluation/views/olympiades.py`
  (split 80/20 de `PayerParticipationOlympiadeView`, §6 de cet audit
  résolu pour ce site d'appel précis — les deux autres occurrences du
  split 80/20 documentées §6, tarification dégressive du prix global d'une
  olympiade, restent en dur, **hors périmètre littéral de ce ticket, non
  traitées ici**) ; `Repetiteur.tarif_mensuel` (§6 de cet audit, `default=7500`
  devient un `default` callable lisant `ParametreSysteme`).
  **Décision produit validée avec l'utilisateur** : `COMMISSION_YEKI_IA`
  était un montant fixe (5 FCFA), pas un pourcentage — le CDC demande
  `commission_ia_pourcent=20`, donc la formule de facturation IA a
  réellement changé (pourcentage du coût, pas un ajout forfaitaire), pas
  un simple renommage de constante.
  **Non traité, signalé** : `INPUT_TOKEN_PRICE_USD`/`OUTPUT_TOKEN_PRICE_USD`
  (tarification Claude par token, `apps/ia/services.py`) restent en dur —
  absents de la liste de valeurs du ticket, aucune valeur donnée à semer.
- **`FraisOperateur` créé** (`apps/paiement/models.py`) — grille de frais
  par tranche de montant, paramétrable en base (`calculer_frais()`),
  aucune ligne semée (grille vide par défaut, à configurer par l'admin,
  aucune valeur donnée par le ticket ; `calculer_frais()` dégrade
  proprement à frais=0 si aucune tranche ne correspond, pas d'erreur).
- **`DemandePaiementManuelle` créé** (CDC §9.1) avec
  `UniqueConstraint(['operateur','id_transaction'])` — sans elle, la même
  transaction opérateur pouvait être soumise deux fois (double
  crédit potentiel). Câblage minimal validé avec l'utilisateur (même choix
  qu'en P2.1/P2.3) : `SoumettrePaiementManuelView` (création uniquement,
  409 `CONFLICT` via l'exception déjà unifiée du projet sur violation de
  la contrainte). Pas de vue de validation/refus Service Client — hors
  périmètre, à traiter dans une tâche dédiée.
- **`DemandeRetrait` créé** (CDC §5.6). Câblage minimal :
  `DemanderRetraitView` vérifie montant ≥ `retrait_minimum` et solde
  suffisant, calcule les frais via `calculer_frais()`, puis **débite
  immédiatement le wallet** (gel du solde, conforme au CDC) et crée la
  demande à `en_attente`. **Assumé et documenté, pas un oubli** : aucune
  vue n'existe encore pour qu'un Service Client valide/refuse et
  libère/finalise ce gel — une demande créée aujourd'hui reste gelée
  jusqu'à une tâche ultérieure dédiée à cette décision.
- **`HistoriquePrixDepartement` créé** (`apps/formation/models.py`),
  alimenté par un signal `pre_save`/`post_save` sur `Departement`
  (`apps/formation/signals.py`, même pattern que la cascade
  `is_repetiteur` de P2.1) — portée volontairement limitée aux champs
  `prix`/`prix_presentiel` (seule motivation donnée par le CDC : rendre la
  règle « prix inférieur → promotion » calculable), pas un audit générique
  de tout changement de champ sur `Departement`. `par_qui` non renseigné
  automatiquement (un signal `post_save` n'a pas accès à l'utilisateur
  HTTP courant) — laissé `null`, à renseigner par les vues d'écriture dans
  une tâche ultérieure si souhaité.
- **`DeviceToken` créé** (`apps/notifications/models.py`, CDC §8.2) : 5
  champs exacts (`user`, `token` unique, `plateforme`, `actif`,
  `derniere_utilisation`). Pas de vue d'enregistrement/désenregistrement
  dans cette tâche — l'intégration FCM réelle (envoi de push) est un
  chantier bien plus large que la création du modèle, hors périmètre
  explicite du ticket.
- **Découverte hors périmètre, signalée mais non traitée** : trois
  constantes mortes déjà présentes dans `apps/paiement/models.py` avant
  cette tâche (`TARIF_IA_PAR_TOKEN`, `COMMISSION_YEKI_IA` — un second
  homonyme distinct de celui d'`apps/ia/services.py`, tarification GPT-3.5
  d'une génération de code antérieure — et `TARIF_IA_MIN_PAR_REQUETE`),
  confirmées totalement inutilisées (grep). Laissées en place (« déplacer,
  ne pas réécrire », scope discipliné) — candidates à suppression pure
  lors d'une passe de nettoyage dédiée.
- **Vérification** : 22 nouveaux tests pytest (cache/invalidation,
  commission IA en %, split olympiade paramétrable, contrainte unique
  paiement manuel, retrait — minimum/solde/gel immédiat, historique de
  prix — portée limitée confirmée, unicité `DeviceToken`), suite complète
  86/86 verte, `ruff check .`/`black --check .` verts,
  `makemigrations --check --dry-run` → aucune migration manquante.

---

## 12. Nettoyage des olympiades — P2.5 (2026-07-18)

**Résout §5.1 ci-dessus** (les deux bugs `AttributeError`/perte silencieuse
décrits en §5.1 sont corrigés dans cette tâche — cette section constate la
résolution, elle ne re-décrit pas le diagnostic).

### 12.1 — Code mort corrigé

`matiere`, `niveau`, `prix_1er`, `prix_2eme`, `prix_3eme` avaient déjà été
retirés du modèle `Olympiade` (Python commenté, `apps/evaluation/models.py`)
lors d'un nettoyage antérieur resté inachevé : plusieurs vues continuaient
à lire/écrire ces attributs. Corrigé :
- `ListeOlympiadesView` : filtres `matiere`/`niveau` (query params +
  `OpenApiParameter`) retirés — levaient `FieldError` si utilisés.
- `CadreModifierOlympiadeView` : les 5 blocs `if "matiere"/"niveau"
  /"prix_1er"/"prix_2eme"/"prix_3eme" in data` retirés — le `setattr`
  correspondant réussissait silencieusement sans jamais persister (perte
  de données silencieuse, confirmation 200 trompeuse).
- `CadreOlympiadesView.get()` : les 5 clés mortes retirées du dict de
  réponse — leur lecture directe (`o.matiere` etc.) levait une
  `AttributeError` non rattrapée → 500 systématique dès qu'une olympiade
  existait pour le cadre connecté.

### 12.2 — Suppression de la validation admin (décision produit confirmée)

**Confirmé explicitement avec l'utilisateur avant suppression** (règle
« s'arrêter et demander » du protocole d'arbitrage) : la consigne écrite la
plus récente indique qu'il n'est plus question de validation d'une
olympiade par l'enseignant admin (publication immédiate dès la création
par le cadre, cf. docstring de `CreerOlympiadeParCadreView`). Les 3 routes
admin, les vues correspondantes, le bloc dupliqué du dashboard admin
général et l'onglet Flutter associé sont donc supprimés, **après
archivage complet ci-dessous (rien perdu)**.

Bug indépendant découvert en cours de suppression (n'a donc plus besoin
d'être corrigé, mais documenté pour l'historique) : la route
`admin/olympiades/<int:pk>/refuser/` déclare le kwarg `pk`, mais
`AdminRefuserOlympiadeView.post(self, request, olympiade_id)` attendait
`olympiade_id` → `TypeError` systématique. **Cette route n'a probablement
jamais fonctionné en production.**

Doublon fonctionnel également supprimé : `apps/accounts/views/dashboards.py`
recalculait la même liste « olympiades en attente/refusées » qu'
`AdminOlympiadesAValiderView`, depuis un second endroit (le dashboard admin
général), avec le même bug `o.matiere`/`o.niveau`.

### 12.3 — Code archivé avant suppression (rien perdu — rule 5)

**`apps/evaluation/views/olympiades.py`** — les 3 classes supprimées dans
leur intégralité (dernières lignes du fichier avant suppression) :

```python
class AdminOlympiadesAValiderView(PaginatedListMixin, APIView):
    """
    GET /api/admin/olympiades/a-valider/
    Retourne les olympiades du parcours de l'admin qui attendent validation
    ou qui ont été refusées.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Olympiades à valider (admin)",
        description="Liste paginée des olympiades en attente de validation ou refusées, pour le parcours de l'admin connecté.",
        tags=["evaluation"],
        parameters=[*PARAMS_PAGINATION],
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_PAGINATION, *ERREURS_COURANTES],
    )
    def get(self, request):
        profile = _get_profile(request.user)
        if not profile or profile.user_type != "enseignant_admin":
            return Response({"detail": "Accès refusé."}, status=403)

        try:
            parcours = Parcours.objects.get(admin=profile)
        except Parcours.DoesNotExist:
            return Response({"detail": "Aucun parcours assigné."}, status=404)

        # Olympiades en attente de validation (prix_global = 0, non validées, non refusées)
        olympiades_attente = (
            Olympiade.objects.filter(
                organisateur__departements_cadre__parcours=parcours,
                prix_global=0,
                est_validee=False,
                est_refusee=False,
            )
            .distinct()
            .select_related("organisateur__user", "devoir")
        )

        # Olympiades refusées (l'admin peut encore les voir pour accepter)
        olympiades_refusees = (
            Olympiade.objects.filter(
                organisateur__departements_cadre__parcours=parcours,
                prix_global=0,
                est_refusee=True,
            )
            .distinct()
            .select_related("organisateur__user", "devoir")
        )

        result = []
        for o in olympiades_attente:
            result.append(
                {
                    "id": o.id,
                    "titre": o.titre,
                    "matiere": o.matiere,
                    "niveau": o.niveau,
                    "edition": o.edition,
                    "statut_validation": "attente",
                    "cadre": {
                        "id": o.organisateur.id,
                        "nom": _nom_profil(o.organisateur),
                    },
                    "date_creation": o.created_at,
                    "prix_global": getattr(o, "prix_global", 0),
                    "niveaux_accessibles": o.get_niveaux_accessibles_list(),
                }
            )

        for o in olympiades_refusees:
            result.append(
                {
                    "id": o.id,
                    "titre": o.titre,
                    "matiere": o.matiere,
                    "niveau": o.niveau,
                    "edition": o.edition,
                    "statut_validation": "refuse",
                    "motif_refus": getattr(o, "motif_refus", ""),
                    "cadre": {
                        "id": o.organisateur.id,
                        "nom": _nom_profil(o.organisateur),
                    },
                    "date_creation": o.created_at,
                    "prix_global": getattr(o, "prix_global", 0),
                    "niveaux_accessibles": o.get_niveaux_accessibles_list(),
                }
            )

        page = self.paginate_queryset(result)
        return self.get_paginated_response(page)


class AdminValiderOlympiadeView(APIView):
    """
    POST /api/admin/olympiades/<pk>/valider/
    Body optionnel : { "refuser": true, "motif": "..." }

    Valide (publie) ou refuse une olympiade du parcours de l'admin.
    Valider = mettre Devoir.est_publie = True
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Valider ou refuser une olympiade (admin)",
        description="Publie le devoir lié (validation) ou marque l'olympiade comme refusée, pour le parcours de l'admin connecté.",
        tags=["evaluation"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    )
    @transaction.atomic
    def post(self, request, pk):
        profile = _get_profile(request.user)
        if not profile or profile.user_type != "enseignant_admin":
            return Response({"detail": "Accès refusé."}, status=403)

        try:
            parcours = Parcours.objects.get(admin=profile)
        except Parcours.DoesNotExist:
            return Response({"detail": "Aucun parcours assigné."}, status=404)

        olympiade = get_object_or_404(
            Olympiade,
            pk=pk,
            organisateur__departements_cadre__parcours=parcours,
        )

        refuser = request.data.get("refuser", False)

        if refuser:
            motif = request.data.get("motif", "Refusée par l'administrateur.")
            olympiade.est_refusee = True
            olympiade.est_validee = False
            olympiade.motif_refus = motif
            olympiade.save()

            enregistrer_activite(
                user=request.user,
                action="olympiad_rejected",
                description=f"Olympiade « {olympiade.titre} » refusée. Motif : {motif}",
                objet_id=olympiade.id,
                objet_type="Olympiade",
            )
            return Response(
                {
                    "detail": f"Olympiade refusée. Motif : {motif}",
                    "id": olympiade.id,
                    "statut": "refuse",
                }
            )

        # Valider → publier le devoir lié
        if not olympiade.devoir:
            return Response(
                {"detail": "Cette olympiade n'a pas de devoir lié. Impossible de valider."},
                status=400,
            )

        olympiade.devoir.est_publie = True
        olympiade.devoir.save(update_fields=["est_publie"])
        olympiade.est_validee = True
        olympiade.est_refusee = False
        olympiade.save(update_fields=["est_validee", "est_refusee"])

        enregistrer_activite(
            user=request.user,
            action="olympiad_validated",
            description=f"Olympiade « {olympiade.titre} » validée et publiée.",
            objet_id=olympiade.id,
            objet_type="Olympiade",
        )

        return Response(
            {
                "detail": "Olympiade validée et publiée avec succès.",
                "id": olympiade.id,
                "titre": olympiade.titre,
                "statut": "validee",
            }
        )


class AdminRefuserOlympiadeView(APIView):
    """Refuser une olympiade (la garde visible mais marquée comme refusée)"""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Refuser une olympiade (admin)",
        description="Marque une olympiade du parcours de l'admin comme refusée (reste visible, motif enregistré).",
        tags=["evaluation"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    )
    @transaction.atomic
    def post(self, request, olympiade_id):
        profile = _get_profile(request.user)
        if not profile or profile.user_type != "enseignant_admin":
            return Response({"detail": "Accès refusé."}, status=403)

        try:
            parcours = Parcours.objects.get(admin=profile)
        except Parcours.DoesNotExist:
            return Response({"detail": "Aucun parcours assigné."}, status=404)

        olympiade = get_object_or_404(
            Olympiade,
            pk=olympiade_id,
            organisateur__departements_cadre__parcours=parcours,
        )

        motif = request.data.get("motif", "Refusée par l'administrateur.")

        olympiade.est_refusee = True
        olympiade.est_validee = False
        olympiade.motif_refus = motif
        olympiade.save()

        enregistrer_activite(
            user=request.user,
            action="olympiad_rejected",
            description=f"Olympiade « {olympiade.titre} » refusée. Motif : {motif}",
            objet_id=olympiade.id,
            objet_type="Olympiade",
        )

        return Response(
            {
                "detail": "Olympiade refusée.",
                "id": olympiade.id,
                "est_refusee": True,
            }
        )
```

**`apps/evaluation/urls.py`** — routes retirées :
```python
    # ── ADMIN : Validation olympiades ────────────────────────────
    path(
        "admin/olympiades/a-valider/",
        AdminOlympiadesAValiderView.as_view(),
        name="admin-olympiades-a-valider",
    ),
    path(
        "admin/olympiades/<int:pk>/valider/",
        AdminValiderOlympiadeView.as_view(),
        name="admin-valider-olympiade",
    ),
    path(
        "admin/olympiades/<int:pk>/refuser/",
        AdminRefuserOlympiadeView.as_view(),
        name="admin-refuser-olympiade",
    ),
```

**`apps/accounts/views/dashboards.py`** — bloc doublon retiré (dashboard
admin général, `AdminDashboardView` ou équivalent) :
```python
        # ── Olympiades en attente (prix_global = 0, non publiées) ────
        olympiades_en_attente = []

        olympiades_attente_qs = (
            Olympiade.objects.filter(
                organisateur__departements_cadre__parcours=parcours_qs,
                prix_global=0,
                devoir__est_publie=False,
            )
            .distinct()
            .select_related("organisateur__user", "devoir")
        )

        for o in olympiades_attente_qs:
            statut = "refuse" if o.est_refusee else "attente"

            olympiades_en_attente.append(
                {
                    "id": o.id,
                    "titre": o.titre,
                    "matiere": o.matiere,
                    "niveau": o.niveau,
                    "edition": o.edition,
                    "statut_validation": statut,
                    "motif_refus": o.motif_refus if o.est_refusee else "",
                    "cadre": (
                        {
                            "id": o.organisateur.id,
                            "nom": _nom_profil(o.organisateur),
                        }
                        if o.organisateur
                        else None
                    ),
                    "date_creation": o.created_at.isoformat() if hasattr(o, "created_at") else None,
                    "niveaux_accessibles": o.get_niveaux_accessibles_list(),
                    "prix_global": o.prix_global,
                    "est_validee": o.est_validee,
                    "est_refusee": o.est_refusee,
                }
            )
```
Plus les clés `stats["nb_olympiades_attente"]` et
`olympiades_en_attente` dans la réponse finale et le fallback
« pas de parcours assigné ».

Côté Flutter (non collé ici, disponible dans l'historique git) :
`enseignant_admin_dashboard_page.dart` — 3ᵉ onglet « Olympiades à valider »
de la `TabBar`, son `TabBarView`, et les méthodes
`_validerOlympiade`/`_refuserOlympiade`.

### 12.4 — Migrations (données puis colonnes), défensives et idempotentes

Aucune migration de ce dépôt n'avait jamais physiquement créé ces colonnes
sur `yeki_olympiade` (`yeki/migrations/0001_initial.py` les exclut déjà) —
la base de dev (SQLite) ne les a donc jamais eues. La production tourne
sur **PostgreSQL**, une base distincte dont l'historique réel a pu diverger
(squash de l'historique de migrations jamais rejoué contre la prod) —
**elle a probablement encore ces colonnes physiquement**. Les 2 nouvelles
migrations (`apps/evaluation/migrations/0004_*.py` puis `0005_*.py`) sont
donc écrites en SQL brut avec introspection portable
(`connection.introspection.get_table_description`), pour rester correctes
dans les deux cas sans supposer l'état réel de la prod (confirmé avec
l'utilisateur) :
1. **0004 (données)** : si les colonnes existent, concatène le contenu de
   `prix_1er`/`prix_2eme`/`prix_3eme` (format HTML, cohérent avec
   `recompense` « devient du HTML enrichi ») dans `recompense`, logge
   chaque ligne touchée + un résumé ; si absentes, no-op loggé.
2. **0005 (colonnes)** : `DROP COLUMN` pour chaque colonne encore
   présente ; no-op loggé sinon.

### 12.5 bis — Bugs supplémentaires trouvés et corrigés dans `CadreOlympiadesView`

Non signalés par le ticket (découverts en écrivant le test de régression
`test_cadre_olympiades_ne_plante_plus`, qui échouait encore après le
nettoyage des 5 champs abandonnés) :
- `.order_by("-created_at")` (L1081 avant correction) : `Olympiade` n'a
  **jamais** eu de champ `created_at` — `FieldError` immédiate à la
  construction du queryset, **100% des appels** à cet endpoint
  échouaient en 500, indépendamment de matiere/niveau/prix_1er et même
  s'il n'y avait aucune olympiade. Corrigé en `.order_by("-id")`
  (proxy raisonnable de l'ordre de création, sans ajouter de nouveau
  champ hors périmètre).
- `"created_at": o.cree_par.isoformat() if hasattr(o, "cree_par") else None`
  (L1113 avant correction) : `cree_par` est bien un champ réel
  (`ForeignKey(User)`, contrairement à ce que supposait §5.1 ci-dessus) —
  `hasattr` est donc toujours vrai, et `.isoformat()` est appelée soit sur
  `None` soit sur un `User`, qui n'ont ni l'un ni l'autre de méthode
  `.isoformat()` → `AttributeError` systématique dès que cette clé était
  évaluée. La clé n'est lue nulle part côté Flutter (vérifié) — retirée
  purement et simplement plutôt que d'inventer un vrai champ de date hors
  périmètre.

### 12.5 — Vérification
- 5 nouveaux tests (`apps/evaluation/tests/test_nettoyage_olympiades.py`) :
  `CadreOlympiadesView` ne plante plus (régression directe sur les deux
  bugs ci-dessus) ; `CadreModifierOlympiadeView` ignore silencieusement
  matiere/niveau/prix_1er/2eme/3eme sans erreur ; `ListeOlympiadesView`
  n'échoue plus avec les query params matiere/niveau ; les 3 routes admin
  supprimées lèvent bien `NoReverseMatch` ; le dashboard admin général ne
  plante plus et ne renvoie plus `olympiades_en_attente`/
  `nb_olympiades_attente`.
- Les deux migrations (`0004`/`0005`) ont été exercées dans **les deux
  branches** : sur la vraie base de dev (colonnes absentes → no-op loggé,
  confirmé) ET sur une copie jetable de la base avec les 5 colonnes
  réajoutées manuellement + données de test (branche « colonnes
  présentes » → fusion HTML dans `recompense` confirmée ligne par ligne,
  puis suppression effective des 5 colonnes confirmée par introspection
  après coup) — nécessaire car la base de dev seule ne peut pas exercer la
  branche qui compte le plus (celle attendue en production).
- Suite complète : **90 tests passés, 1 échec** —
  `apps/formation/tests/test_historique_prix.py::test_baisse_de_prix_est_bien_le_referent_de_la_promotion`.
  **Confirmé sans rapport avec P2.5** (aucun fichier de `apps/formation`
  touché ici) : échec déterministe (reproduit 3/3, pas un flake), cause
  identifiée — `HistoriquePrixDepartement.date` (`auto_now_add`) reçoit la
  même valeur pour les deux `Departement.save()` du test (résolution
  d'horloge Windows), donc `.latest("date")` ne peut pas départager les
  deux lignes de façon fiable. Bug pré-existant de la tâche P2.4, non
  corrigé ici (application différente, hors périmètre du nettoyage
  olympiades) — à corriger dans une tâche dédiée (ex : trier sur `-id` en
  plus de `-date`, même correctif que celui appliqué ci-dessus à
  `CadreOlympiadesView`).
- `ruff check .` / `black --check .` : verts (2 imports désormais morts
  retirés après suppression des 3 vues : `_nom_profil`, `Parcours`).
- `python manage.py makemigrations --check --dry-run` → aucune migration
  manquante (les 2 nouvelles migrations sont écrites à la main en SQL
  brut, pas auto-générées, puisqu'aucun champ de modèle Django ne change).
- `python manage.py check` → aucun problème.
- Frontend : `dart analyze` sur les 3 fichiers touchés → 0 erreur ; 1
  avertissement (`_sectionTitle` devenu orphelin après suppression de
  l'onglet) corrigé dans la foulée.
- Découverte hors périmètre, non traitée : `Devoir` a **le même schéma
  d'abandon** que `Olympiade` — `matiere`/`niveau` commentés dans le
  modèle (`apps/evaluation/models.py`, lignes ~22-23 de la classe
  `Devoir`) mais encore lus côté Flutter
  (`cadre_dashboard_page.dart:1548`, picker « lier un devoir existant »).
  Non traité ici : ticket explicitement scopé à `Olympiade`, application
  différente (`Devoir`), pas de preuve que ce site précis plante
  actuellement (à vérifier dans une tâche dédiée).

---

## Synthèse — priorités suggérées (à discuter, pas décidées par cet audit)

Ordre de sévérité suggéré si une correction est envisagée séparément :

1. **`CadreOlympiadesView` (§5.1)** — 500 systématique dès qu'une olympiade
   existe côté cadre. Bug actif, pas seulement latent.
2. **`DepartementUpdateView` (§5.2)** — fonctionnalité de changement de
   cadre cassée à 100% (compare `user_type` sur `User` au lieu de `Profile`).
3. **`CadreModifierOlympiadeView` (§5.1)** — perte silencieuse de données
   (prix) avec confirmation 200 trompeuse.
4. **`AdminGeneralChangerTypeEnseignantView` (§2.1)** — doublon avec
   comportement divergent, email de notification perdu silencieusement.
5. **Tokens non invalidés (§3, L3561/3669/10266)** — logout/reset de mot
   de passe qui se déclarent réussis sans garantir l'invalidation réelle.
6. **`get_dashboard_data` (§4)** — N+1 le plus sévère, sur l'endpoint le
   plus consulté (à chaque connexion).
7. Le reste (valeurs en dur, `Profile.user_type` dormant, contrainte
   `Repetiteur` morte) : dette technique réelle mais non bloquante à court
   terme.

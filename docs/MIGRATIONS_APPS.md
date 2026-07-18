# Déplacement des 46 modèles vers `apps/` — SeparateDatabaseAndState

Date : 2026-07-17. Résumé de la méthode utilisée pour faire migrer le code
des 46 modèles de `yeki/models.py` vers les 9 apps `apps/{core,accounts,
formation,evaluation,forum,paiement,ia,notifications,repetiteurs}`, **sans
aucun ALTER TABLE, sans aucune perte de données**. `yeki/models.py` est
désormais un pur fichier de ré-exports (`from apps.xxx.models import ...`),
gardé temporairement pour ne rien casser côté `views.py`/`serializers.py`/
`admin.py`/`signals.py` qui font tous `from .models import X` ou
`from yeki.models import X`.

## ⚠️ Découverte préalable — action manuelle requise en production

`yeki/migrations/` ne contenait **aucune migration** pour le schéma actuel
avant cette tâche (le seul `0001_initial.py` qu'ait connu ce dépôt créait un
vieux modèle `CustomUser` aujourd'hui disparu du code, supprimé du dépôt il
y a 325 commits/9 mois). La production a pourtant déjà les 46 tables
(confirmé par l'utilisateur — migrées manuellement côté serveur, jamais
resynchronisées dans le dépôt).

**Étape 0 réalisée dans cette tâche** : régénération de
`yeki/migrations/0001_initial.py` (46 `CreateModel` réels, correspondant
exactement au `models.py` actuel — aucun modèle n'a de `db_table`
personnalisé, donc Django utilise déjà la convention par défaut
`yeki_<nom_modele_minuscule>`, qui correspond à ce qui existe déjà en
production). Appliquée **pour de vrai en local uniquement** (la base
locale ne contenait que 3 tables résiduelles `yeki_customuser*`, aucune des
46 tables actuelles — donc aucune donnée réelle en jeu).

**Action manuelle requise en production, jamais exécutée depuis cet
environnement (pas d'accès) :**
```bash
python manage.py migrate yeki 0001_initial --fake
```
`--fake` marque la migration comme appliquée **sans exécuter le moindre
`CREATE TABLE`**, puisque les 46 tables existent déjà. **Ne jamais lancer
un `migrate` non-`--fake` sur cette migration précise en production** —
cela tenterait de recréer des tables déjà existantes.

Hypothèse posée : les noms de tables réels en production suivent la
convention par défaut Django (`yeki_profile`, `yeki_cours`, etc.). À
vérifier (`\dt` ou équivalent côté serveur) avant de lancer le `--fake` si
un doute existe.

## Méthode appliquée à chacune des 9 apps (identique à chaque fois)

1. Copie exacte du code de chaque modèle dans `apps/<app>/models.py` (champs,
   `Meta`, méthodes, propriétés — inchangés), avec :
   - `db_table = "yeki_<nom_modele_minuscule>"` explicite dans chaque
     `Meta`, pour garantir qu'aucune table ne bouge physiquement.
   - Références croisées vers un modèle d'une autre app sous forme chaîne
     `"accounts.Profile"` / `"formation.Cours"` / `"evaluation.Olympiade"`
     (obligatoire dès qu'une référence Django `ForeignKey("NomSeul", ...)`
     — sans le préfixe d'app — pointait vers un modèle qui vient de
     déménager : Django résout un nom non préfixé dans l'app courante ;
     laisser `"Profile"` dans un modèle resté en `yeki` après le départ de
     `Profile` vers `accounts` aurait créé une référence pendante. Corrigé
     à chaque étape où le cas se présentait : `Devoir.cree_par`,
     `Olympiade.organisateur` → `"accounts.Profile"` ; `Devoir.cours_lie`
     → `"formation.Cours"`.
   - Constantes/fonctions colocalisées suivent leur modèle :
     `COURSE_COLOR_PALETTE`/`COURSE_COLOR_CHOICES` → `formation` (avec
     `Cours`) ; `enregistrer_activite` → `core` (avec `HistoriqueActivite`) ;
     `creer_notification` → `notifications` (avec `Notification`).
2. `yeki/models.py` : la classe déplacée est remplacée par un import de
   ré-export (`from apps.accounts.models import Profile`).
3. `manage.py makemigrations <app>` → migration générée avec un
   `CreateModel` réel par modèle : éditée à la main pour envelopper toutes
   les opérations dans
   `migrations.SeparateDatabaseAndState(state_operations=[...], database_operations=[])`.
4. `manage.py makemigrations yeki` → migration générée avec les
   `RemoveField`/`AlterField`/`DeleteModel` nécessaires (un modèle qui
   migre d'app oblige Django à mettre à jour l'état de toute autre table de
   `yeki` qui a une FK vers lui) : également enveloppée dans
   `SeparateDatabaseAndState`. Vérifié systématiquement qu'aucune opération
   de schéma n'apparaissait hors de ce wrapper.
5. Schéma SQL comparé caractère pour caractère avant/après chaque
   application (`sqlite_master.sql`) — strictement identique à chaque
   étape, confirmé aussi sur l'ensemble des 52 tables `yeki_*` (46 modèles
   actuels + 3 tables M2M auto-générées + 3 tables résiduelles
   `yeki_customuser*`) après la dernière migration.

## Répartition finale des 46 modèles

| App | Modèles |
|---|---|
| `core` | `HistoriqueActivite`, `AppVersion` |
| `accounts` | `Profile`, `PasswordResetOTP` |
| `formation` | `Parcours`, `Departement`, `DemandeAccesFormation`, `Cours`, `Module`, `Lecon`, `SupplementCours`, `ProgressionLecon`, `LeconLike` |
| `evaluation` | `Exercice`, `SessionExercice`, `Question`, `Choix`, `ExerciceTentative`, `EvaluationExercice`, `ReponseExercice`, `Devoir`, `QuestionDevoir`, `ChoixReponse`, `SoumissionDevoir`, `ReponseDevoir`, `Olympiade`, `InscriptionOlympiade`, `ReponseOlympiade`, `ClassementOlympiade`, `RangApprenant`, `ScoreDetail` |
| `forum` | `QuestionForum`, `ReponseQuestion`, `LikeReponse`, `ReponseImage` |
| `paiement` | `Paiement`, `PaiementOlympiade`, `AbonnementPremium`, `YekiWallet`, `WalletTransaction`, `YekiCompteIA`, `CinetPayTransaction` |
| `ia` | `YekiIAPersonalite`, `YekiIAChatHistorique` |
| `notifications` | `Notification` |
| `repetiteurs` | `Repetiteur` |

`AppVersion` n'était listé dans aucune des 9 apps par la consigne (donnée
explicitement pour `core`→`accounts`→`formation`→`evaluation` puis les 5
dernières nommées sans répartition détaillée) : placé dans `core` par
analogie avec `HistoriqueActivite` (infrastructure transverse, pas de
domaine métier propre) — à confirmer/corriger si une autre app était
voulue, déplacement trivial si besoin (même méthode).

## Historique des migrations créées

- `yeki/migrations/0001_initial.py` — bootstrap (46 `CreateModel` réels,
  voir avertissement ci-dessus).
- `apps/core/migrations/0001_initial.py` + `yeki/migrations/0002_*.py`
- `apps/accounts/migrations/0001_initial.py` + `yeki/migrations/0003_*.py`
- `apps/formation/migrations/0001_initial.py` + `yeki/migrations/0004_*.py`
- `apps/evaluation/migrations/0001_initial.py` + `yeki/migrations/0005_*.py`
- `apps/forum/migrations/0001_initial.py` + `yeki/migrations/0006_*.py`
- `apps/paiement/migrations/0001_initial.py` + `yeki/migrations/0007_*.py`
- `apps/ia/migrations/0001_initial.py` + `yeki/migrations/0008_*.py`
- `apps/notifications/migrations/0001_initial.py` + `yeki/migrations/0009_*.py`
- `apps/repetiteurs/migrations/0001_initial.py` + `yeki/migrations/0010_*.py`

Toutes les migrations `apps/*/0001_initial.py` et `yeki/migrations/000{2..10}_*.py`
sont entièrement enveloppées dans `SeparateDatabaseAndState` avec
`database_operations=[]` — aucune n'exécute de SQL de modification de
schéma. Seule `yeki/migrations/0001_initial.py` (l'étape 0) contient de
vraies opérations de schéma, et seulement parce qu'elle documente un état
déjà présent en production (à appliquer là-bas en `--fake` uniquement).

## Point non traité, recommandé en suite séparée

`django_content_type` garde des lignes `app_label='yeki'` pour chacun des
46 modèles déplacés — Django ne les migre pas automatiquement lors d'un
changement d'app_label. Conséquence : les permissions `auth_permission`
existantes deviennent orphelines (nouvelles permissions créées sous les
nouveaux app_labels, sans suppression des anciennes — pas de perte, mais
doublons silencieux). Un remappage
(`ContentType.objects.filter(app_label='yeki', model=...).update(app_label=...)`
pour chacun des 46 modèles) réglerait proprement ce point. Non exécuté ici
— cette tâche portait strictement sur le déplacement des modèles, pas sur
la table système `django_content_type` ; à traiter séparément avec
confirmation explicite.

## Vérification

- Les 52 tables `yeki_*` (46 modèles actuels + 3 M2M auto-générées + 3
  résiduelles `yeki_customuser*`) comparées champ pour champ
  (`sqlite_master.sql`) avant/après l'application de **chacune** des 10
  paires de migrations : identiques à chaque fois, confirmé une dernière
  fois sur l'ensemble après la toute dernière migration.
- Les 46 modèles vérifiés un par un : `app_label` correct (`apps.get_model(
  '<app>', '<Modele>')._meta.app_label == '<app>'`) et ré-export
  `yeki.models.<Modele> is apps.get_model('<app>', '<Modele>')` — les deux
  systématiquement confirmés vrais.
- `python manage.py check` bute sur le même blocage préexistant et sans
  rapport que lors des tâches précédentes de cette session
  (`yeki/ranking_service.py` modifié localement, non commité,
  `RankingService` n'y existe plus) — contourné pour toutes les commandes
  `makemigrations`/`migrate` de cette tâche via `--skip-checks` (n'affecte
  pas la détection de migrations, seulement les vérifications système
  Django classiques comme la résolution des gestionnaires d'erreurs
  d'URLs).

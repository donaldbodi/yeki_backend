# Rotation des secrets — YÉKI backend

## Constat

Le 2026-07-16, il a été vérifié que `yeki_backend/settings.py`, versionné sur
GitHub (`origin/main`, dépôt `donaldbodi/yeki_backend`) depuis de nombreux
commits (`git log -- yeki_backend/settings.py` remonte à v-2.7.78 et avant),
contenait en clair :

- `SECRET_KEY` — clé Django jamais régénérée depuis `startproject` (préfixe
  `django-insecure-`).
- `EMAIL_HOST_USER` — adresse Gmail utilisée comme expéditeur SMTP.
- `EMAIL_HOST_PASSWORD` — mot de passe d'application Gmail.
- `CINETPAY_API_KEY` / `CINETPAY_SITE_ID` — utilisés en valeur par défaut
  (donc actifs même sans variable d'environnement définie).

**Ces quatre secrets doivent être considérés comme DÉFINITIVEMENT
COMPROMIS**, y compris après une éventuelle réécriture de l'historique Git
(`filter-repo`, BFG, etc.) : le dépôt est public sur GitHub, ils ont pu être
indexés, clonés, ou consultés par des tiers à n'importe quel moment depuis
leur premier commit. Réécrire l'historique n'annule pas une fuite déjà
passée — seule la rotation (invalidation + remplacement) protège réellement.

Le code lit désormais ces valeurs via `django-environ` (`env('...')`, sans
valeur par défaut) depuis un fichier `.env` local (non commité, voir
`.gitignore`) ou depuis les variables d'environnement du serveur en
production. Voir `.env.example` pour la liste des clés attendues.

## Procédure de rotation (manuelle — acte de l'administrateur)

### 1. SECRET_KEY

1. Générer une nouvelle valeur :
   ```bash
   python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
   ```
2. Mettre à jour `SECRET_KEY` dans le `.env` local ET dans la configuration
   d'environnement du serveur de production (PythonAnywhere).
3. Redéployer / redémarrer l'application.

**Conséquence directe :** `SECRET_KEY` signe les sessions Django et les
cookies CSRF — la changer invalide immédiatement :
- toutes les sessions actives basées sur `SessionAuthentication` (les
  utilisateurs devront se reconnecter) ;
- tous les cookies CSRF en cours.

**Ce que la rotation NE règle PAS automatiquement :** les tokens
`rest_framework.authtoken` (`TokenAuthentication`, utilisés par l'app Flutter
via `Authorization: Token <token>`) sont des valeurs aléatoires stockées en
base (table `authtoken_token`), **indépendantes de `SECRET_KEY`**. Ils
survivent à la rotation et restent valides. Comme le `SECRET_KEY` a fuité,
ces tokens doivent être régénérés séparément si l'on veut une remise à zéro
complète :
```bash
python manage.py shell -c "
from rest_framework.authtoken.models import Token
Token.objects.all().delete()
"
```
⚠️ Ceci déconnecte immédiatement TOUS les utilisateurs de l'app mobile (ils
devront se reconnecter pour obtenir un nouveau token). À planifier en dehors
des heures d'usage, avec information préalable si possible.

### 2. Mot de passe d'application Gmail

1. Aller sur https://myaccount.google.com/apppasswords avec le compte
   `EMAIL_HOST_USER` concerné.
2. Révoquer l'ancien mot de passe d'application (celui qui a fuité).
3. Générer un nouveau mot de passe d'application dédié à YÉKI.
4. Mettre à jour `EMAIL_HOST_PASSWORD` dans le `.env` local et en production.

### 3. Clé CinetPay

1. Se connecter au tableau de bord marchand CinetPay.
2. Demander la régénération de `CINETPAY_API_KEY` (et de `CINETPAY_SITE_ID`
   si l'offre CinetPay le permet — sinon contacter le support CinetPay en
   signalant la fuite, le site ID seul seul n'est pas un secret exploitable
   sans la clé API mais autant le signaler par prudence).
3. Mettre à jour `CINETPAY_API_KEY` / `CINETPAY_SITE_ID` dans le `.env` local
   et en production.
4. Vérifier un paiement de test avant de considérer la rotation terminée.

### 4. Après rotation

- Vérifier que `.env` local et les variables d'environnement du serveur de
  production contiennent bien les nouvelles valeurs (jamais les anciennes).
- Vérifier qu'aucune des quatre anciennes valeurs ne reste écrite en dur nulle
  part dans le dépôt : `grep -rniE "SECRET_KEY *=|PASSWORD *=|API_KEY *=" --include=*.py .`
  (hors `venv/`) ne doit renvoyer que des lectures `env(...)`.
- Envisager, séparément de cette rotation, de retirer `venv/` et
  `db.sqlite3` de l'historique Git (actuellement versionnés car
  `.gitignore` était nommé `.gitignore.txt` et donc inactif jusqu'à cette
  intervention) — action distincte, destructive sur l'historique, à ne
  mener qu'avec confirmation écrite explicite.

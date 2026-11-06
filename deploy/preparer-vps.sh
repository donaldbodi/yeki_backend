#!/bin/sh
# Préparation initiale du VPS Ubuntu, à lancer une seule fois :
#   sudo sh preparer-vps.sh
set -eu

UTILISATEUR="${SUDO_USER:-ubuntu}"
ACCUEIL="$(getent passwd "$UTILISATEUR" | cut -d: -f6)"

echo "→ Mises à jour et paquets..."
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y
DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl ufw fail2ban unattended-upgrades

echo "→ Docker..."
if ! command -v docker >/dev/null; then
    curl -fsSL https://get.docker.com | sh
fi
usermod -aG docker "$UTILISATEUR"

echo "→ Pare-feu..."
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Uniquement si une clé est déjà en place, pour ne pas se fermer la porte.
if [ -s "$ACCUEIL/.ssh/authorized_keys" ]; then
    echo "→ SSH par clé uniquement..."
    printf 'PasswordAuthentication no\nPermitRootLogin no\n' >/etc/ssh/sshd_config.d/00-yeki.conf
    systemctl reload ssh
else
    echo "⚠ Aucune clé SSH trouvée : connexion par mot de passe laissée active."
fi

echo "→ Dossier de l'application..."
mkdir -p /opt/yeki/backups
chown -R "$UTILISATEUR:$UTILISATEUR" /opt/yeki

echo "→ Sauvegarde quotidienne à 3 h..."
printf '0 3 * * * %s sh /opt/yeki/deploy/sauvegarder.sh >>/opt/yeki/backups/sauvegarde.log 2>&1\n' \
    "$UTILISATEUR" >/etc/cron.d/yeki-sauvegarde

echo "Terminé. Se déconnecter puis se reconnecter pour que le groupe docker s'applique."

from django.conf import settings
from django.core.mail import send_mail

from apps.accounts.models import Profile


def _get_profile(user):
    try:
        return user.profile
    except Profile.DoesNotExist:
        return None


def _is_premium(user):
    from apps.paiement.models import AbonnementPremium

    try:
        return user.abonnement.est_actif
    except AbonnementPremium.DoesNotExist:
        return False


def _nom_profil(profile):
    n = f"{profile.user.first_name} {profile.user.last_name}".strip()
    return n or profile.user.username


def _envoyer_email_desactivation_enseignant(profile):
    """Envoie un email de notification de désactivation."""
    user = profile.user
    nom = f"{user.first_name} {user.last_name}".strip() or user.username

    sujet = "ℹ️ Votre compte Yéki a été désactivé"

    message_texte = f"""
Bonjour {nom},

Votre compte enseignant sur Yéki a été désactivé par l'administrateur.

Vous ne pouvez plus vous connecter à la plateforme.
Pour toute question, veuillez contacter le support.

— L'équipe Yéki
"""

    message_html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: Arial, sans-serif; background: #f4f4f4; margin: 0; padding: 0; }}
    .container {{ max-width: 480px; margin: 40px auto; background: white;
                  border-radius: 16px; overflow: hidden;
                  box-shadow: 0 4px 20px rgba(0,0,0,0.08); }}
    .header {{ background: linear-gradient(135deg, #2884A9, #2A657D);
               padding: 32px 24px; text-align: center; }}
    .header h1 {{ color: white; margin: 0; font-size: 22px; }}
    .header p  {{ color: rgba(255,255,255,0.8); margin: 8px 0 0; font-size: 14px; }}
    .body   {{ padding: 32px 24px; text-align: center; }}
    .greeting {{ color: #1E293B; font-size: 15px; margin-bottom: 24px; }}
    .note {{ color: #94A3B8; font-size: 11px; margin-top: 28px;
             border-top: 1px solid #E2E8F0; padding-top: 16px; }}
    .footer {{ background: #F8FAFC; padding: 16px; text-align: center;
               color: #94A3B8; font-size: 11px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>ℹ️ Compte désactivé</h1>
      <p>Votre accès a été suspendu</p>
    </div>
    <div class="body">
      <p class="greeting">Bonjour <strong>{nom}</strong>,<br>
      Votre compte enseignant a été désactivé par l'administrateur Yéki.</p>

      <p class="note">
        Vous ne pouvez plus vous connecter à la plateforme.<br>
        Pour toute question, veuillez contacter le support.
      </p>
    </div>
    <div class="footer">© Yeki — Plateforme éducative</div>
  </div>
</body>
</html>
"""

    send_mail(
        subject=sujet,
        message=message_texte,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@yeki.app"),
        recipient_list=[user.email],
        html_message=message_html,
        fail_silently=False,
    )


def _envoyer_email_changement_type_enseignant(profile, ancien_type, nouveau_type):
    """
    Envoie un email de notification pour le changement de type.

    # TODO(correction): appelée uniquement par l'ancienne version (supprimée)
    # de AdminGeneralChangerTypeEnseignantView (doublon mort L356-443 dans
    # yeki/views.py avant l'éclatement). La version active de cette vue
    # n'envoie aucun email — comportement perdu par l'écrasement Python
    # (voir docs/AUDIT_BACKEND.md §2.1). Conservée telle quelle, non
    # rebranchée, en attente d'une décision produit sur la réintégration.
    """
    user = profile.user
    nom = f"{user.first_name} {user.last_name}".strip() or user.username

    type_labels = {
        "enseignant": "Enseignant",
        "enseignant_principal": "Enseignant Principal",
        "enseignant_cadre": "Enseignant Cadre",
        "enseignant_admin": "Enseignant Administrateur",
    }

    ancien_label = type_labels.get(ancien_type, ancien_type)
    nouveau_label = type_labels.get(nouveau_type, nouveau_type)

    sujet = "📋 Votre grade Yéki a été modifié"

    message_texte = f"""
Bonjour {nom},

L'administrateur Yéki a modifié votre grade sur la plateforme.

Ancien grade : {ancien_label}
Nouveau grade : {nouveau_label}

Connectez-vous pour voir les nouvelles fonctionnalités accessibles avec votre nouveau grade.

— L'équipe Yéki
"""

    message_html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: Arial, sans-serif; background: #f4f4f4; margin: 0; padding: 0; }}
    .container {{ max-width: 480px; margin: 40px auto; background: white;
                  border-radius: 16px; overflow: hidden;
                  box-shadow: 0 4px 20px rgba(0,0,0,0.08); }}
    .header {{ background: linear-gradient(135deg, #2884A9, #2A657D);
               padding: 32px 24px; text-align: center; }}
    .header h1 {{ color: white; margin: 0; font-size: 22px; }}
    .header p  {{ color: rgba(255,255,255,0.8); margin: 8px 0 0; font-size: 14px; }}
    .body   {{ padding: 32px 24px; text-align: center; }}
    .greeting {{ color: #1E293B; font-size: 15px; margin-bottom: 24px; }}
    .grade-box {{ background: #F1F5F9; border-radius: 12px; padding: 20px; margin: 0 auto;
                  display: inline-block; min-width: 200px; text-align: left; }}
    .grade-box div {{ padding: 4px 0; color: #1E293B; }}
    .grade-box strong {{ color: #2884A9; }}
    .note {{ color: #94A3B8; font-size: 11px; margin-top: 28px;
             border-top: 1px solid #E2E8F0; padding-top: 16px; }}
    .footer {{ background: #F8FAFC; padding: 16px; text-align: center;
               color: #94A3B8; font-size: 11px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>📋 Grade mis à jour</h1>
      <p>Votre rôle sur la plateforme a changé</p>
    </div>
    <div class="body">
      <p class="greeting">Bonjour <strong>{nom}</strong>,<br>
      L'administrateur Yéki a modifié votre grade.</p>

      <div class="grade-box">
        <div><strong>Ancien grade :</strong> {ancien_label}</div>
        <div><strong>Nouveau grade :</strong> {nouveau_label}</div>
      </div>

      <p class="note">
        Connectez-vous pour découvrir les nouvelles fonctionnalités accessibles.
      </p>
    </div>
    <div class="footer">© Yeki — Plateforme éducative</div>
  </div>
</body>
</html>
"""

    send_mail(
        subject=sujet,
        message=message_texte,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@yeki.app"),
        recipient_list=[user.email],
        html_message=message_html,
        fail_silently=False,
    )


def _envoyer_email_activation_enseignant(profile):
    """
    Envoie un email de confirmation à l'enseignant après activation.
    """
    user = profile.user
    nom = f"{user.first_name} {user.last_name}".strip() or user.username

    sujet = "✅ Votre compte Yéki est activé"

    message_texte = f"""
Bonjour {nom},

Félicitations ! Votre compte enseignant a été activé par l'administrateur Yéki.

Vous pouvez maintenant vous connecter à la plateforme avec vos identifiants.

Identifiant : {user.username}
Email : {user.email}

Si vous avez oublié votre mot de passe, utilisez la fonction "Mot de passe oublié" sur la page de connexion.

— L'équipe Yéki
"""

    message_html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: Arial, sans-serif; background: #f4f4f4; margin: 0; padding: 0; }}
    .container {{ max-width: 480px; margin: 40px auto; background: white;
                  border-radius: 16px; overflow: hidden;
                  box-shadow: 0 4px 20px rgba(0,0,0,0.08); }}
    .header {{ background: linear-gradient(135deg, #2884A9, #2A657D);
               padding: 32px 24px; text-align: center; }}
    .header h1 {{ color: white; margin: 0; font-size: 22px; }}
    .header p  {{ color: rgba(255,255,255,0.8); margin: 8px 0 0; font-size: 14px; }}
    .body   {{ padding: 32px 24px; text-align: center; }}
    .greeting {{ color: #1E293B; font-size: 15px; margin-bottom: 24px; }}
    .credentials {{ background: #F1F5F9; border-radius: 12px; padding: 20px; margin: 0 auto;
                    display: inline-block; min-width: 200px; text-align: left; }}
    .credentials div {{ padding: 4px 0; color: #1E293B; }}
    .credentials strong {{ color: #2884A9; }}
    .note {{ color: #94A3B8; font-size: 11px; margin-top: 28px;
             border-top: 1px solid #E2E8F0; padding-top: 16px; }}
    .footer {{ background: #F8FAFC; padding: 16px; text-align: center;
               color: #94A3B8; font-size: 11px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>✅ Compte activé</h1>
      <p>Vous pouvez maintenant accéder à Yéki</p>
    </div>
    <div class="body">
      <p class="greeting">Bonjour <strong>{nom}</strong>,<br>
      Votre compte enseignant a été activé par l'administrateur Yéki.</p>

      <div class="credentials">
        <div><strong>Identifiant :</strong> {user.username}</div>
        <div><strong>Email :</strong> {user.email}</div>
      </div>

      <p class="note">
        Si vous avez oublié votre mot de passe, utilisez la fonction "Mot de passe oublié"
        sur la page de connexion.
      </p>
    </div>
    <div class="footer">© Yeki — Plateforme éducative</div>
  </div>
</body>
</html>
"""

    send_mail(
        subject=sujet,
        message=message_texte,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@yeki.app"),
        recipient_list=[user.email],
        html_message=message_html,
        fail_silently=False,
    )


def _envoyer_email_changement_type(profile, ancien_type, nouveau_type):
    """Envoie un email de confirmation pour le changement de type."""
    user = profile.user
    nom = f"{user.first_name} {user.last_name}".strip() or user.username

    labels = {
        "enseignant": "Enseignant",
        "enseignant_principal": "Enseignant Principal",
        "enseignant_cadre": "Enseignant Cadre",
        "enseignant_admin": "Enseignant Administrateur",
    }
    ancien_label = labels.get(ancien_type, ancien_type)
    nouveau_label = labels.get(nouveau_type, nouveau_type)

    sujet = "📝 Votre grade d'enseignant a été modifié"

    message_texte = f"""
Bonjour {nom},

L'administrateur général a modifié votre grade d'enseignant sur Yéki.

Ancien grade : {ancien_label}
Nouveau grade : {nouveau_label}

Ce changement vous permet d'accéder à de nouvelles fonctionnalités sur la plateforme.

— L'équipe Yéki
"""

    message_html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: Arial, sans-serif; background: #f4f4f4; margin: 0; padding: 0; }}
    .container {{ max-width: 480px; margin: 40px auto; background: white;
                  border-radius: 16px; overflow: hidden;
                  box-shadow: 0 4px 20px rgba(0,0,0,0.08); }}
    .header {{ background: linear-gradient(135deg, #2884A9, #2A657D);
               padding: 32px 24px; text-align: center; }}
    .header h1 {{ color: white; margin: 0; font-size: 22px; }}
    .header p  {{ color: rgba(255,255,255,0.8); margin: 8px 0 0; font-size: 14px; }}
    .body   {{ padding: 32px 24px; text-align: center; }}
    .greeting {{ color: #1E293B; font-size: 15px; margin-bottom: 24px; }}
    .grade-box {{ background: #F1F5F9; border-radius: 12px; padding: 20px; margin: 0 auto;
                  display: inline-block; min-width: 200px; text-align: left; }}
    .grade-box div {{ padding: 4px 0; color: #1E293B; }}
    .grade-box strong {{ color: #2884A9; }}
    .note {{ color: #94A3B8; font-size: 11px; margin-top: 28px;
             border-top: 1px solid #E2E8F0; padding-top: 16px; }}
    .footer {{ background: #F8FAFC; padding: 16px; text-align: center;
               color: #94A3B8; font-size: 11px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>📝 Grade modifié</h1>
      <p>Votre compte enseignant a été mis à jour</p>
    </div>
    <div class="body">
      <p class="greeting">Bonjour <strong>{nom}</strong>,<br>
      L'administrateur général a modifié votre grade d'enseignant sur Yéki.</p>

      <div class="grade-box">
        <div><strong>Ancien grade :</strong> {ancien_label}</div>
        <div><strong>Nouveau grade :</strong> {nouveau_label}</div>
      </div>

      <p class="note">
        Ce changement vous permet d'accéder à de nouvelles fonctionnalités sur la plateforme.
      </p>
    </div>
    <div class="footer">© Yeki — Plateforme éducative</div>
  </div>
</body>
</html>
"""

    send_mail(
        subject=sujet,
        message=message_texte,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@yeki.app"),
        recipient_list=[user.email],
        html_message=message_html,
        fail_silently=False,
    )


def _envoyer_email_otp(user, code):
    """Envoie l'email contenant le code OTP."""
    nom = f"{user.first_name} {user.last_name}".strip() or user.username

    sujet = "🔐 Votre code de vérification Yéki"

    message_texte = f"""
Bonjour {nom},

Vous avez demandé la réinitialisation de votre mot de passe sur Yéki.

Votre code de vérification est : {code}

Ce code est valable pendant 10 minutes.
Si vous n'avez pas fait cette demande, ignorez cet email.

— L'équipe Yéki
"""

    message_html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: Arial, sans-serif; background: #f4f4f4; margin: 0; padding: 0; }}
    .container {{ max-width: 480px; margin: 40px auto; background: white;
                  border-radius: 16px; overflow: hidden;
                  box-shadow: 0 4px 20px rgba(0,0,0,0.08); }}
    .header {{ background: linear-gradient(135deg, #2884A9, #2A657D);
               padding: 32px 24px; text-align: center; }}
    .header h1 {{ color: white; margin: 0; font-size: 22px; }}
    .header p  {{ color: rgba(255,255,255,0.8); margin: 8px 0 0; font-size: 14px; }}
    .body   {{ padding: 32px 24px; text-align: center; }}
    .greeting {{ color: #1E293B; font-size: 15px; margin-bottom: 24px; }}
    .code-box {{ background: #F1F5F9; border: 2px dashed #2884A9;
                 border-radius: 12px; padding: 20px; margin: 0 auto;
                 display: inline-block; min-width: 200px; }}
    .code {{ font-size: 38px; font-weight: bold; letter-spacing: 10px;
             color: #2884A9; font-family: monospace; }}
    .validity {{ color: #64748B; font-size: 12px; margin-top: 8px; }}
    .note  {{ color: #94A3B8; font-size: 11px; margin-top: 28px;
               border-top: 1px solid #E2E8F0; padding-top: 16px; }}
    .footer {{ background: #F8FAFC; padding: 16px; text-align: center;
               color: #94A3B8; font-size: 11px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>🔐 Code de vérification</h1>
      <p>Réinitialisation de mot de passe</p>
    </div>
    <div class="body">
      <p class="greeting">Bonjour <strong>{nom}</strong>,<br>
      Voici votre code pour réinitialiser votre mot de passe.</p>

      <div class="code-box">
        <div class="code">{code}</div>
        <div class="validity">⏱ Valable 10 minutes</div>
      </div>

      <p class="note">
        Si vous n'avez pas demandé la réinitialisation de votre mot de passe,
        ignorez cet email. Votre compte reste sécurisé.
      </p>
    </div>
    <div class="footer">© Yeki — Plateforme éducative</div>
  </div>
</body>
</html>
"""

    send_mail(
        subject=sujet,
        message=message_texte,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@yeki.app"),
        recipient_list=[user.email],
        html_message=message_html,
        fail_silently=False,
    )


def _envoyer_email_confirmation(user):
    """Email de confirmation après changement réussi."""
    from django.utils import timezone

    nom = f"{user.first_name} {user.last_name}".strip() or user.username
    now_str = timezone.now().strftime("%d/%m/%Y à %H:%M")

    send_mail(
        subject="✅ Mot de passe modifié — Yeki",
        message=f"Bonjour {nom},\n\nVotre mot de passe a été modifié le {now_str}.\nSi ce n'est pas vous, contactez-nous immédiatement.\n\n— L'équipe Yeki",
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@yeki.app"),
        recipient_list=[user.email],
        fail_silently=True,
    )

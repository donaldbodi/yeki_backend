import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.authtoken.models import Token

from apps.accounts.models import Profile, PasswordResetOTP
from apps.accounts.serializers import RegisterSerializer, LoginSerializer
from apps.accounts.services import (
    _envoyer_email_otp,
    _envoyer_email_confirmation,
)

from drf_spectacular.utils import extend_schema, extend_schema_view
from drf_spectacular.types import OpenApiTypes
from apps.core.schema_examples import (
    ERREURS_COURANTES,
    ERREURS_ECRITURE,
    EXEMPLE_THROTTLED,
)

User = get_user_model()
logger = logging.getLogger(__name__)


@extend_schema_view(
    post=extend_schema(
        summary="Créer un compte utilisateur",
        description=(
            "Crée un nouveau compte (apprenant ou enseignant selon les champs "
            "fournis) et retourne un token d'authentification immédiatement "
            "utilisable, ainsi que le rôle et les informations de base de "
            "l'utilisateur créé."
        ),
        tags=["accounts"],
        request=RegisterSerializer,
        responses={201: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = serializer.save()

        token, _ = Token.objects.get_or_create(user=profile.user)

        return Response(
            {
                "token": token.key,
                "role": profile.user_type,
                "user": {
                    "id": profile.user.id,
                    "username": profile.user.username,
                    "email": profile.user.email,
                },
            },
            status=status.HTTP_201_CREATED,
        )


@extend_schema_view(
    post=extend_schema(
        summary="Se connecter",
        description=(
            "Authentifie un utilisateur avec son identifiant et son mot de passe "
            "et retourne un token d'authentification, son rôle et ses "
            "informations de base. Renvoie 403 si le compte enseignant est en "
            "attente de validation par l'administrateur. Limité à 5 tentatives "
            "par minute (anti brute-force, CDC_BACKEND §2.5)."
        ),
        tags=["accounts"],
        request=LoginSerializer,
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_THROTTLED, *ERREURS_ECRITURE],
    ),
)
class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "login"  # anti brute-force (CDC_BACKEND §2.5) : 5/min

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        profile = Profile.objects.get(user=user)

        # Vérifier si le compte est actif
        if not profile.is_active:
            return Response(
                {
                    "detail": "⚠️ Votre compte enseignant est en attente de validation par l'administrateur.",
                    "error_type": "account_inactive",
                    "role": profile.user_type,
                },
                status=403,
            )

        token, _ = Token.objects.get_or_create(user=user)

        return Response(
            {
                "token": token.key,
                "role": profile.user_type,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                },
            },
            status=200,
        )


@extend_schema_view(
    post=extend_schema(
        summary="Demander un code de réinitialisation de mot de passe",
        description=(
            "Envoie par email un code OTP à 6 chiffres (valable 10 minutes) "
            "permettant de réinitialiser le mot de passe. Corps attendu : "
            '`{"email": "..."}`. La réponse est volontairement générique '
            "(200) même si l'email n'existe pas, afin de ne pas révéler les "
            "comptes existants. Limité à 3 demandes par 10 minutes (anti-abus, "
            "CDC_BACKEND §2.5). En mode DEBUG, le code est renvoyé directement "
            "dans la réponse si l'envoi d'email échoue."
        ),
        tags=["accounts"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[EXEMPLE_THROTTLED, *ERREURS_ECRITURE],
    ),
)
class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]  # public : demande de réinitialisation, avant connexion
    throttle_scope = "otp"  # anti-abus de l'envoi d'OTP par email (CDC_BACKEND §2.5) : 3/10min

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()

        if not email:
            return Response(
                {"detail": "L'adresse email est requise."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Réponse générique pour ne pas révéler si l'email existe
        generic_response = Response(
            {"detail": "Si cet email est enregistré, vous recevrez un code de vérification."},
            status=status.HTTP_200_OK,
        )

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return generic_response

        # Invalider tous les OTP précédents non utilisés de cet utilisateur
        PasswordResetOTP.objects.filter(user=user, used=False).update(used=True)

        # Créer un nouvel OTP (le code est généré dans le save())
        otp = PasswordResetOTP.objects.create(user=user)

        # ── Envoyer l'email ───────────────────────────────────────
        try:
            _envoyer_email_otp(user, otp.code)
        except Exception:
            # Volontairement large : l'envoi d'email peut échouer pour de
            # nombreuses raisons (SMTP, réseau...) qui ne doivent jamais
            # empêcher la demande de réinitialisation de réussir.
            logger.exception("Erreur envoi OTP email")
            # En développement, renvoyer le code dans la réponse pour tests
            if settings.DEBUG:
                return Response(
                    {
                        "detail": "Email non envoyé (mode DEBUG). Code OTP pour test :",
                        "debug_code": otp.code,
                        "expires_in_minutes": 10,
                    },
                    status=status.HTTP_200_OK,
                )

        return generic_response


@extend_schema_view(
    post=extend_schema(
        summary="Vérifier le code OTP de réinitialisation",
        description=(
            "Vérifie le code OTP reçu par email. Corps attendu : "
            '`{"email": "...", "code": "123456"}`. Maximum 5 tentatives '
            "par code avant blocage. En cas de succès, retourne un "
            "`reset_token` temporaire à utiliser pour finaliser la "
            "réinitialisation via `ResetPasswordView`."
        ),
        tags=["accounts"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class VerifyOTPView(APIView):
    permission_classes = [AllowAny]  # public : vérification du code OTP, avant connexion

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        code = (request.data.get("code") or "").strip()

        if not email or not code:
            return Response(
                {"detail": "Email et code sont requis."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Récupérer l'utilisateur
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return Response(
                {"detail": "Code invalide ou expiré."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Récupérer le dernier OTP actif
        otp = PasswordResetOTP.objects.filter(user=user, used=False).order_by("-created_at").first()

        if otp is None:
            return Response(
                {"detail": "Aucun code en attente. Faites une nouvelle demande."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Vérifier expiration
        if not otp.is_valid:
            if otp.attempts >= 5:
                return Response(
                    {"detail": "Trop de tentatives. Demandez un nouveau code."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response(
                {"detail": "Ce code a expiré. Demandez un nouveau code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Incrémenter les tentatives
        otp.attempts += 1
        otp.save(update_fields=["attempts"])

        # Vérifier le code
        if otp.code != code:
            remaining = 5 - otp.attempts
            if remaining <= 0:
                otp.used = True
                otp.save(update_fields=["used"])
                return Response(
                    {"detail": "Code incorrect. Trop de tentatives. Demandez un nouveau code."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response(
                {"detail": f"Code incorrect. {remaining} tentative(s) restante(s)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Code correct → générer un reset_token temporaire ─────
        import secrets

        reset_token = secrets.token_urlsafe(32)

        # Stocker le token dans l'OTP (on réutilise le champ code)
        otp.code = f"VERIFIED:{reset_token}"
        otp.save(update_fields=["code"])

        return Response(
            {
                "detail": "Code vérifié avec succès.",
                "reset_token": reset_token,
            },
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    post=extend_schema(
        summary="Réinitialiser le mot de passe",
        description=(
            "Finalise la réinitialisation du mot de passe à l'aide du "
            "`reset_token` obtenu via `VerifyOTPView`. Corps attendu : "
            '`{"email": "...", "reset_token": "...", "new_password": '
            '"...", "confirm_password": "..."}`. Le mot de passe doit '
            "contenir au moins 8 caractères, une lettre et un chiffre. "
            "Invalide tous les tokens d'authentification existants, forçant "
            "une nouvelle connexion."
        ),
        tags=["accounts"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class ResetPasswordView(APIView):
    permission_classes = [AllowAny]  # public : réinitialisation finale, avant connexion

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        reset_token = (request.data.get("reset_token") or "").strip()
        new_password = (request.data.get("new_password") or "").strip()
        confirm_password = (request.data.get("confirm_password") or "").strip()

        # ── Validation des champs ─────────────────────────────────
        if not all([email, reset_token, new_password, confirm_password]):
            return Response(
                {"detail": "Tous les champs sont requis."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if new_password != confirm_password:
            return Response(
                {"detail": "Les mots de passe ne correspondent pas."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(new_password) < 8:
            return Response(
                {"detail": "Le mot de passe doit contenir au moins 8 caractères."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Vérification de la complexité ────────────────────────
        has_digit = any(c.isdigit() for c in new_password)
        has_alpha = any(c.isalpha() for c in new_password)
        if not (has_digit and has_alpha):
            return Response(
                {"detail": "Le mot de passe doit contenir au moins une lettre et un chiffre."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Récupérer l'utilisateur ───────────────────────────────
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return Response(
                {"detail": "Lien de réinitialisation invalide."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Vérifier le reset_token ───────────────────────────────
        otp = (
            PasswordResetOTP.objects.filter(
                user=user,
                used=False,
                code=f"VERIFIED:{reset_token}",
            )
            .order_by("-created_at")
            .first()
        )

        if otp is None or not otp.is_valid:
            return Response(
                {"detail": "Lien de réinitialisation invalide ou expiré. Recommencez."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Mettre à jour le mot de passe ─────────────────────────
        user.set_password(new_password)
        user.save()

        # Invalider l'OTP
        otp.used = True
        otp.save(update_fields=["used"])

        # Supprimer tous les anciens tokens d'auth → force une nouvelle connexion
        from rest_framework.authtoken.models import Token as AuthToken

        AuthToken.objects.filter(user=user).delete()

        # ── Email de confirmation ─────────────────────────────────
        try:
            _envoyer_email_confirmation(user)
        except Exception:
            # Volontairement large (idem OTP) : ne jamais bloquer la
            # réinitialisation, déjà appliquée, pour un aléa d'envoi.
            logger.exception("Erreur envoi email de confirmation reset mot de passe")

        return Response(
            {
                "detail": "Mot de passe réinitialisé avec succès. Connectez-vous avec votre nouveau mot de passe."
            },
            status=status.HTTP_200_OK,
        )


@extend_schema_view(
    post=extend_schema(
        summary="Changer son mot de passe (utilisateur connecté)",
        description=(
            "Change le mot de passe de l'utilisateur authentifié. Corps "
            'attendu : `{"old_password": "...", "new_password": "..."}`. '
            "Le nouveau mot de passe doit contenir au moins 8 caractères. "
            "Renouvelle le token d'authentification et le retourne dans la "
            "réponse."
        ),
        tags=["accounts"],
        request=OpenApiTypes.OBJECT,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_ECRITURE],
    ),
)
class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        old_password = request.data.get("old_password", "")
        new_password = request.data.get("new_password", "")

        if not old_password or not new_password:
            return Response({"detail": "Les deux champs sont requis."}, status=400)

        if not check_password(old_password, user.password):
            return Response({"detail": "Ancien mot de passe incorrect."}, status=400)

        if len(new_password) < 8:
            return Response(
                {"detail": "Le nouveau mot de passe doit contenir au moins 8 caractères."},
                status=400,
            )

        user.set_password(new_password)
        user.save()

        # Renouveler le token après changement de mdp
        try:
            user.auth_token.delete()
        except Token.DoesNotExist:
            pass
        token, _ = Token.objects.get_or_create(user=user)

        return Response(
            {"detail": "Mot de passe modifié avec succès.", "token": token.key}, status=200
        )


@extend_schema_view(
    post=extend_schema(
        summary="Se déconnecter",
        description="Supprime le token d'authentification de l'utilisateur connecté.",
        tags=["accounts"],
        request=None,
        responses={200: OpenApiTypes.OBJECT},
        examples=[*ERREURS_COURANTES],
    ),
)
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            # Si JWT : invalider le token côté serveur
            # Si Token : supprimer le token
            request.user.auth_token.delete()
        except Token.DoesNotExist:
            pass
        return Response({"detail": "Déconnecté avec succès"}, status=status.HTTP_200_OK)

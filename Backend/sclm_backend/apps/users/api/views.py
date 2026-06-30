"""
apps.users.api.views
─────────────────────────────────────────────────────────────────────────────
LoginView      POST /api/v1/users/auth/login/     [Public]
TokenRefresh   POST /api/v1/users/auth/refresh/   [Public]
MeView         GET  /api/v1/users/me/             [Authenticated]
LogoutView     POST /api/v1/users/auth/logout/    [Authenticated]
─────────────────────────────────────────────────────────────────────────────
Views are thin HTTP adapters — they validate input via serializers
and call the service layer. No business logic lives here.
"""
import logging
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.views import TokenRefreshView

from apps.users.api.serializers import (
    CustomTokenObtainPairSerializer,
    UserProfileSerializer,
    LogoutSerializer,
)

logger = logging.getLogger(__name__)


class LoginView(APIView):
    """
    POST /api/v1/users/auth/login/

    Accepts: { "email": "...", "password": "...", "tenant_id": "<uuid>" }
    Returns: { "access": "...", "refresh": "...", "role": "...", ... }

    The serializer validates credentials AND tenant membership.
    The tenant_id and role are embedded in the JWT payload.
    """
    permission_classes = [AllowAny]
    serializer_class = CustomTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        logger.info(
            "Successful login — email='%s', tenant_id='%s', role='%s'.",
            serializer.validated_data.get("email"),
            serializer.validated_data.get("tenant_id"),
            serializer.validated_data.get("role"),
        )
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


class SCLMTokenRefreshView(TokenRefreshView):
    """
    POST /api/v1/users/auth/refresh/
    Standard simplejwt refresh — no customization needed.
    The envelope renderer wraps the response automatically.
    """
    permission_classes = [AllowAny]


class MeView(APIView):
    """
    GET /api/v1/users/me/
    Returns the authenticated user's profile, tenant_id, and role.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        serializer = UserProfileSerializer(
            request.user,
            context={"request": request},
        )
        return Response(serializer.data, status=status.HTTP_200_OK)


class LogoutView(APIView):
    """
    POST /api/v1/users/auth/logout/
    Blacklists the provided refresh token and the current access token's JTI.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # Also blacklist the access token's JTI if present.
        jti = getattr(request, "token_jti", None)
        if jti:
            from apps.users.services import UserAuthService
            UserAuthService.blacklist_token(request.user, jti)

        logger.info("User '%s' logged out.", request.user.email)
        return Response(
            {"message": "Successfully logged out."},
            status=status.HTTP_200_OK,
        )

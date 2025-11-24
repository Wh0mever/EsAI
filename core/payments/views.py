import logging
import uuid

from django.urls import reverse
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from users.models import User
from .freedompay import FreedomPayHPPClient, FreedomPayError


logger = logging.getLogger("payments.freedompay")


class StartBindCardAPIView(APIView):
    """Generate FreedomPay Hosted Payment Page redirect URL."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        body = request.data or {}
        client = FreedomPayHPPClient()
        order_id = f"bind-{request.user.id}-{uuid.uuid4().hex[:8]}"
        callback_url = request.build_absolute_uri(reverse("card-bind-callback"))

        back_link_input = body.get("back_link") or body.get("back_path") or "/profile"
        if isinstance(back_link_input, str) and back_link_input.startswith(("http://", "https://")):
            back_link = back_link_input
        else:
            path = str(back_link_input or "/profile")
            if not path.startswith("/"):
                path = f"/{path}"
            back_link = request.build_absolute_uri(path)

        try:
            redirect_url = client.start_card_bind(
                user_id=request.user.id,
                order_id=order_id,
                post_link=callback_url,
                back_link=back_link,
            )
        except FreedomPayError as exc:
            logger.warning("FreedomPay bind start failed: %s payload=%s", exc, getattr(client, "last_request", {}))
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception:
            logger.exception("FreedomPay bind start unexpected error payload=%s", getattr(client, "last_request", {}))
            return Response({"detail": "freedompay_error"}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"redirect_url": redirect_url})


class FreedomPayCallbackAPIView(APIView):
    """Handle POST callback from FreedomPay once card is stored."""

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        payload = request.data or {}
        pg_status = str(payload.get("pg_status") or "").lower()
        if pg_status != "ok":
            logger.warning("FreedomPay callback ignored, status=%s", pg_status)
            return Response({"status": "ignored"}, status=status.HTTP_400_BAD_REQUEST)

        token = (payload.get("pg_card_token") or "").strip()
        user_id_raw = payload.get("pg_user_id")

        if not token or not user_id_raw:
            logger.warning("FreedomPay callback missing parameters")
            return Response({"status": "error", "detail": "missing_params"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user_id = int(user_id_raw)
        except (TypeError, ValueError):
            logger.warning("FreedomPay callback invalid user id: %s", user_id_raw)
            return Response({"status": "error", "detail": "invalid_user"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            logger.warning("FreedomPay callback user not found: %s", user_id)
            return Response({"status": "error", "detail": "user_not_found"}, status=status.HTTP_404_NOT_FOUND)

        User.objects.filter(pk=user.pk).update(pay_token=token[:1024])
        logger.info("FreedomPay token saved for user %s", user_id)
        return Response({"status": "ok"})

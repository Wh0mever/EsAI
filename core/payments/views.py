import logging
import uuid

from django.urls import reverse
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.conf import settings

from users.models import User
from .freedompay import FreedomPayHPPClient, FreedomPayError, save_freedompay_callback
from .models import Payment


logger = logging.getLogger()


class StartBindCardAPIView(APIView):
    """Generate FreedomPay Hosted Payment Page redirect URL."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        body = request.data or {}
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
            client = FreedomPayHPPClient()
        except FreedomPayError as exc:
            logger.warning("FreedomPay client init failed: %s", exc)
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception:
            logger.exception("FreedomPay client init unexpected error")
            return Response({"detail": "freedompay_error"}, status=status.HTTP_502_BAD_GATEWAY)

        logger.info(
            "FreedomPay bind init user=%s order=%s callback=%s back=%s",
            request.user.id,
            order_id,
            callback_url,
            back_link,
        )

        try:
            redirect_url = client.start_card_bind(
                user_id=request.user.id,
                post_link=callback_url,
                back_link=back_link,
            )
        except FreedomPayError as exc:
            logger.warning(
                "FreedomPay bind start failed: %s endpoint=%s request=%s response=%s",
                exc,
                getattr(client, "last_endpoint", ""),
                getattr(client, "last_request", {}),
                getattr(client, "last_response", {}),
            )
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception:
            logger.exception(
                "FreedomPay bind start unexpected error endpoint=%s request=%s response=%s",
                getattr(client, "last_endpoint", ""),
                getattr(client, "last_request", {}),
                getattr(client, "last_response", {}),
            )
            return Response({"detail": "freedompay_error"}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"redirect_url": redirect_url})


class FreedomPayCallbackAPIView(APIView):
    """Handle POST callback from FreedomPay once card is stored."""

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        is_success = save_freedompay_callback(request.data or {})
        
        if is_success is False:
            return Response({"status": "error"}, status=status.HTTP_400_BAD_REQUEST)
            
        return Response({"status": "ok"})


class FreedomPayChargeResultView(APIView):
    """Record recurring charge redirects/callbacks."""

    authentication_classes = []
    permission_classes = []
    result_type = "success"  # overridden in subclasses

    def get(self, request, *args, **kwargs):
        return self._handle(request.query_params)

    def post(self, request, *args, **kwargs):
        return self._handle(request.data)

    def _handle(self, payload_source):
        payload = self._normalize_payload(payload_source)
        order_id = payload.get("pg_order_id") or payload.get("order_id")
        self._persist_payment(order_id, payload)
        logger.warning(
            "FreedomPay %s callback order=%s payload=%s",
            self.result_type,
            order_id,
            payload,
        )
        message = {"status": "received", "result": self.result_type, "order_id": order_id}
        return Response(message, status=status.HTTP_200_OK)

    def _normalize_payload(self, data):
        if hasattr(data, "lists"):
            return {key: values[-1] if values else "" for key, values in data.lists()}
        if isinstance(data, dict):
            return {k: v for k, v in data.items()}
        return {}

    def _persist_payment(self, order_id, payload):
        if not order_id:
            return
        payment = Payment.objects.filter(order_id=order_id).order_by("-id").first()
        if not payment:
            return
        response = payment.response or {}
        callbacks = list(response.get("callbacks") or [])
        callbacks.append({"type": self.result_type, "payload": payload})
        response["callbacks"] = callbacks
        payment.response = response
        if self.result_type == "success":
            payment.success = True
            payment.error = ""
        elif self.result_type == "failure":
            payment.success = False
            payment.error = payload.get("pg_error_description") or payload.get("pg_error_message") or "freedompay_failure"
        payment.save(update_fields=["response", "success", "error"])


class FreedomPayChargeFailureView(FreedomPayChargeResultView):
    result_type = "failure"


class FreedomPayChargePostbackView(FreedomPayChargeResultView):
    result_type = "post"

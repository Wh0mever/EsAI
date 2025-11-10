import random
import json
from django.core.cache import cache
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import AllowAny
from .serializers import (
    SignUpSerializer,
    SignInSerializer,
    ProfileSerializer,
    NotificationDeliverySerializer,
    UserQuestionSerializer,
    UserFeedbackSerializer,
)
from core.format import format_errors
from mails.sender import send_template_email
from django.contrib.auth.hashers import make_password
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.authentication import JWTAuthentication
from plans.models import UserSubscription
from plans.serializers import UserSubscriptionSerializer
from .models import User, UserQuestions, Notification, NotificationDelivery
from rest_framework import generics, permissions
from rest_framework.exceptions import NotFound
from django.db.utils import DataError as DBDataError
from django.db import connection


class SigninApiView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = SignInSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data['user']
            email = user['email']

            try:
                user_object = User.objects.get(email=email)
                if not user_object._2fa:
                    refresh = RefreshToken.for_user(user_object)
                    return Response({
                        "status": "authenticated",
                        "data": {
                            "access": str(refresh.access_token),
                            "refresh": str(refresh),
                            "user": {
                                "id": user_object.id,
                                "email": user_object.email,
                                "tel": user_object.tel,
                            }
                        }
                    }, status=200)

            except Exception as ex:
                print(ex)
                return Response({"status": "error", "message": "user was not found"}, status=status.HTTP_400_BAD_REQUEST)

            code = str(random.randint(100000, 999999))
            cache.set(f"email_code:{email}", code, timeout=600)
            cache.set(f"auth_data:{email}",
                      serializer.validated_data, timeout=600)

            send_template_email(
                subject="Your verification code",
                template_name="verify_email.html",
                context={
                    "code": code, "message": "To confirm your email, please use the 6-digit code below:"},
                recipient_list=[email],
            )

            return Response({
                "status": "success",
                "message": "Verification code sent to email"
            }, status=status.HTTP_200_OK)
        return Response({
            "status": "error",
            "errors": format_errors(serializer.errors),
        }, status=status.HTTP_400_BAD_REQUEST)


class VerifyCodeApiView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        email = (request.data.get("email") or "").strip()
        # normalize code: strip spaces and ensure string compare
        raw_code = request.data.get("code")
        code = str(raw_code).strip().replace(" ", "") if raw_code is not None else ""

        if not email or not code:
            return Response({"error": "Email and code are required."}, status=400)

        cached_code = cache.get(f"email_code:{email}")
        if isinstance(cached_code, (bytes, bytearray)):
            cached_code = cached_code.decode()
        if cached_code != code:
            return Response({"error": "Invalid or expired code."}, status=400)

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=404)

        cache.delete(f"email_code:{email}")
        user.is_confirmed = True
        user.save()

        refresh = RefreshToken.for_user(user)

        return Response({
            "status": "authenticated",
            "data": {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "tel": user.tel,
                }
            }
        }, status=200)


class SignUpApiView(APIView):
    authentication_classes = []
    permission_classes = []

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip

    def post(self, request):
        ip = self.get_client_ip(request)
        serializer = SignUpSerializer(data={**request.data, 'ip': ip})
        if serializer.is_valid():
            user = serializer.save()
            return Response({
                "status": "success",
            }, status=status.HTTP_201_CREATED)
        else:
            print("SIGNUP ERRORS:", serializer.errors)
            return Response({
                "status": "error",
                "errors": format_errors(serializer.errors),
            }, status=status.HTTP_400_BAD_REQUEST)


class PasswordResetRequestView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        email = request.data.get("email")
        if not email:
            return Response({"message": "Email is required."}, status=400)

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"message": "User not found."}, status=404)

        code = str(random.randint(100000, 999999))
        cache.set(f"reset_code:{email}", code, timeout=600)  # 10 минут

        send_template_email(
            subject="Password Reset Code",
            template_name="verify_email.html",
            context={
                "code": code, "message": "To reset your password, please use the 6-digit code below:"},
            recipient_list=[email],
        )

        return Response({"status": "success", "message": "Code sent to email."}, status=200)


class PasswordResetVerifyView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        email = (request.data.get("email") or "").strip()
        raw_code = request.data.get("code")
        code = str(raw_code).strip().replace(" ", "") if raw_code is not None else ""

        if not email or not code:
            return Response({"message": "Email and code are required."}, status=400)

        cached_code = cache.get(f"reset_code:{email}")
        if isinstance(cached_code, (bytes, bytearray)):
            cached_code = cached_code.decode()
        if cached_code != code:
            return Response({"message": "Invalid or expired code."}, status=400)

        return Response({"status": "success", "message": "Code verified."}, status=200)


class PasswordResetCompleteView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        email = (request.data.get("email") or "").strip()
        raw_code = request.data.get("code")
        code = str(raw_code).strip().replace(" ", "") if raw_code is not None else ""
        password = request.data.get("password")

        if not email or not code or not password:
            return Response({"message": "Email, code, and new password are required."}, status=400)

        cached_code = cache.get(f"reset_code:{email}")
        if isinstance(cached_code, (bytes, bytearray)):
            cached_code = cached_code.decode()
        if cached_code != code:
            return Response({"message": "Invalid or expired code."}, status=400)

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"message": "User not found."}, status=404)

        user.password = make_password(password)
        user.save()
        cache.delete(f"reset_code:{email}")

        return Response({"status": "success", "message": "Password changed successfully."}, status=200)


class UserProfileView(APIView):
    def get(self, request):
        user = ProfileSerializer(request.user).data
        subscription = (UserSubscription.objects
                         .select_related("plan", "usage", "user")
                         .filter(user=request.user)
                         .order_by("-start_date")
                         .first())

        if subscription:
            subscription = UserSubscriptionSerializer(subscription).data
        else:
            subscription = None

        if request.user.last4 and request.user.card_holder:
            card = {
                'last4': request.user.last4 or None,
                'card_holder': request.user.card_holder or None,
                'exp_month': request.user.exp_month or None,
                'exp_year': request.user.exp_year or None,
            }
        else:
            card = None

        responseData = {
            'user': user,
            'subscription': subscription,
            'card': card,
        }

        return Response(responseData, status=200)

    def put(self, request):

        changed = False
        tel = request.data.get('tel', None)
        first_name = request.data.get('first_name', None)
        _2fa = request.data.get('_2fa', None)

        if tel:
            request.user.tel = tel
            changed = True
        if first_name:
            request.user.first_name = first_name
            changed = True
        if _2fa == False or _2fa == True:
            request.user._2fa = _2fa
            changed = True

        if changed:
            request.user.save()

        return Response({}, status=200)


class QuestionAPIView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        # accept alias "message" for "question"
        data = request.data.copy()
        if "question" not in data and "message" in data:
            data["question"] = data["message"]

        serializer = UserQuestionSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        obj = serializer.save()
        return Response({"id": obj.id}, status=status.HTTP_201_CREATED)
    

class NotificationListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = NotificationDeliverySerializer

    def get_queryset(self):
        user = self.request.user
        qs = (
            NotificationDelivery.objects
            .filter(recipient=user, notification__created_at__gte=user.date_joined)
            .select_related("notification")
        )
        if self.request.query_params.get("unread") == "1":
            qs = qs.filter(is_read=False)
        return qs.order_by("-assigned_at")


class NotificationMarkReadView(generics.UpdateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = NotificationDeliverySerializer
    lookup_url_kwarg = "pk"

    def get_queryset(self):
        user = self.request.user
        return (
            NotificationDelivery.objects
            .filter(recipient=user, notification__created_at__gte=user.date_joined)
            .select_related("notification")
        )

    def get_object(self):
        qs = self.get_queryset()
        pk = self.kwargs.get(self.lookup_url_kwarg)
        # Accept either delivery id or notification id for convenience
        try:
            return qs.get(pk=pk)
        except NotificationDelivery.DoesNotExist:
            obj = qs.filter(notification_id=pk).order_by('-assigned_at').first()
            if not obj:
                raise NotFound("Notification not found for this user")
            return obj

    def _mark(self, request, *args, **kwargs):
        delivery = self.get_object()
        delivery.mark_read()
        serializer = self.get_serializer(delivery)
        return Response(serializer.data, status=200)

    def patch(self, request, *args, **kwargs):
        return self._mark(request, *args, **kwargs)


class FeedbackView(APIView):
    """POST to submit feedback by authenticated users; GET list for admins."""

    def get_permissions(self):
        if self.request.method == "GET":
            return [permissions.IsAdminUser()]
        return [permissions.IsAuthenticated()]

    def post(self, request):
        serializer = UserFeedbackSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            obj = serializer.save()
            return Response({"status": "success", "id": obj.id}, status=201)
        return Response({"status": "error", "errors": serializer.errors}, status=400)

    def get(self, request):
        # Admin-only list
        from .models import UserFeedback
        qs = UserFeedback.objects.all()
        return Response(UserFeedbackSerializer(qs, many=True).data, status=200)

    def put(self, request, *args, **kwargs):
        return self._mark(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        return self._mark(request, *args, **kwargs)


class BindCardView(APIView):
    authentication_classes = [JWTAuthentication]
    """Bind FreedomPay tokenized card to the current user (без сохранения PAN).

    Expected JSON:
    - token: string (FreedomPay token from JS SDK tokenize)
    - brand: string (optional, e.g., VISA/MASTERCARD)
    - last4: string (optional last 4 digits)
    - exp_month: int (optional)
    - exp_year: int (optional, 2- or 4-digit)
    - card_holder: string (optional)
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        data = request.data or {}
        token = (data.get("token") or "").strip()
        if not token:
            return Response({"message": "token is required"}, status=400)

        # Optional metadata to show in profile
        brand = (data.get("brand") or "").strip() or None
        last4 = (data.get("last4") or "").strip() or None
        exp_month = data.get("exp_month")
        exp_year = data.get("exp_year")
        holder = (data.get("card_holder") or "").strip() or None

        # Normalize year and month
        try:
            if isinstance(exp_year, str) and exp_year.isdigit():
                exp_year = int(exp_year)
            if isinstance(exp_month, str) and exp_month.isdigit():
                exp_month = int(exp_month)
        except Exception:
            pass

        u: User = request.user
        # Prepare values for DB update (bypass model.save extra queries)
        values = {
            "pay_token": token[:1024],
            "brand": (brand or None)[:20] if brand else None,
            "last4": last4[-4:] if last4 else u.last4,
            "card_holder": (holder or None)[:100] if holder else None,
        }
        if isinstance(exp_month, int):
            values["exp_month"] = exp_month
        if isinstance(exp_year, int):
            values["exp_year"] = (2000 + exp_year) if 0 <= exp_year < 100 else exp_year

        try:
            User.objects.filter(pk=u.pk).update(**values)
        except DBDataError:
            # Rollback broken transaction and retry with conservative lengths
            try:
                connection.rollback()
            except Exception:
                pass
            if values.get("pay_token") and len(values["pay_token"]) > 100:
                values["pay_token"] = values["pay_token"][:100]
            if values.get("brand") and len(values["brand"]) > 20:
                values["brand"] = values["brand"][:20]
            if values.get("card_holder") and len(values["card_holder"]) > 100:
                values["card_holder"] = values["card_holder"][:100]
            User.objects.filter(pk=u.pk).update(**values)

        # Refresh in-memory fields from updated values
        for k, v in values.items():
            setattr(u, k, v)

        return Response({
            "status": "ok",
            "card": {
                "last4": u.last4,
                "card_holder": u.card_holder,
                "exp_month": u.exp_month,
                "exp_year": u.exp_year,
            }
        }, status=200)


class UnbindCardView(APIView):
    authentication_classes = [JWTAuthentication]
    """Clear saved FreedomPay token and public card meta for the user."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        u: User = request.user
        u.pay_token = None
        u.brand = None
        u.last4 = None
        u.card_holder = None
        u.exp_month = None
        u.exp_year = None
        u.save()
        return Response({"status": "ok"}, status=200)

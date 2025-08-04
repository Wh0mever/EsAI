import random
from django.core.cache import cache
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from .serializers import SignUpSerializer, SignInSerializer, ProfileSerializer
from core.format import format_errors
from mails.sender import send_template_email
from django.contrib.auth.hashers import make_password
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView
from .models import User
from plans.models import UserSubscription
from plans.serializers import UserSubscribeSerializer
import json


class SigninApiView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = SignInSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data['user']
            email = user['email']

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
        email = request.data.get("email")
        code = request.data.get("code")

        if not email or not code:
            return Response({"error": "Email and code are required."}, status=400)

        cached_code = cache.get(f"email_code:{email}")
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
        email = request.data.get("email")
        code = request.data.get("code")

        if not email or not code:
            return Response({"message": "Email and code are required."}, status=400)

        cached_code = cache.get(f"reset_code:{email}")
        if cached_code != code:
            return Response({"message": "Invalid or expired code."}, status=400)

        return Response({"status": "success", "message": "Code verified."}, status=200)


class PasswordResetCompleteView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        email = request.data.get("email")
        code = request.data.get("code")
        password = request.data.get("password")

        if not email or not code or not password:
            return Response({"message": "Email, code, and new password are required."}, status=400)

        cached_code = cache.get(f"reset_code:{email}")
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
        plan = UserSubscription.objects.filter(user=request.user)
        
        if plan.exists():
            plan = UserSubscribeSerializer(plan, many=True).data
        else:
            plan = False
        
        responseData = json.dumps({
            'user': user,
            'plan': plan
        })
        return Response(responseData, status=200)
    
    def put(self, request):
        
        tel = request.data.get('tel', None)
        first_name = request.data.get('first_name', None)

        if tel:
            request.user.tel = tel
        if first_name:
            request.user.first_name = first_name
        if tel or first_name:
            request.user.save()
        
        return Response({}, status=200) 
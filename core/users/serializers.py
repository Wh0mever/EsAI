# users/serializers.py
from .models import User
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken

class SignUpSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    tel = serializers.CharField(max_length=20)
    password = serializers.CharField(write_only=True)
    password_repeat = serializers.CharField(write_only=True)

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("Имя не может быть пустым.")
        return value
    
    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Пользователь с таким email уже существует.")
        return value
    
    def validate_tel(self, value):
        if User.objects.filter(tel=value).exists():
            raise serializers.ValidationError("Пользователь с таким номером телефона уже существует.")
        return value
    
    def validate_ip(self, value):
        if not value:
            raise serializers.ValidationError("IP адрес обязателен.")
        return value

    def validate(self, data):
        if data['password'] != data['password_repeat']:
            raise serializers.ValidationError("Пароли не совпадают.")
        if len(data['password']) < 8:
            raise serializers.ValidationError("Пароль должен быть не менее 8 символов.")
        if not any(char.isdigit() for char in data['password']):
            raise serializers.ValidationError("Пароль должен содержать хотя бы одну цифру.")
        if not any(char.isalpha() for char in data['password']):
            raise serializers.ValidationError("Пароль должен содержать хотя бы одну букву.")
        return data

    def create(self, validated_data):
        user = User.objects.create_user(
            email=validated_data["email"],
            tel=validated_data["tel"],
            password=validated_data["password"],
            first_name=validated_data["name"],
            ip=validated_data.get("ip")
        )
        return user




class SignInSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False)
    tel = serializers.CharField(required=False)
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        email = data.get("email")
        tel = data.get("tel")
        password = data.get("password")

        user = None
        if email:
            user = authenticate(email=email, password=password)
        elif tel:
            user = authenticate(tel=tel, password=password)

        if not user:
            raise serializers.ValidationError("Неверные учетные данные")

        refresh = RefreshToken.for_user(user)

        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": {
                "id": user.id,
                "email": user.email,
                "tel": user.tel,
            }
        }
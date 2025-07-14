from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from .serializers import SignUpSerializer, SignInSerializer
from core.format import format_errors

class SigninApiView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = SignInSerializer(data=request.data)
        if serializer.is_valid():
            return Response({
                "status": "success",
                "data": serializer.validated_data,
                }, status=status.HTTP_200_OK)
        return Response({
            "status": "error",
            "errors": format_errors(serializer.errors),
        }, status=status.HTTP_400_BAD_REQUEST)


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
            return Response({
                "status": "error",
                "errors": format_errors(serializer.errors),
            }, status=status.HTTP_400_BAD_REQUEST)


class SignOutApiView(APIView):
    def get(self, request):
        return Response({'message': 'Hello, World!'})

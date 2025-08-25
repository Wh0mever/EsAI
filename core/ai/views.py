from openai import OpenAI
from typing import Any, List, Optional
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.pagination import LimitOffsetPagination
from rest_framework_simplejwt.authentication import JWTAuthentication
from .handlers import OpenAIHandler
from .pagination import MessagesPaginator
from django.shortcuts import get_object_or_404
from .models import AiProvider, AiChatSession, AiChatMessage, AiPromptTemplate, AiPromptTemplateFavorite
from .serializers import (
    AiChatSessionListSerializer,
    AiChatSessionMetaSerializer,
    AiChatMessageSerializer,
    AiPromptTemplateSerializer
)
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt


class ChatGptAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        response = OpenAIHandler(request)
        return Response(
            response,
            status=200 if isinstance(
                response, dict) and "error" not in response else 400
        )


class ChatSessionListAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (
            AiChatSession.objects
            .filter(user=request.user)
            .order_by("-updated_at")
            .prefetch_related("messages")
        )
        data = AiChatSessionListSerializer(qs, many=True).data
        return Response(data)


class ChatSessionDetailAPIView(APIView, LimitOffsetPagination):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    default_limit = 30

    def get(self, request, session_id: int):
        session = (
            AiChatSession.objects
            .filter(id=session_id, user=request.user)
            .first()
        )
        if not session:
            return Response({"error": "Session not found"}, status=404)

        messages_qs = session.messages.order_by("created_at")
        page = self.paginate_queryset(messages_qs, request, view=self)
        messages = AiChatMessageSerializer(page, many=True).data
        payload = {
            "id": session.id,
            "title": session.title,
            "provider_id": session.provider_id,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "is_active": session.is_active,
            "messages": messages,
        }
        return self.get_paginated_response(payload)


class AiTemplatesApiView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        personal_data = []
        
        global_queryset = AiPromptTemplate.objects.filter(
            is_public=True, is_active=True)
        global_data = AiPromptTemplateSerializer(
            global_queryset, many=True).data
        
        if request.user.is_authenticated:
            personal_queryset = AiPromptTemplate.objects.filter(
                is_public=False, is_active=True, created_by=request.user
            )
            personal_data = AiPromptTemplateSerializer(
            personal_queryset, many=True).data

        return Response(
            data={
                "global": global_data,
                "personal": personal_data, },
            status=200
        )


@method_decorator(csrf_exempt, name="dispatch")  # disable CSRF for this view
class AiTemplatesFavoriteApiView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        template_id = request.data.get("templateId")
        favorite = bool(request.data.get("favorite", False))
        # TODO: persist favorite for user
        return Response({"templateId": template_id, "favorite": favorite})

    def get(self, request):
        return Response({"detail": "OK"})
    
    
class ChatSessionDetailAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    paginator = MessagesPaginator()

    def get(self, request, session_id: int):
        session = get_object_or_404(AiChatSession, id=session_id, user=request.user)

        order = request.query_params.get("order", "asc")
        qs = session.messages.all()
        qs = qs.order_by("created_at") if order == "asc" else qs.order_by("-created_at")

        page = self.paginator.paginate_queryset(qs, request, view=self)
        # UI обычно хочет хронологию ↑, даже если пагинируем по desc
        if order != "asc":
            page = list(reversed(page))

        messages_data = AiChatMessageSerializer(page, many=True).data
        session_payload = AiChatSessionMetaSerializer(session).data

        return self.paginator.get_paginated_response(messages_data, session_payload)
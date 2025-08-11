from openai import OpenAI
from typing import Any, List, Optional
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.pagination import LimitOffsetPagination
from rest_framework_simplejwt.authentication import JWTAuthentication
from .handlers import OpenAIHandler
from .models import AiProvider, AiChatSession, AiChatMessage, AiPromptTemplate, AiPromptTemplateFavorite
from .serializers import (
    AiChatSessionListSerializer,
    AiChatSessionDetailSerializer,
    AiChatMessageSerializer,
    AiPromptTemplateSerializer
)



class ChatGptAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        response = OpenAIHandler(request)
        print("OpenAIHandler response:", response)
        return Response(
            response,
            status=200 if isinstance(response, dict) and "error" not in response else 400
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
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        global_queryset = AiPromptTemplate.objects.filter(
            is_public=True, is_active=True)
        personal_queryset = AiPromptTemplate.objects.filter(
            is_public=False, is_active=True, created_by=request.user
        )
        global_data = AiPromptTemplateSerializer(
            global_queryset, many=True).data
        personal_data = AiPromptTemplateSerializer(
            personal_queryset, many=True).data

        return Response(
            data={
                "global": global_data,
                "personal": personal_data, },
            status=200
        )
        
    
class AiTemplatesFavoriteApiView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        template_id = request.data.get("templateId")
        favorite = request.data.get("favorite", False)

        pass
        
    def get(self, request):
        pass

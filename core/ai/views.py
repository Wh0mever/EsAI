from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.permissions import IsAuthenticated
from .models import AiProvider, AiPromptTemplate
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam
from .serializers import AiPromptTemplateSerializer



class ChatGptAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        message = request.data.get("message")
        if not message:
            return Response({"error": "No message provided"}, status=400)

        try:
            token = AiProvider.objects.get(slug="gpt").token
            client = OpenAI(api_key=token)

            messages: list[ChatCompletionMessageParam] = [
                {
                    "role": "system",
                    "content": "Говори как пират, но на русском языке",
                },
                {
                    "role": "user",
                    "content": message,
                },
            ]

            response = client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                temperature=0.7,
                max_tokens=1000,
                top_p=1,
            )

            answer = response.choices[0].message.content
            return Response({"response": answer})

        except Exception as e:
            print("ChatGPT error:", e)
            return Response({"error": str(e)}, status=500)


class AiTemplatesApiView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        queryset = AiPromptTemplate.objects.filter(is_public=True, is_active=True)
        data = AiPromptTemplateSerializer(queryset, many=True).data

        return Response(
            data=data,
            status=200
        )
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import BlogPost
from .serializers import BlogPostSerializer
from django.shortcuts import get_object_or_404


def get_language_from_request(request):
    lang_header = request.headers.get('Accept-Language', '')
    if lang_header:
        return lang_header.split(',')[0].split('-')[0].lower()
    return 'ru'


class BlogPostListAPIView(APIView):
    def get(self, request):
        lang = get_language_from_request(request)
        posts = BlogPost.objects.all().order_by('-created_at')
        serializer = BlogPostSerializer(posts, many=True, context={'lang': lang})
        return Response(serializer.data, status=status.HTTP_200_OK)


class BlogPostDetailAPIView(APIView):
    def get(self, request, pk):
        lang = get_language_from_request(request)
        post = get_object_or_404(BlogPost, pk=pk)
        serializer = BlogPostSerializer(post, context={'lang': lang})
        return Response(serializer.data, status=status.HTTP_200_OK)

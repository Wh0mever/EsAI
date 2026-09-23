from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from django.shortcuts import get_object_or_404

from .models import BlogPost, SiteSettings, PageSeo
from .serializers import (
    BlogPostSerializer,
    ArticleListSerializer,
    ArticleDetailSerializer,
    SiteSettingsSerializer,
    PageSeoSerializer,
)


class BlogPostListAPIView(APIView):

    authentication_classes = []
    permission_classes = []

    def get(self, request):
        # Только опубликованные: черновики из админки уходили в открытый API
        # раньше, чем их выпустят на сайт.
        posts = BlogPost.objects.filter(is_published=True).order_by('-created_at')
        serializer = BlogPostSerializer(posts, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ArticleListAPIView(ListAPIView):
    """GET /api/content/articles/ — список опубликованных статей."""
    authentication_classes = []
    permission_classes = []
    serializer_class = ArticleListSerializer

    def get_queryset(self):
        return BlogPost.objects.filter(is_published=True).order_by('-published_at', '-created_at')


class ArticleDetailAPIView(RetrieveAPIView):
    """GET /api/content/articles/<slug>/ — опубликованная статья детально."""
    authentication_classes = []
    permission_classes = []
    serializer_class = ArticleDetailSerializer
    lookup_field = 'slug'

    def get_queryset(self):
        return BlogPost.objects.filter(is_published=True)


class SiteSettingsAPIView(APIView):
    """GET /api/content/site-settings/ — глобальные настройки сайта."""
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        settings_obj = SiteSettings.get_solo()
        serializer = SiteSettingsSerializer(settings_obj)
        return Response(serializer.data, status=status.HTTP_200_OK)


class PageSeoAPIView(APIView):
    """GET /api/content/page-seo/?path=<path> — SEO для пути."""
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        path = request.query_params.get('path')
        if not path:
            return Response(
                {'detail': 'Query param "path" is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        seo = get_object_or_404(PageSeo, path=path)
        serializer = PageSeoSerializer(seo)
        return Response(serializer.data, status=status.HTTP_200_OK)

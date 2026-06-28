from django.urls import path
from .views import (
    BlogPostListAPIView,
    ArticleListAPIView,
    ArticleDetailAPIView,
    SiteSettingsAPIView,
    PageSeoAPIView,
)

urlpatterns = [
    path('blog/', BlogPostListAPIView.as_view(), name='blog-list'),
    path('articles/', ArticleListAPIView.as_view(), name='article-list'),
    path('articles/<slug:slug>/', ArticleDetailAPIView.as_view(), name='article-detail'),
    path('site-settings/', SiteSettingsAPIView.as_view(), name='site-settings'),
    path('page-seo/', PageSeoAPIView.as_view(), name='page-seo'),
]

from django.urls import path
from .views import BlogPostListAPIView, BlogPostDetailAPIView

urlpatterns = [
    path('blog/', BlogPostListAPIView.as_view(), name='blog-list'),
    path('blog/<int:pk>/', BlogPostDetailAPIView.as_view(), name='blog-detail'),
]

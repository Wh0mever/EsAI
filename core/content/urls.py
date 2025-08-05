from django.urls import path
from .views import BlogPostListAPIView

urlpatterns = [
    path('blog/', BlogPostListAPIView.as_view(), name='blog-list'),
]

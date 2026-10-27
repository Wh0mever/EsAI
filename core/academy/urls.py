from django.urls import path

from . import views

app_name = "academy"

urlpatterns = [
    path("courses/", views.CoursesView.as_view(), name="courses"),
]

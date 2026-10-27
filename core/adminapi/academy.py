"""EsAI Академия в панели: курсы со ссылками на сайты авторов и ссылка «Предложить курс».

  GET    academy/courses/              все курсы в порядке сайта, ссылка кнопки, границы полей
  POST   academy/courses/              новый черновик (JSON)
  POST   academy/courses/order/        новый порядок всех курсов {ids}
  GET    academy/courses/<id>/         один курс
  PATCH  academy/courses/<id>/         поправить, опубликовать, скрыть
  DELETE academy/courses/<id>/         удалить
  POST   academy/courses/<id>/cover/   обложка (multipart, file)
  GET    academy/settings/             {suggest_url}
  PATCH  academy/settings/             {suggest_url}: @имя, t.me/…, https://… или пусто

Любой сотрудник, как остальная панель (только главному администратору можно
отдать позже — IsSuperuser). Проверка полей и ссылок, журнал действий и
обложки — в academy.panel; здесь только разбор запроса и форма ответа.
Контракт — vstudio2-notes/pricing/CONTRACT_ACADEMY.md.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from academy import panel, public

from .views import StaffAPIView


def _body(request) -> dict:
    data = getattr(request, "data", None)
    return data if hasattr(data, "get") else {}


class AcademyCoursesView(StaffAPIView):
    """GET — все курсы и всё, что нужно форме; POST — новый черновик."""

    def get(self, request):
        return Response(panel.list_payload())

    def post(self, request):
        course = panel.create_course(_body(request), actor=request.user, request=request)
        return Response(panel.course_row(course), status=status.HTTP_201_CREATED)


class AcademyCourseView(StaffAPIView):
    """GET — один курс; PATCH — поправить (is_published — публикация); DELETE — удалить."""

    def get(self, request, pk):
        return Response(panel.course_row(panel.get_course(pk)))

    def patch(self, request, pk):
        course = panel.edit_course(pk, _body(request), actor=request.user, request=request)
        return Response(panel.course_row(course))

    def delete(self, request, pk):
        panel.delete_course(pk, actor=request.user, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AcademyCourseCoverView(StaffAPIView):
    """POST multipart file=<картинка> — новая обложка, синхронно."""

    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        course = panel.upload_cover(pk, request.FILES, actor=request.user, request=request)
        return Response(panel.course_row(course))


class AcademyCourseOrderView(StaffAPIView):
    """POST {ids: [...]} — все курсы в новом порядке."""

    def post(self, request):
        courses = panel.reorder(_body(request), actor=request.user, request=request)
        return Response({"results": panel.course_rows(courses)})


class AcademySettingsView(StaffAPIView):
    """GET / PATCH {suggest_url} — ссылка кнопки «Предложить курс»; пусто — кнопки нет."""

    def get(self, request):
        return Response({"suggest_url": public.suggest_url()})

    def patch(self, request):
        value = panel.set_suggest_url(_body(request), actor=request.user, request=request)
        return Response({"suggest_url": value})

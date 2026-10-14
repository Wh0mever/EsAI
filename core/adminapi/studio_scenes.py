"""Сцены мультстудии в панели: библиотека, которую владелец ведёт сам.

  GET    studio/scenes/?section=&audience=&published=&pick=&q=   сцены, разделы, справочники
  POST   studio/scenes/                                           новая сцена (JSON)
  GET    studio/scenes/<id>/                                      одна сцена (опрос сборки превью)
  PATCH  studio/scenes/<id>/                                      поправить, опубликовать, снять
  DELETE studio/scenes/<id>/                                      удалить, если её никто не взял
  POST   studio/scenes/<id>/preview/                              ролик превью (multipart, file)
  POST   studio/scenes/<id>/preview/rebuild/                      собрать копии превью заново
  GET    studio/sections/                                         разделы библиотеки
  POST   studio/sections/                                         новый раздел
  PATCH  studio/sections/<id>/                                    поправить, порядок, скрыть

Только staff. Проверка полей, журнал действий и сборка превью — в
cartoon.panel; здесь только разбор запроса и форма ответа. Отказы — телом
{"detail": "<текст>"}, как у остальной панели.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from cartoon import panel

from .views import StaffAPIView


def _body(request) -> dict:
    data = getattr(request, "data", None)
    return data if hasattr(data, "get") else {}


def _sections_payload() -> dict:
    return {
        "sections": panel.sections_rows(),
        "audiences": [{"key": key, "label": label} for key, label in panel.AUDIENCES],
        "aspects": list(panel.STUDIO_ASPECTS),
        "limits": panel.limits(),
    }


class StudioScenesView(StaffAPIView):
    """GET — сцены библиотеки с фильтрами и всё, что нужно форме; POST — новая сцена."""

    def get(self, request):
        qs = panel.filter_scenes(panel.scenes_qs(), request.query_params)
        results = panel.scene_rows(qs)
        return Response({"count": len(results), "results": results, **_sections_payload()})

    def post(self, request):
        preset = panel.create_scene(_body(request), actor=request.user, request=request)
        return Response(panel.scene_row(panel.get_scene(preset.pk)),
                        status=status.HTTP_201_CREATED)


class StudioSceneView(StaffAPIView):
    """GET — одна сцена; PATCH — поправить (is_active — публикация); DELETE — удалить."""

    def get(self, request, pk):
        return Response(panel.scene_row(panel.get_scene(pk)))

    def patch(self, request, pk):
        preset = panel.edit_scene(panel.get_scene(pk), _body(request), actor=request.user,
                                  request=request)
        return Response(panel.scene_row(preset))

    def delete(self, request, pk):
        panel.delete_scene(panel.get_scene(pk), actor=request.user, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class StudioScenePreviewView(StaffAPIView):
    """POST multipart file=<mp4> — новый ролик превью; копии собираются в фоне."""

    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        preset = panel.upload_preview(panel.get_scene(pk), request.FILES.get("file"),
                                      actor=request.user, request=request)
        return Response(panel.scene_row(panel.get_scene(preset.pk)),
                        status=status.HTTP_202_ACCEPTED)


class StudioScenePreviewRebuildView(StaffAPIView):
    """POST — собрать лёгкую копию, обложку и миниатюру заново из текущего ролика."""

    def post(self, request, pk):
        preset = panel.rebuild_preview(panel.get_scene(pk))
        return Response(panel.scene_row(preset), status=status.HTTP_202_ACCEPTED)


class StudioSectionsView(StaffAPIView):
    """GET — разделы (и скрытые); POST — новый раздел."""

    def get(self, request):
        return Response({"results": panel.sections_rows()})

    def post(self, request):
        section = panel.create_section(_body(request), actor=request.user, request=request)
        return Response(_section(section.pk), status=status.HTTP_201_CREATED)


class StudioSectionView(StaffAPIView):
    """PATCH — название, значок, порядок, показ. Удаления нет: раздел скрывают."""

    def patch(self, request, pk):
        section = panel.edit_section(panel.get_section(pk), _body(request), actor=request.user,
                                     request=request)
        return Response(_section(section.pk))


def _section(pk) -> dict:
    # Строка со счётчиками сцен — та же, что в списке.
    return next(row for row in panel.sections_rows() if row["id"] == pk)

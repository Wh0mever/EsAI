"""Общие заготовки тестов склейки: источники всех видов с файлами на диске.

Файлы пишутся во временный MEDIA_ROOT (MediaTestCase), ffprobe и ffmpeg
подменены: проверяем права, деньги и состояния, а не кодек.
"""
from __future__ import annotations

import itertools
import shutil
import tempfile
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from ai.models import GenerationLog, GPTModels
from cartoon.models import CartoonPreset, CartoonProject, CartoonScene
from merge.models import MergeProject
from merge.render import Probe
from vstudio.models import Asset, Take
from vstudio.tests.factories import make_asset, make_shot, make_take, make_user

_seq = itertools.count(1)


def probe_ok(duration: float = 5.0, width: int = 1280, height: int = 720, audio: bool = True):
    return Probe(duration=duration, width=width, height=height, audio=audio, video=True)


def client_for(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.force_authenticate(user)
    return client


def store(name: str, blob: bytes = b"\x00\x00\x00\x18ftypmp42") -> str:
    return default_storage.save(name, ContentFile(blob))


class MediaTestCase(TestCase):
    """Временный MEDIA_ROOT, чистый кэш, ffprobe отвечает «5 с, 1280×720, со звуком»."""

    durations: dict = {}

    def setUp(self):
        super().setUp()
        self._media = tempfile.mkdtemp(prefix="merge-test-")
        media = override_settings(MEDIA_ROOT=self._media)
        media.enable()
        self.addCleanup(media.disable)
        self.addCleanup(shutil.rmtree, self._media, True)
        cache.clear()
        self.durations = {}
        patcher = patch("merge.render.probe", side_effect=self._probe)
        self.probe = patcher.start()
        self.addCleanup(patcher.stop)

    def _probe(self, path):
        for name, value in self.durations.items():
            if str(path).replace("\\", "/").endswith(name):
                return None if value is None else probe_ok(value)
        return probe_ok()

    # ------------------------------------------------------------ источники

    def user(self, balance: int = 500, **kw):
        return make_user(balance=balance, **kw)

    def take(self, user, *, duration: float = 5.0, status: str = Take.STATUS_DONE,
             with_file: bool = True, deleted: bool = False):
        shot = make_shot(user, prompt="Кот летит над городом на закате")
        asset = make_asset(user, kind=Asset.KIND_VIDEO, source=Asset.SOURCE_GENERATED_VIDEO,
                           width=1280, height=720, duration_s=duration)
        if with_file:
            store(asset.file)
        if deleted:
            from django.utils import timezone

            Asset.objects.filter(pk=asset.pk).update(deleted_at=timezone.now())
        return make_take(shot, status=status, result_asset=asset)

    def _preset(self):
        n = next(_seq)
        image = GPTModels.objects.create(name=f"img{n}", openrouter_id=f"t/img{n}", max_tokens=1,
                                         markup_coefficient=Decimal(1), category="image")
        video = GPTModels.objects.create(name=f"vid{n}", openrouter_id=f"t/vid{n}", max_tokens=1,
                                         markup_coefficient=Decimal(1), category="video")
        return CartoonPreset.objects.create(title="Крыша", title_en="Roof", slug=f"roof-{n}",
                                            scene_prompt="x", image_model=image, video_model=video)

    def movie(self, user, *, status: str = CartoonProject.STATUS_READY, with_file: bool = True):
        name = f"cartoon/movies/m{next(_seq)}.mp4"
        if with_file:
            name = store(name)
        return CartoonProject.objects.create(user=user, title="Мой мультфильм", status=status,
                                             result_video=name)

    def scene(self, user, *, status: str = CartoonScene.STATUS_READY, with_file: bool = True,
              project=None, mixed: bool = False):
        project = project or CartoonProject.objects.create(user=user, title="Про кота")
        name = f"cartoon/videos/s{next(_seq)}.mp4"
        if with_file:
            name = store(name)
        extra = {"mixed_video": store(f"cartoon/mixed/x{next(_seq)}.mp4")} if mixed else {}
        return CartoonScene.objects.create(project=project, preset=self._preset(), status=status,
                                           video=name, keyframe="cartoon/keyframes/k.jpg",
                                           shot_duration=5, **extra)

    def chat(self, user, *, status: str = GenerationLog.STATUS_DELIVERED, source: str = "chat",
             with_file: bool = True):
        name = f"ai_videos/c{next(_seq)}.mp4"
        if with_file:
            name = store(name)
        return GenerationLog.objects.create(user=user, kind=GenerationLog.KIND_VIDEO, source=source,
                                            status=status, model="bytedance/seedance-2.0",
                                            prompt="Закат над морем", params={"duration": 5},
                                            result_url=default_storage.url(name))

    # ------------------------------------------------------------ склейка

    @staticmethod
    def ref(obj) -> dict:
        if isinstance(obj, Take):
            return {"type": "vstudio", "id": obj.uid}
        if isinstance(obj, CartoonScene):
            return {"type": "cartoon_scene", "id": obj.pk}
        if isinstance(obj, CartoonProject):
            return {"type": "cartoon_movie", "id": obj.pk}
        return {"type": "chat", "id": obj.pk}

    def project(self, user, sources=(), **kw) -> MergeProject:
        from merge import services

        items = services.snapshot(services.check_sources(
            user, services.parse_items([self.ref(s) for s in sources]))) if sources else []
        return MergeProject.objects.create(user=user, title="Тест", items=items, **kw)

    def balance(self, user) -> int:
        user.refresh_from_db(fields=["token_balance"])
        return user.token_balance

"""«Озвучить весь мультфильм»: ИИ пишет реплики по сценам и озвучивает их.

Клиент: «нажимаешь одну кнопку — система сама распределяет реплики между
персонажами и озвучивает все сцены; итоговую стоимость показываем до запуска».

Поэтому шага два и они разделены нарочно:
1) план — дешёвый вызов текстовой модели, ничего не стоит человеку; он видит
   реплики, может их поправить и видит общую цену;
2) озвучка — очередь, где каждая реплика оплачивается по факту готового звука.

Голоса закрепляются за персонажами: один герой звучит одинаково во всех сценах
и во всех запусках, иначе мультфильм разваливается на куски.

Здесь же — реплика, которую человек написал сам (дорожка line): голос героя вместо
речи модели. Её озвучивают съёмка (RenderLine), кнопка на карточке (views_audio)
и «озвучить весь мультфильм». Деньги всюду по одному правилу: сначала готовый звук
и сведение, потом одной транзакцией списание и дорожка (LineDraft).
"""
from __future__ import annotations

import json
import logging
import re
import time
from contextlib import nullcontext

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import transaction

from . import audio, director

logger = logging.getLogger(__name__)

MAX_LINE_CHARS = 200
MAX_LINES = 50
# Реплика человека — как в поле сцены: её текст заморожен, обрезать его нельзя.
MAX_SCENE_LINE_CHARS = 300
WORKING_STATES = ("new", "keyframe", "video")
# Сколько сцен просим у модели за один раз: на длинном списке ответ упирается в
# потолок токенов и обрывается на середине JSON.
CHUNK = 12
# Прогресс живёт дольше замка: по нему интерфейс понимает, что озвучка шла.
PROGRESS_TTL = 60 * 30
LOCK_TTL = 300
# Если прогресс не обновлялся столько секунд — считаем, что задача умерла
# (перезапуск воркера, деплой): иначе кнопка висела бы заблокированной.
STALE_AFTER = 180
# Запуск ещё стоит в очереди media (там идут минутные съёмки) — это не обрыв.
# Раньше через три минуты ожидания его объявляли брошенным, кнопка оживала, и
# второй запуск ставил вторую задачу: обе потом озвучивали и обе списывали.
# Замок на время очереди живёт столько же.
QUEUED_STALE_AFTER = 30 * 60


class Superseded(RuntimeError):
    """Запуск перехвачен новым (замок уже чужой) — дальше не озвучиваем и не списываем."""


class SceneMoved(RuntimeError):
    """Пока делался голос, сцену начали переснимать: к этому ролику он уже не относится."""

LANG_NAMES = {"ru": "русском", "en": "английском", "kg": "кыргызском"}

_SYSTEM = (
    "You write dialogue for a short cartoon. You get the scenes in order, each with the "
    "character who appears in it and how many seconds that scene lasts. Write ONE short spoken "
    "line per scene, said by that scene's character, so that all lines together tell one simple, "
    "warm, kid-friendly story.\n"
    "Rules: each line must fit being said aloud within that scene's duration (about 13 characters "
    "per second, never more than the limit given for the scene); spoken words only — no names, no "
    "quotes, no stage directions, no emoji, no narration about what is happening; keep each "
    "character's voice consistent.\n"
    "Write the lines in {language} (the language of the scene descriptions).\n"
    'Return JSON only: {{"lines": [{{"n": 1, "text": "..."}}]}} with exactly one entry per scene, '
    "using the scene numbers given."
)


class PlanFailed(RuntimeError):
    """Модель не смогла написать реплики. Текст — для лога."""


class NoVoices(RuntimeError):
    """Справочник голосов пуст или недоступен — озвучивать нечем."""


# ------------------------------------------------------------- прогресс ---

def progress_key(project_id: int) -> str:
    return f"studio:voiceall:{project_id}"


def lock_key(project_id: int) -> str:
    return f"studio:voiceall:lock:{project_id}"


def get_progress(project_id: int) -> dict | None:
    return cache.get(progress_key(project_id))


def set_progress(project_id: int, **fields) -> dict:
    """Обновить прогресс и заодно отметить, что задача жива."""
    state = cache.get(progress_key(project_id)) or {"done": 0, "total": 0, "error": "", "spent": 0}
    state.update(fields)
    state["at"] = time.time()
    cache.set(progress_key(project_id), state, PROGRESS_TTL)
    return state


def clear_progress(project_id: int) -> None:
    cache.delete(progress_key(project_id))


def is_stale(state: dict | None) -> bool:
    """Прогресс есть, но давно не обновлялся: задачу убили на середине."""
    if not state or state.get("finished"):
        return False
    limit = QUEUED_STALE_AFTER if state.get("queued") else STALE_AFTER
    return (time.time() - float(state.get("at") or 0)) > limit


def lock_owned(project_id: int, token: str = "") -> bool:
    """Замок всё ещё у этого запуска. Без токена (старые вызовы) — считаем, что да."""
    return not token or cache.get(lock_key(project_id)) == token


def touch_lock(project_id: int, token: str = "") -> None:
    """Продлить замок запуска, пока задача действительно работает. Только свой."""
    value = cache.get(lock_key(project_id))
    if value and (not token or value == token):
        cache.set(lock_key(project_id), value, LOCK_TTL)


# ------------------------------------------------------------- план ------

def _scene_hero(scene):
    return scene.character or scene.project.character


def scene_label(scene) -> str:
    """Чем сцена является для сценариста: название из библиотеки или своё описание."""
    if scene.custom_text:
        return (scene.custom_title or scene.custom_text)[:200]
    return (scene.preset.title if scene.preset_id else "")[:200]


def scene_seconds(scene) -> int:
    """Сколько секунд длится сцена — под это мерится длина реплики.

    Снятая или запущенная — по снимку «Снять», остальные — по доку (своя
    длительность сцены, мультфильма или пресета): реплика на 5 с в сцене на 15 с
    звучала бы обрывком, а на 15 с в пятисекундной — не влезала бы.
    """
    from .pricing import MAX_DURATION, scene_duration

    try:
        seconds = scene_duration(scene)
    except Exception:
        logger.exception("реплики: длительность сцены %s не выяснилась, беру пресет", scene.pk)
        seconds = getattr(scene.preset, "duration", 5)
    return max(3, min(MAX_DURATION, int(seconds or 5)))


def known_voices(project) -> dict:
    """Голоса, которыми этого героя уже озвучивали в этом мультфильме.

    Герой обязан звучать одинаково: и между сценами, и когда человек нажмёт
    «озвучить весь мультфильм» во второй раз. Закреплённый голос (hero_voices)
    важнее последней дорожки: его выбрал человек.
    """
    from .models import CartoonAudioTrack

    out = {}
    for key, value in (project.hero_voices or {}).items():
        if str(key).isdigit() and isinstance(value, dict) and value.get("voice_id"):
            out[int(key)] = {"voice_id": value["voice_id"], "voice_name": value.get("voice_name", "")}
    tracks = (CartoonAudioTrack.objects
              .filter(scene__project=project,
                      kind__in=(CartoonAudioTrack.KIND_VOICE, CartoonAudioTrack.KIND_LINE))
              .exclude(voice_id="").exclude(character__isnull=True)
              .order_by("-id").values("character_id", "voice_id", "voice_name"))
    for t in tracks:
        out.setdefault(t["character_id"], {"voice_id": t["voice_id"], "voice_name": t["voice_name"]})
    return out


# Возраст из подсказки режиссёра → начало метки голоса в каталоге ElevenLabs
# (young, middle_aged, old). Детских голосов в каталоге нет: ребёнку — молодой.
_AGE_LABELS = {"child": "young", "young": "young", "adult": "middle", "old": "old"}
# Описание героя пишется по-английски (модель CartoonCharacter), но бывает и по-русски.
_FEMALE = re.compile(r"\b(?:girl|woman|lady|princess|queen|bride|mother|mom|mum|grandma|grandmother|"
                     r"sister|daughter|aunt|female|девочк\w*|девушк\w*|женщин\w*|бабушк\w*|мама|принцесс\w*)\b",
                     re.I)
_MALE = re.compile(r"\b(?:boy|man|guy|gentleman|prince|king|groom|father|dad|grandpa|grandfather|"
                   r"brother|son|uncle|male|мальчик\w*|парень|мужчин\w*|дедушк\w*|папа|принц(?!есс)\w*)\b", re.I)
_CHILD = re.compile(r"\b(?:girl|boy|kid|child|toddler|baby|девочк\w*|мальчик\w*|ребён\w*|ребен\w*)\b", re.I)
# «old» только при человеке: «5-year-old boy» и «old-fashioned dress» — не про возраст голоса.
_OLD = re.compile(r"(?<![-\w])(?:grandma|grandmother|grandpa|grandfather|elderly"
                  r"|old (?:man|woman|lady|wizard|king|queen)|бабушк\w*|дедушк\w*)\b", re.I)


def description_hint(character) -> dict:
    """Подсказка о голосе из описания героя: «a little girl in a pink hat» — не чётность номера."""
    text = str(getattr(character, "description", "") or "")
    hint = {}
    female, male = _FEMALE.search(text), _MALE.search(text)
    if female and male:
        hint["gender"] = "female" if female.start() < male.start() else "male"
    elif female or male:
        hint["gender"] = "female" if female else "male"
    if _CHILD.search(text):
        hint["age"] = "child"
    elif _OLD.search(text):
        hint["age"] = "old"
    return hint


def _voice_pools(character_pk: int, voices: list, male: list, female: list, hint: dict | None) -> list:
    """Из каких голосов выбирать герою: от самого подходящего круга к самому широкому.

    Подсказка важнее чётности номера. Круги нужны, потому что подходящий голос могут
    занять: в каталоге мало молодых женских, а разным героям нужны разные голоса —
    лучше другой голос того же пола, чем два героя одним.
    """
    hint = hint or {}
    gender = hint.get("gender")
    if gender == "female" and female:
        pool = female
    elif gender == "male" and male:
        pool = male
    else:
        # Пола у персонажа студии нет: чередуем мужские и женские по чётности
        # его номера — это стабильно между запусками.
        pool = (female if (character_pk % 2 and female) else male) or voices

    def aged(label: str | None) -> list:
        return [v for v in pool if label and str(v.get("age") or "").lower().startswith(label)]

    age = hint.get("age")
    # Старых голосов мало, а бабушке лучше зрелый голос, чем молодой и игривый.
    return [p for p in (aged(_AGE_LABELS.get(age)), aged("middle") if age == "old" else [], pool) if p]


def pick_voices(characters: list, voices: list | None = None, fixed: dict | None = None,
                hints: dict | None = None) -> dict:
    """Закрепить голос за каждым персонажем: разные герои — разные голоса.

    Уже звучавшие герои сохраняют свой голос. Остальным раздаём по номеру
    персонажа, а не по месту в списке: тогда при повторном плане (даже если
    сцены удалили или переставили) герой получит тот же голос.

    hints — {номер героя: {"gender", "age"}} от режиссёра сцены. Чего там нет, того
    ищем в описании героя: сцены, снятые до автоозвучки, режиссёр не оценивал.
    """
    voices = voices if voices is not None else audio.list_voices()
    if not voices:
        raise NoVoices("список голосов пуст")
    fixed = fixed or {}
    hints = hints or {}
    male = [v for v in voices if (v.get("gender") or "").lower().startswith("male")]
    female = [v for v in voices if (v.get("gender") or "").lower().startswith("female")]
    # Занятые — все закреплённые, а не только у героев из списка: в съёмке список
    # из одного героя, а голос не должен совпасть с другим героем мультфильма.
    out, taken = {}, {v["voice_id"] for v in fixed.values() if v.get("voice_id")}
    # Раздаём в порядке номеров персонажей, а не в порядке сцен: иначе тот же
    # герой получал бы другой голос, стоило поменять сцены местами.
    characters = sorted({c.pk: c for c in characters}.values(), key=lambda c: c.pk)
    for ch in characters:
        if ch.pk in fixed and fixed[ch.pk].get("voice_id"):
            out[ch.pk] = dict(fixed[ch.pk])
            taken.add(out[ch.pk]["voice_id"])
    for ch in characters:
        if ch.pk in out:
            continue
        hint = {**description_hint(ch), **{k: w for k, w in (hints.get(ch.pk) or {}).items() if w}}
        pools = _voice_pools(ch.pk, voices, male, female, hint)
        choice = None
        for pool in pools:
            for i in range(len(pool)):
                candidate = pool[(ch.pk + i) % len(pool)]
                if candidate["id"] not in taken:
                    choice = candidate
                    break
            if choice:
                break
        choice = choice or pools[0][ch.pk % len(pools[0])]
        taken.add(choice["id"])
        out[ch.pk] = {"voice_id": choice["id"], "voice_name": choice["name"]}
    return out


_ANY = object()


def set_hero_voice(project, character, voice: dict, *, keep: bool = False, expected=_ANY) -> dict:
    """Закрепить голос за героем на весь мультфильм. Возвращает закреплённый голос.

    keep — только если голоса ещё нет: две сцены одного героя снимаются разом, и
    обе выбирают голос. Строка под замком: побеждает первая, вторая берёт его же.
    expected — закрепление, которое видел запуск по плану. Стало другим — голос сменил
    человек, пока запуск шёл, и его выбор важнее плана.
    """
    from .models import CartoonProject

    key = str(character.pk)
    with transaction.atomic():
        row = CartoonProject.objects.select_for_update().get(pk=project.pk)
        voices = dict(row.hero_voices or {})
        current = voices.get(key)
        moved = expected is not _ANY and (current or {}).get("voice_id") != (expected or {}).get("voice_id")
        chosen = current if keep or moved else None
        if not (chosen and chosen.get("voice_id")) and not moved:
            chosen = {"voice_id": voice["voice_id"], "voice_name": voice.get("voice_name", "")}
            voices[key] = chosen
            row.hero_voices = voices
            row.save(update_fields=["hero_voices", "updated_at"])
    project.hero_voices = row.hero_voices
    return dict(chosen or {})


def _hero_hint(project, character, hint: dict | None) -> dict:
    """Подсказка режиссёра о голосе: своей сцены, а если там нет — другой сцены этого героя."""
    if hint and hint.get("gender"):
        return hint
    rows = project.scenes.exclude(voice_hint={}).order_by("id").values_list("character_id", "voice_hint")
    for character_id, scene_hint in rows:
        if (character_id or project.character_id) == character.pk and scene_hint.get("gender"):
            return scene_hint
    return hint or {}


def hero_voice(project, character, hint: dict | None = None) -> dict:
    """Голос героя: закреплённый, а если его нет — выбрать и тут же закрепить.

    Бросает NoVoices, если каталог голосов пуст.
    """
    project.refresh_from_db(fields=["hero_voices"])
    saved = (project.hero_voices or {}).get(str(character.pk)) or {}
    if saved.get("voice_id"):
        return dict(saved)
    fixed = known_voices(project)
    choice = fixed.get(character.pk) or pick_voices(
        [character], fixed=fixed, hints={character.pk: _hero_hint(project, character, hint)})[character.pk]
    return set_hero_voice(project, character, choice, keep=True)


def line_lang(scene) -> str | None:
    """Язык реплики по мнению режиссёра. None — он её не читал, audio.tts смотрит на буквы."""
    return (scene.voice_hint or {}).get("lang")


def line_track(scene):
    """Готовая реплика сцены (дорожка line) или None."""
    from .models import CartoonAudioTrack

    return (scene.audio_tracks.filter(kind=CartoonAudioTrack.KIND_LINE,
                                      status=CartoonAudioTrack.STATUS_READY)
            .exclude(file="").first())


class LineDraft:
    """Реплика, готовая лечь в сцену: файл есть, сведение посчитано, денег ещё нет.

    ffmpeg дольше замка строки, поэтому всё тяжёлое — здесь, вне транзакции, а
    install — внутри, вместе со списанием: обрыв не оставит ни списания без
    дорожки, ни дорожки без списания.
    """

    def __init__(self, scene, track, mixed: str):
        self.scene, self.track, self.mixed = scene, track, mixed

    def install(self, *, save_scene: bool = True) -> None:
        """Заменить реплику сцены этой. Только в транзакции со списанием."""
        from .models import CartoonAudioTrack

        CartoonAudioTrack.objects.filter(scene=self.scene, kind=CartoonAudioTrack.KIND_LINE).delete()
        self.track.save()
        if save_scene:
            self.scene.mixed_video = self.mixed
            self.scene.save(update_fields=["mixed_video", "speech_start", "speech_end", "updated_at"])

    def rival(self, old, any_voice: bool = False):
        """Та же реплика, уже озвученная другим путём, пока делался этот голос, или None.

        Звать под замком строки сцены: кнопка на карточке и «Озвучить весь мультфильм»
        не ждут друг друга, а платить дважды за одни слова человек не должен.
        any_voice — запуск по старому плану: голос на карточке выбрал человек позже.
        """
        track = line_track(self.scene)
        same = (track is not None and track.text == self.track.text
                and (any_voice or track.voice_id == self.track.voice_id))
        return track if same and (old is None or track.pk != old.pk) else None

    def drop(self) -> None:
        """Голос никому не достался: убрать его файлы. Сбой хранилища — не повод ронять сцену."""
        from django.core.files.storage import default_storage

        for path in (self.track.file, self.mixed):
            try:
                if path:
                    default_storage.delete(path)
            except Exception:
                logger.exception("голос героя: файл %s не удалился", path)


def draft_line(scene, path: str, duration: float, *, text: str, voice_id: str, voice_name: str = "",
               character=None, price: int = 0) -> LineDraft:
    """Озвученная реплика + окно сцены + сведение. Не удалось — файла не остаётся.

    У неснятой сцены (озвучили весь мультфильм заранее) сводить нечего: момент
    реплики поставит съёмка, когда появится ролик.
    """
    from django.core.files.storage import default_storage

    from .models import CartoonAudioTrack

    track = CartoonAudioTrack(scene=scene, kind=CartoonAudioTrack.KIND_LINE, character=character,
                              voice_id=voice_id, voice_name=voice_name[:120], text=text, file=path,
                              duration=duration, start_sec=audio.LINE_START_SEC, volume=1.0,
                              credits_planned=price, credits_spent=price)
    try:
        mixed = ""
        if scene.video:
            if audio.stored_window(scene) is None:
                window = audio.scene_window(scene)
                if window:
                    scene.speech_start, scene.speech_end = window
            mixed = audio.mix_scene(scene, line=track)
    except Exception:
        default_storage.delete(path)
        raise
    return LineDraft(scene, track, mixed)


class RenderLine:
    """Голос героя для только что снятого ролика.

    Три шага вокруг транзакции выдачи: prepare до неё (TTS и ffmpeg), commit внутри,
    finish после. Сбой голоса здесь и остаётся: ролик снят и должен быть выдан и
    оплачен, а человек получит сцену с голосом модели и кнопку «Озвучить».
    Деньги — только сумма с кнопки «Снять» (shot_voice_credits): нет её в цене —
    нет и нового синтеза.
    """

    def __init__(self, scene, character, video_price: int):
        self.scene, self.character, self.video_price = scene, character, video_price
        self.user = scene.project.user
        self.text = (scene.dialogue or "").strip()
        self.old = None         # реплика сцены до этой съёмки
        self.draft = None       # новая озвучка
        self.reused = False     # прежняя реплика подошла к новому ролику
        self.mixed = ""
        self.price = 0          # сколько возьмём за новый голос: сумма с кнопки «Снять»
        self.entry = None
        self.paid = 0
        self.failure = ""

    def _affordable(self, price: int) -> bool:
        """Хватит ли на голос сверх видео. Иначе синтез оплатили бы мы, а не человек."""
        from django.contrib.auth import get_user_model

        balance = (get_user_model().objects.filter(pk=self.user.pk)
                   .values_list("token_balance", flat=True).first() or 0)
        return int(balance) - int(self.video_price) >= price

    def _journal(self, model: str):
        from ai import genlog

        return genlog.start(user=self.user, kind="voice", source="studio", provider="elevenlabs",
                            model=model, prompt=self.text, credits_planned=self.price,
                            scene_id=self.scene.pk, params={"chars": len(self.text), "auto": True})

    def _keep_old(self) -> None:
        """Прежняя реплика ложится на новый ролик: новое окно, тот же звук."""
        self.mixed = audio.mix_scene(self.scene, line=self.old)
        self.reused = True

    def _same_words(self) -> bool:
        return bool(self.old is not None and self.text and self.old.text == self.text)

    def _prepare(self, beat) -> None:
        scene, text = self.scene, self.text
        self.old = line_track(scene)
        enabled = audio.line_ready(self.user)
        if not self.old and not (enabled and text):
            return
        self.price = int(scene.shot_voice_credits or 0) if enabled and text and scene.dialogue_is_speech else 0
        window = audio.scene_window(scene)
        if window:
            scene.speech_start, scene.speech_end = window
        beat()
        voice = hero_voice(scene.project, self.character, scene.voice_hint) if self.price else None
        if self._same_words() and (voice is None or voice["voice_id"] == self.old.voice_id):
            # Те же слова тем же голосом: новый синтез не нужен, новый ролик — новое окно.
            self.price = 0
            self._keep_old()
            return
        if not self.price:
            return
        if not self._affordable(self.price):
            logger.warning("сцена %s: на голос не хватает кредитов, остаётся голос модели", scene.pk)
            self.price = 0
            if self._same_words():
                self._keep_old()
            return
        self.entry = self._journal(voice["voice_id"])
        raw = audio.tts(text, voice["voice_id"], lang=line_lang(scene))
        beat()
        path, duration = audio.save_audio(raw)
        beat()
        self.draft = draft_line(scene, path, duration, text=text, voice_id=voice["voice_id"],
                                voice_name=voice.get("voice_name", ""), character=self.character,
                                price=self.price)
        beat()

    def prepare(self, beat=None) -> "RenderLine":
        """Никогда не бросает: сюда же попадает и мягкий лимит задачи."""
        scene = self.scene
        # Окно прошлого ролика к новому не относится.
        scene.speech_start = scene.speech_end = None
        try:
            self._prepare(beat or (lambda: None))
        except Exception as exc:  # noqa: BLE001 — сбой голоса не должен стоить ролика
            logger.exception("сцена %s: голос героя не получился, остаётся голос модели", scene.pk)
            # Мягкий лимит мог прийти и после готового черновика: без него нет и списания.
            if self.draft is not None:
                self.draft.drop()
                self.draft = None
            self.mixed, self.reused = "", False
            if self.price:
                (self.entry or self._journal("")).failed(str(exc)[:500])
            self.entry, self.price = None, 0
            self._fall_back()
        return self

    def _fall_back(self) -> None:
        """Новый голос не вышел: прежние слова всё равно должны встать на новое окно."""
        if self.old is None or not self._same_words():
            return
        try:
            self._keep_old()
        except Exception as exc:  # noqa: BLE001 — сцена выйдет с голосом модели
            logger.exception("сцена %s: прежняя реплика не свелась с новым роликом", self.scene.pk)
            self.mixed, self.reused = "", False
            self._journal(self.old.voice_id).failed(str(exc)[:500])

    def _pay(self) -> None:
        from plans.wallet import InsufficientTokens

        from .services import charge

        scene, track = self.scene, self.draft.track
        try:
            with transaction.atomic():
                # Пока шёл синтез, реплику могла озвучить «Озвучить весь мультфильм».
                if self.draft.rival(self.old) is not None:
                    raise Superseded("реплику уже озвучили")
                charge(self.user, track.credits_spent, "cartoon_voice",
                       meta={"scene": scene.pk, "kind": "line", "chars": len(track.text), "auto": True})
                self.draft.install(save_scene=False)
            self.paid = track.credits_spent
            scene.mixed_video = self.draft.mixed
        except InsufficientTokens:
            logger.warning("сцена %s: к выдаче не хватило кредитов на голос", scene.pk)
            self.failure = "не хватило кредитов к моменту готовности"
        except Superseded as exc:
            self.failure = str(exc)
        except Exception as exc:  # noqa: BLE001 — откатился только голос, видео уже списано
            logger.exception("сцена %s: голос героя не записался", scene.pk)
            self.failure = str(exc)
        if not self.paid:
            self.draft.drop()
            self.draft = None

    def commit(self) -> None:
        """Внутри транзакции выдачи ролика: деньги за голос и дорожка.

        Списание идёт без respect_reserves: голос платит из резерва этой сцены,
        как и видео.
        """
        from .models import CartoonAudioTrack

        scene, old = self.scene, self.old
        if self.draft is not None:
            self._pay()
        elif self.reused:
            CartoonAudioTrack.objects.filter(pk=old.pk).update(start_sec=old.start_sec)
            scene.mixed_video = self.mixed
        # Реплика от прежнего текста: к новому ролику она не относится.
        if old is not None and old.text != self.text and not self.paid:
            CartoonAudioTrack.objects.filter(pk=old.pk).delete()

    def finish(self) -> None:
        """После транзакции: закрыть запись журнала. Журнал не роняет выдачу."""
        if self.entry is None:
            return
        if self.paid:
            from django.core.files.storage import default_storage

            self.entry.delivered(credits=self.paid, result_url=default_storage.url(self.draft.track.file))
        elif self.entry.is_open():
            # Провайдер голос сделал и деньги за него взял, а человек его не получил.
            self.entry.lost(self.failure or "голос не достался сцене")

    def discard(self, why: str) -> None:
        """Ролик не выдан: голос тоже никому не достался (деньги откатила транзакция)."""
        from django.core.files.storage import default_storage

        if self.draft is not None:
            self.draft.drop()
            self.draft, self.paid = None, 0
        if self.mixed:
            default_storage.delete(self.mixed)
        if self.entry is not None and self.entry.is_open():
            self.entry.lost(why[:500])


def _ask_model(listing: list, lang: str, numbers: list) -> dict:
    """Одна пачка сцен → {номер: реплика}. Ошибки — PlanFailed."""
    from ai.handlers import _openrouter_config

    cfg = _openrouter_config()
    body = {
        "model": getattr(settings, "STUDIO_SCENE_MODEL", "google/gemini-2.5-flash"),
        "messages": [
            {"role": "system", "content": _SYSTEM.format(language=LANG_NAMES.get(lang, LANG_NAMES["ru"]))},
            {"role": "user", "content": "\n".join(listing)[:4000]},
        ],
        "temperature": 0.7,
        "max_tokens": min(4000, 400 + 160 * len(listing)),
        "response_format": {"type": "json_object"},
    }
    try:
        r = requests.post(
            f"{cfg['base_url'].rstrip('/')}/chat/completions", json=body,
            headers={"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"},
            timeout=(10, 90))
    except Exception as exc:  # noqa: BLE001
        raise PlanFailed(f"реплики: сеть: {exc}") from exc
    if not (200 <= r.status_code < 300):
        raise PlanFailed(f"реплики: http {r.status_code}: {r.text[:200]}")
    try:
        payload = r.json() or {}
    except ValueError as exc:
        raise PlanFailed("реплики: ответ не JSON") from exc
    content = (((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    match = re.search(r"\{.*\}", content, flags=re.S)
    try:
        data = json.loads(match.group(0) if match else content)
    except ValueError as exc:
        raise PlanFailed("реплики: модель ответила не JSON") from exc
    out = {}
    raw = data.get("lines") if isinstance(data, dict) else None
    for item in (raw or []):
        # Модель иногда отвечает списком строк вместо списка объектов.
        if not isinstance(item, dict):
            continue
        try:
            n = int(item.get("n"))
        except (TypeError, ValueError):
            continue
        text = " ".join(str(item.get("text") or "").split())[:MAX_LINE_CHARS]
        if text and n in numbers:
            out[n] = text
    return out


def write_lines(scenes: list, lang: str = "ru") -> dict:
    """Реплики для всех сцен: {номер сцены (с единицы): текст}.

    Просим пачками: на длинном списке ответ обрывается по лимиту токенов, и
    тогда без пачек не было бы вообще ничего.
    """
    if not scenes:
        return {}
    result, failures = {}, 0
    for start in range(0, len(scenes), CHUNK):
        chunk = scenes[start:start + CHUNK]
        numbers = list(range(start + 1, start + len(chunk) + 1))
        listing = []
        for n, scene in zip(numbers, chunk):
            hero = _scene_hero(scene)
            seconds = scene_seconds(scene)
            listing.append(
                f"{n}. Сцена: {scene_label(scene)}. Персонаж: {hero.name if hero else 'герой'}. "
                f"Длительность: {seconds} с, не длиннее {min(MAX_LINE_CHARS, seconds * 13)} символов.")
        try:
            result.update(_ask_model(listing, lang, numbers))
        except PlanFailed:
            logger.exception("реплики: пачка сцен %s-%s не написалась", numbers[0], numbers[-1])
            failures += 1
    if not result:
        raise PlanFailed(f"реплики: ни одной пачки не получилось ({failures})")
    return result


def build_plan(project, lang: str = "ru") -> dict:
    """План озвучки всего мультфильма: реплика и голос на каждую сцену + цена.

    Сцены, где человек сам написал реплику, идут в план пунктом line: текст
    заморожен (он в карточке сцены), озвучка заменяет речь модели. Без дорожки
    line реплику произнёс бы голос модели, а герой должен звучать одинаково.
    Не попадают сюда: описания (вслух не читаем), уже озвученные реплики и сцены,
    которые ещё не сняты или снимаются — их озвучит сама съёмка, это уже в её цене.

    Автоозвучка выключена — как было: такие сцены пропускаются, реплику произносит
    модель, и второй голос поверх дал бы эхо.
    """
    from .models import CartoonAudioTrack

    everything = list(project.scenes.select_related(
        "preset", "preset__video_model", "character", "shot_model",
        "project__character", "project__video_model").order_by("order", "id"))
    everything = [s for s in everything if _scene_hero(s)]
    spoken = [s for s in everything if (s.dialogue or "").strip()]
    frozen, line_voiced, descriptions, unshot, working, ready = {}, 0, 0, 0, 0, {}
    line_on = audio.line_ready(project.user)
    if line_on:
        # Снятое до автоозвучки и поправленные слова режиссёр не читал: описание здесь
        # прочли бы вслух.
        director.judge_lines([s for s in spoken if s.video and director.unjudged(s)
                              and s.status not in WORKING_STATES])
        ready = dict(CartoonAudioTrack.objects.filter(
            scene__project=project, kind=CartoonAudioTrack.KIND_LINE).values_list("scene_id", "text"))
        for scene in spoken:
            text = scene.dialogue.strip()
            if not scene.dialogue_is_speech:
                descriptions += 1
            elif ready.get(scene.pk) == text:
                line_voiced += 1
            elif scene.video and scene.status not in WORKING_STATES:
                # Неснятую сцену озвучит съёмка: голос уже в цене «Снять», а режиссёр
                # ещё не решил, слова ли это, и описание здесь прочли бы вслух.
                frozen[scene.pk] = text
            elif scene.status in WORKING_STATES:
                working += 1
            else:
                unshot += 1
    counts = {"spoken_in_video": 0 if line_on else len(spoken), "line_voiced": line_voiced,
              "descriptions": descriptions, "unshot": unshot, "working": working}
    # Реплику стёрли, а дорожка осталась: новая ИИ-реплика зазвучала бы поверх неё.
    scenes = [s for s in everything if s.pk in frozen
              or (not (s.dialogue or "").strip() and s.pk not in ready)][:MAX_LINES]
    if not scenes:
        return {"lines": [], "total_credits": 0, **counts}

    heroes, seen, hints = [], set(), {}
    for scene in scenes:
        hero = _scene_hero(scene)
        if (scene.voice_hint or {}).get("gender") and hero.pk not in hints:
            hints[hero.pk] = scene.voice_hint
        if hero.pk not in seen:
            seen.add(hero.pk)
            heroes.append(hero)
    # Голоса спрашиваем ДО платного вызова модели: если их нет, незачем тратить
    # деньги на реплики, которые нечем озвучить.
    voices = pick_voices(heroes, fixed=known_voices(project), hints=hints)

    # Модель пишет реплики только сценам без своей реплики; нумерация — по этому списку.
    free = [s for s in scenes if s.pk not in frozen]
    numbers = {s.pk: i for i, s in enumerate(free, start=1)}
    texts = write_lines(free, lang) if free else {}

    voiced = set(project.scenes.filter(audio_tracks__kind="voice")
                 .values_list("pk", flat=True))
    lines, total = [], 0
    for scene in scenes:
        # Сцена без реплики остаётся в списке с пустым текстом: молча пропасть
        # она не должна — человек увидит её и допишет реплику сам.
        text = frozen.get(scene.pk) or texts.get(numbers.get(scene.pk)) or ""
        hero = _scene_hero(scene)
        voice = voices.get(hero.pk) or {}
        price = audio.voice_price(text) if text else 0
        total += price
        lines.append({
            "scene_id": scene.pk,
            "order": scene.order,
            "title": scene_label(scene),
            "seconds": scene_seconds(scene),
            "character": {"id": hero.pk, "name": hero.name},
            "voice_id": voice.get("voice_id", ""),
            "voice_name": voice.get("voice_name", ""),
            "text": text,
            "credits": price,
            "has_voice": scene.pk in voiced,
            # Реплика человека: текст не правится здесь, озвучка заменит речь модели.
            "line": scene.pk in frozen,
        })
    return {"lines": lines, "total_credits": total, **counts}


# ------------------------------------------------------------- озвучка ---

def voice_line(scene, text: str, voice_id: str, voice_name: str = "", character=None,
               replace: bool = True, guard=None, line: bool = False):
    """Озвучить одну реплику сцены и списать кредиты ПОСЛЕ готового звука.

    replace — убрать прежние ИИ-реплики сцены: повторная озвучка мультфильма не
    должна наслаивать голоса друг на друга.

    guard — проверка «запуск всё ещё мой» прямо перед списанием: пока шёл
    синтез, человек мог перезапустить озвучку, и тогда платит новый запуск.

    line — реплика человека вместо речи модели (дорожка line): заменяет только
    прежнюю line, дорожки, которые человек сделал сам, не трогает. Сводится здесь
    же, поэтому под замком сведения сцены.

    Деньги и дорожка пишутся одной транзакцией: иначе обрыв между списанием и
    записью оставил бы человека без звука, но с минусом на балансе.
    """
    text = " ".join(str(text or "").split())[:MAX_SCENE_LINE_CHARS if line else MAX_LINE_CHARS]
    if not text or not audio.valid_voice_id(voice_id):
        return None
    with audio.mix_lock(scene.pk) if line else nullcontext():
        return _voice_line(scene, text, voice_id, voice_name, character, replace, guard, line)


def _voice_line(scene, text, voice_id, voice_name, character, replace, guard, line):
    from django.core.files.storage import default_storage

    from ai import genlog

    from plans.wallet import InsufficientTokens

    from .models import CartoonAudioTrack, CartoonScene
    from .services import charge

    old = line_track(scene) if line else None
    # Уже озвученные слова в план не попадают: значит, дорожка появилась, пока запуск ждал
    # очереди, и голос в ней выбран позже плана. Второй раз не платим и его не затираем.
    if old is not None and old.text == text:
        return None
    price = audio.voice_price(text)
    entry = genlog.start(user=scene.project.user, kind="voice", source="studio", provider="elevenlabs",
                         model=voice_id, prompt=text, credits_planned=price, scene_id=scene.pk,
                         params={"chars": len(text), "all": True})
    try:
        raw = audio.tts(text, voice_id, lang=line_lang(scene)) if line else audio.tts(text, voice_id)
        path, duration = audio.save_audio(raw)
        draft = (draft_line(scene, path, duration, text=text, voice_id=voice_id, voice_name=voice_name,
                            character=character, price=price) if line else None)
    except Exception as exc:
        entry.failed(str(exc)[:500])
        raise

    def drop():
        if draft is not None:
            draft.drop()
        else:
            default_storage.delete(path)

    if guard is not None and not guard():
        drop()
        entry.lost("озвучку перезапустили")
        raise Superseded("озвучку перезапустили")
    try:
        with transaction.atomic():
            if draft is not None:
                # Замок строки: карточка могла озвучить ту же реплику, пока шёл синтез.
                CartoonScene.objects.select_for_update().filter(pk=scene.pk).values_list("pk").first()
                if draft.rival(old, any_voice=True) is not None:
                    drop()
                    entry.lost("реплику уже озвучили")
                    return None
                draft.install()
                track = draft.track
            else:
                if replace:
                    CartoonAudioTrack.objects.filter(
                        scene=scene, kind=CartoonAudioTrack.KIND_VOICE).delete()
                track = CartoonAudioTrack.objects.create(
                    scene=scene, kind=CartoonAudioTrack.KIND_VOICE, character=character,
                    voice_id=voice_id, voice_name=voice_name, text=text, file=path,
                    duration=duration, start_sec=0, volume=1.0, credits_spent=price)
            # Резервы идущих съёмок не трогаем: иначе готовый ролик остался бы без оплаты.
            charge(scene.project.user, price, "cartoon_voice", respect_reserves=True,
                   meta={"scene": scene.pk, "kind": track.kind, "chars": len(text), "all": True})
    except InsufficientTokens:
        drop()
        entry.lost("не хватило кредитов к моменту готовности")
        raise
    except Exception as exc:
        # Звук не достался человеку — и платить за него он не должен.
        drop()
        entry.lost(str(exc)[:500])
        raise
    entry.delivered(credits=price, result_url=default_storage.url(path))
    return track


def voice_project(project, plan: list, replace: bool = True, token: str = "") -> dict:
    """Озвучить все реплики плана и свести снятые сцены. Считает прогресс.

    token — замок этого запуска. Потерян (человек перезапустил озвучку, пока эта
    задача стояла в очереди или висела на синтезе) — останавливаемся до списания
    и чужой прогресс не трогаем.
    """
    from celery.exceptions import SoftTimeLimitExceeded

    from plans.wallet import InsufficientTokens

    from .models import CartoonScene

    total = len(plan)
    if not lock_owned(project.pk, token):
        logger.warning("озвучка мультфильма %s: запуск уже перехвачен новым", project.pk)
        return {"done": 0, "total": total, "spent": 0, "error": "superseded"}
    # Задача началась: с этой секунды «тишина» в прогрессе — уже обрыв.
    set_progress(project.pk, done=0, total=total, error="", spent=0, finished=False,
                 queued=False)
    touch_lock(project.pk, token)
    done, spent, error = 0, 0, ""
    project.refresh_from_db(fields=["hero_voices"])
    pinned = dict(project.hero_voices or {})
    for item in plan:
        if not lock_owned(project.pk, token):
            error = "superseded"
            break
        try:
            scene_id = int(item.get("scene_id") or 0)
        except (TypeError, ValueError):
            continue
        # Сцену могли удалить из ленты, пока шла озвучка.
        scene = (CartoonScene.objects.select_related("project", "project__user", "character",
                                                     "project__character")
                 .filter(pk=scene_id, project=project).first())
        if not scene:
            continue
        character = scene.character or scene.project.character
        line = bool(item.get("line"))
        # Запуск мог ждать очередь полчаса. Сцену запустили в съёмку — она озвучит себя сама;
        # неснятую тоже озвучит съёмка; слова поправили или режиссёр признал их описанием —
        # план устарел, за него человек платить не должен.
        if line and (scene.status in WORKING_STATES or not scene.video or not scene.dialogue_is_speech
                     or " ".join((scene.dialogue or "").split()) != " ".join(str(item.get("text") or "").split())):
            continue
        try:
            track = voice_line(scene, item.get("text"), item.get("voice_id"),
                               item.get("voice_name") or "", character, replace,
                               guard=lambda: lock_owned(project.pk, token), line=line)
        except Superseded:
            error = "superseded"
            logger.warning("озвучка мультфильма %s: перезапущена, эта задача остановилась",
                           project.pk)
            break
        except InsufficientTokens:
            error = "not_enough_credits"
            logger.warning("озвучка мультфильма %s: не хватило кредитов на сцене %s",
                           project.pk, scene.pk)
            break
        except SoftTimeLimitExceeded:
            # Мягкий лимит: выходим сами, чтобы сняли замок и записали прогресс.
            error = "timeout"
            logger.warning("озвучка мультфильма %s: не успели за отведённое время", project.pk)
            break
        except Exception:
            logger.exception("озвучка мультфильма %s: сцена %s не озвучилась", project.pk, scene.pk)
            error = "line_failed"
            continue
        if track:
            done += 1
            spent += track.credits_spent
            set_progress(project.pk, done=done, spent=spent, error=error)
            touch_lock(project.pk, token)
            if character:
                # Голос героя один на мультфильм. План заполнен закреплённым голосом,
                # так что другой здесь — сознательный выбор человека: иначе пересъёмка
                # вернула бы старый и взяла за него ещё раз. Но если голос сменили
                # на карточке, пока шёл запуск, выбор сделан позже плана.
                key = str(character.pk)
                chosen = set_hero_voice(project, character, {"voice_id": track.voice_id,
                                                             "voice_name": track.voice_name},
                                        expected=pinned.get(key))
                if chosen.get("voice_id") == track.voice_id:
                    pinned[key] = chosen
        # Сведение сразу: снятая сцена начинает говорить, пока идут остальные.
        # Состояние сцены перечитывается внутри remix_scene — её могли доснять.
        # Реплика line уже сведена: её свели до списания.
        if not line:
            try:
                audio.remix_scene(scene)
            except Exception:
                logger.exception("озвучка мультфильма %s: сцена %s не свелась", project.pk, scene.pk)
        touch_lock(project.pk, token)
    if error != "superseded":
        # Прогресс перехваченного запуска принадлежит новому — его не закрываем.
        set_progress(project.pk, done=done, spent=spent, error=error, finished=True)
    return {"done": done, "total": total, "spent": spent, "error": error}

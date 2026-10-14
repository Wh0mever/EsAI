"""Снять ролики для карусели первого экрана — все сценарии одной командой.

    python manage.py vstudio_shoot_showcase --user <почта сотрудника> --dry-run
    python manage.py vstudio_shoot_showcase --user <почта сотрудника> --yes
        [--only film,ad] [--label v2] [--publish] [--timeout 900] [--poll 5]

Что и на чём снимать — в vstudio.showcase_scenarios. Команда тратит настоящие
кредиты аккаунта, поэтому своего пути к деньгам у неё нет:
- цена — views.prepare + views.quote_json, а проверки запуска —
  views.check_can_run: ровно то, что делают POST quote/ и POST shots/;
- запуск — сама вьюха ShotsView, вызванная DRF-запросом с подставленным
  пользователем (без HTTP, но тем же кодом): режим студии, тариф, сверка цены,
  резерв под замком, дубль и постановка задачи после фиксации. Баланс, резерв
  и дубли команда не пишет нигде;
- в витрину работа ставится через showcase.add — с записью в журнал действий
  и сборкой лёгкой копии.

Снимает воркер студии; команда только ждёт, перечитывая дубли из базы.

Повторный запуск с той же меткой ничего не переснимает: у сценария постоянный
client_request_id, и вьюха отвечает уже созданным дублем. Незаконченное с
прошлого раза команда дожидается, готовое — ставит в витрину. Переснять
сценарий — новая метка: --only film --label v2.

Неожиданный сбой (база, кэш) новые запуски останавливает: итог печатается всё
равно, код возврата — ненулевой, а начатое подхватит следующий запуск с той же
меткой.
"""
from __future__ import annotations

import dataclasses
import re
import sys
import time
from dataclasses import dataclass, field

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from plans.tiers import TIER_PAID, user_tier
from vstudio import compiler, pricing, reserve, showcase, views
from vstudio import serializers as S
from vstudio.caps import FRAME_FIRST, KIND_IMAGE, KIND_VIDEO
from vstudio.errors import StudioError
from vstudio.models import Asset, Project, ShotInput, ShowcaseItem, Take
from vstudio.showcase_scenarios import BY_KEY, KEYS, MODE_I2V, SCENARIOS, Scenario, position, sort_for

DEFAULT_LABEL = "v1"
DEFAULT_TIMEOUT_S = 900
DEFAULT_POLL_S = 5.0
# Метка входит в client_request_id (≤ 64 символов, без пробелов).
LABEL_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,24}$")
# Облегчённые версии моделей: кусок «Veo 3.1» не должен найти «Veo 3.1 Lite».
VARIANT_WORDS = ("lite", "fast", "mini")
AUTO = "auto"
PART_VIDEO = "video"
PART_IMAGE = "image"
PROJECT_TITLE = "Карусель: сценарии ({label})"
API = "/api/vstudio/"
STUB_UID = "0" * 32
STUB_LONG_SIDE = 1280

FIELD_RU = {"duration": "длительность", "resolution": "качество", "aspect_ratio": "пропорции"}

# Чем закончился сценарий в этом прогоне.
SHOT = "shot"
READY_BEFORE = "ready_before"
FAILED = "failed"
SKIPPED = "skipped"
NOT_STARTED = "not_started"
TIMED_OUT = "timed_out"

# Что ответил запуск.
LAUNCHED = "launched"
RETRY = "retry"
DROPPED = "dropped"
STOP = "stop"
# Отказы, после которых новые запуски бессмысленны: дело не в сценарии.
STOP_CODES = ("insufficient_balance", "provider_unavailable", "vstudio_disabled", "unauthorized")


# ---------------------------------------------------------------- модель и параметры

@dataclass
class Choice:
    """Какая модель досталась сценарию и почему — это печатает план."""

    row: dict | None
    why: str
    skipped: list = field(default_factory=list)


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _matches(name, fragment, *, strict: bool) -> bool:
    name, fragment = _norm(name), _norm(fragment)
    if not fragment or fragment not in name:
        return False
    if not strict:
        return True
    rest = re.findall(r"[^\W_]+", name.replace(fragment, " "))
    return not any(word in rest for word in VARIANT_WORDS)


def pick_model(rows, fragments, *, cheapest: bool = False, first_frame: bool = False,
               aspect: str | None = None) -> Choice:
    """Модель сценария из каталога студии, каким его видит аккаунт (список ModelJSON).

    Куски названий пробуются по порядку. Модель закрыта тарифом, не умеет
    начинать с кадра или снимать в пропорциях сценария (aspect) — идём к
    следующему куску. Среди подходящих: точное название, иначе самое короткое
    (cheapest — самая дешёвая: так выбирается модель исходной картинки). Не
    подошёл ни один кусок — модель студии по умолчанию: первая открытая в
    каталоге, как на фронте (defaultModel), из тех, что сценарию подходят.

    Пропорции — часть сценария, а не параметр «как получится»: горизонтальный
    ролик под названием «Reels / TikTok» — кредиты впустую. Поэтому модель без
    них не берётся вовсе, а не снимает в своих.
    """
    rows = list(rows or [])
    skipped: list[str] = []

    def lacks(row) -> str:
        # Чего модель не умеет из нужного сценарию; пусто — подходит.
        caps = row.get("caps") or {}
        if first_frame and FRAME_FIRST not in (caps.get("frames") or []):
            return "начинать видео с кадра"
        if aspect not in (None, AUTO) and aspect not in (caps.get("aspect_ratios") or []):
            return str(aspect)
        return ""

    def missing(found) -> str:
        return ", ".join(dict.fromkeys(lacks(r) for r in found))

    for fragment in fragments:
        found = [r for r in rows if _matches(r.get("name"), fragment, strict=not cheapest)]
        if not found:
            skipped.append(f"«{fragment}» — такой модели в студии нет")
            continue
        names = ", ".join(str(r.get("name")) for r in found)
        usable = [r for r in found if not r.get("locked")]
        if not usable:
            skipped.append(f"«{fragment}» — {names}: закрыто тарифом аккаунта")
            continue
        fit = [r for r in usable if not lacks(r)]
        if not fit:
            skipped.append(f"«{fragment}» — {names}: не умеет {missing(usable)}")
            continue
        usable = fit
        if cheapest:
            # min берёт первую из равных — порядок каталога.
            row = min(usable, key=lambda r: (r.get("price_from") is None, r.get("price_from") or 0))
            return Choice(row, f"самая дешёвая из «{fragment}»", skipped)
        exact = [r for r in usable if _norm(r.get("name")) == _norm(fragment)]
        if exact:
            return Choice(exact[0], f"точное название «{fragment}»", skipped)
        row = min(usable, key=lambda r: len(_norm(r.get("name"))))
        return Choice(row, f"самое короткое название с «{fragment}»", skipped)
    unlocked = [r for r in rows if not r.get("locked")]
    for row in unlocked:
        if not lacks(row):
            return Choice(row, "модель студии по умолчанию", skipped)
    if unlocked:
        return Choice(None, f"нет доступной модели (открытые не умеют {missing(unlocked)})", skipped)
    return Choice(None, "нет доступной модели", skipped)


def _same_resolution(values, wanted):
    low = str(wanted or "").lower()
    return next((v for v in values if str(v).lower() == low), None) if low else None


def fit_params(row: dict, kind: str, wanted: dict) -> tuple[dict, list[str]]:
    """Параметры сценария под модель — по правилам панели студии.

    То же, что делает фронт при смене модели (settingsModel.normalizeParams):
    что модель умеет — остаётся, длительность — ближайшая (при равенстве
    меньшая), качество и пропорции — значение модели по умолчанию. Иначе
    компилятор ответил бы invalid_param и сценарий не снялся бы вовсе.
    Второе значение — замены словами.
    """
    caps = row.get("caps") or {}
    dflt = row.get("defaults") or {}
    out: dict = {}

    aspects = list(caps.get("aspect_ratios") or [])

    def fits(value) -> bool:
        return value == AUTO or value in aspects

    aspect = wanted.get("aspect_ratio")
    if not fits(aspect):
        aspect = dflt.get("aspect_ratio") if fits(dflt.get("aspect_ratio")) else AUTO
    out["aspect_ratio"] = aspect

    if kind == KIND_VIDEO:
        durations = list(caps.get("durations") or [])
        duration = wanted.get("duration", dflt.get("duration"))
        if durations:
            target = durations[0] if duration is None else duration
            out["duration"] = (target if target in durations
                               else min(durations, key=lambda d: (abs(d - target), d)))
        elif duration is not None:
            out["duration"] = duration
        resolutions = list(caps.get("resolutions") or [])
        if resolutions:
            out["resolution"] = (_same_resolution(resolutions, wanted.get("resolution"))
                                 or _same_resolution(resolutions, dflt.get("resolution"))
                                 or resolutions[0])
        elif wanted.get("resolution") or dflt.get("resolution"):
            out["resolution"] = wanted.get("resolution") or dflt.get("resolution")

    allowed = {"duration": caps.get("durations"), "resolution": caps.get("resolutions"),
               "aspect_ratio": aspects}
    changes = []
    for name in ("duration", "resolution", "aspect_ratio"):
        if name not in wanted or name not in out:
            continue
        if str(out[name]).lower() != str(wanted[name]).lower():
            can = ", ".join(str(v) for v in allowed.get(name) or []) or "—"
            changes.append(f"{FIELD_RU[name]}: {wanted[name]} → {out[name]} (модель умеет: {can})")
    return out, changes


def client_id(label: str, key: str, part: str = PART_VIDEO) -> str:
    """Постоянный client_request_id шага.

    Уникален в паре с пользователем (индекс vs_take_idem), поэтому «пользователь,
    сценарий, метка» дают один и тот же дубль при любом числе запусков команды.
    """
    base = f"scen:{label}:{key}"
    return base if part == PART_VIDEO else f"{base}:img"


def _frame_size(aspect) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+):(\d+)", str(aspect or ""))
    w, h = (int(match.group(1)), int(match.group(2))) if match else (16, 9)
    if not w or not h:
        w, h = 16, 9
    if w >= h:
        return STUB_LONG_SIDE, max(1, round(STUB_LONG_SIDE * h / w))
    return max(1, round(STUB_LONG_SIDE * w / h)), STUB_LONG_SIDE


def _params_text(kind: str, params: dict) -> str:
    params = params or {}
    aspect = str(params.get("aspect_ratio") or AUTO)
    if kind != KIND_VIDEO:
        return aspect
    parts = []
    if params.get("duration"):
        parts.append(f"{params['duration']} с")
    if params.get("resolution"):
        parts.append(str(params["resolution"]))
    return " · ".join(parts + [aspect])


def _issues_text(issues) -> str:
    return "; ".join(str(i.get("message") or i.get("code")) for i in issues or [] if isinstance(i, dict))


def _refusal_text(data: dict) -> str:
    """Отказ студии словами: причины компилятора, если они есть, иначе общий текст."""
    return _issues_text(data.get("errors")) or str(data.get("error") or data.get("detail") or "")


def _error_text(exc) -> str:
    """Исключение одной строкой: у ошибок базы текст бывает в несколько строк."""
    return " ".join(f"{type(exc).__name__}: {exc}".split()).rstrip(" .:")


# ---------------------------------------------------------------- план

@dataclass
class Step:
    """Один оплачиваемый запуск: ролик сценария или его исходная картинка."""

    scenario: Scenario
    part: str
    kind: str
    cid: str
    prompt: str
    choice: Choice
    params: dict = field(default_factory=dict)
    changes: list = field(default_factory=list)
    credits: int | None = None
    mode: str = ""
    # Цена посчитана с условным кадром: настоящей картинки ещё нет.
    estimate: bool = False
    warnings: list = field(default_factory=list)
    blocker: str = ""
    # Дубль этого клика, если он уже есть (прошлый запуск команды с той же меткой).
    take: Take | None = None

    @property
    def name(self) -> str:
        key = self.scenario.key
        return key if self.part == PART_VIDEO else f"{key} (кадр)"

    @property
    def runnable(self) -> bool:
        return bool(not self.blocker and self.credits)


@dataclass
class Track:
    """Сценарий в этом прогоне: его шаги и чем всё кончилось."""

    scenario: Scenario
    position: int
    video: Step
    image: Step | None = None
    # Что будет запущено сейчас; пусто — запускать нечего или нельзя (note).
    todo: list = field(default_factory=list)
    note: str = ""
    outcome: str = ""


class Command(BaseCommand):
    help = ("Снять ролики сценариев для карусели первого экрана видеостудии и поставить их "
            "в витрину скрытыми. Тратит кредиты аккаунта --user.")

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, metavar="EMAIL",
                            help="Почта сотрудника (is_staff): с его баланса идёт съёмка, "
                                 "ему принадлежат работы")
        parser.add_argument("--only", default=None, metavar="KEYS",
                            help="Только эти сценарии, через запятую: " + ", ".join(KEYS))
        parser.add_argument("--label", default=DEFAULT_LABEL,
                            help="Метка запуска (по умолчанию v1). С той же меткой сценарий "
                                 "не переснимается; новая метка — новая попытка")
        parser.add_argument("--dry-run", action="store_true",
                            help="Только план и цены: ничего не запускать и не писать в базу")
        parser.add_argument("--yes", action="store_true",
                            help="Не спрашивать подтверждение перед съёмкой")
        parser.add_argument("--publish", action="store_true",
                            help="Сразу показывать на сайте работы, которые этот запуск ставит в "
                                 "витрину (по умолчанию — скрытыми). Уже стоящие строки не включает")
        parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S, metavar="SECONDS",
                            help="Сколько секунд ждать один дубль (по умолчанию 900)")
        parser.add_argument("--poll", type=float, default=DEFAULT_POLL_S, metavar="SECONDS",
                            help="Пауза между проверками дублей в базе (по умолчанию 5)")

    # ------------------------------------------------------------ вход

    def handle(self, *args, **opts):
        if not (opts.get("stdout") or opts.get("stderr")):
            # В плане есть «→» и «≈». Когда вывод идёт в файл или трубу на Windows,
            # кодировка — cp1251, и печать упала бы посреди съёмки.
            for stream in (sys.stdout, sys.stderr):
                if hasattr(stream, "reconfigure"):
                    stream.reconfigure(errors="replace")
        self._label = self._clean_label(opts["label"])
        scenarios = self._pick_scenarios(opts["only"])
        self._user = self._find_user(opts["user"])
        self._check_keys(scenarios)
        mode = views.studio_mode()
        if not views.can_generate(self._user, mode):
            raise CommandError(
                f"Видеостудия сейчас в режиме «{mode}» и этому аккаунту генерировать не даёт. "
                "Включите её (VSTUDIO_MODE или настройка vstudio_mode в панели) и повторите.")
        self._publish = bool(opts["publish"])
        self._timeout = max(1, int(opts["timeout"]))
        self._poll = max(0.5, float(opts["poll"]))
        self._factory = APIRequestFactory()

        tier = user_tier(self._user)
        self.stdout.write(f"Съёмка роликов для карусели видеостудии. Аккаунт: {self._user.email}, "
                          f"тариф: {tier}. Режим студии: {mode}. Метка запуска: {self._label}.")
        if tier != TIER_PAID:
            self.stdout.write(self.style.WARNING(
                "У аккаунта не платный тариф: платные модели для него закрыты, сценарии уйдут на "
                "бесплатные или не запустятся вовсе."))

        self._catalog = views.models_catalog(self._user)
        tracks = [self._plan(sc) for sc in scenarios]
        total = self._print_plan(tracks)
        if opts["dry_run"]:
            self.stdout.write("Пробный прогон: ничего не запущено, в базу ничего не записано.")
            return

        fresh = [step for track in tracks for step in track.todo]
        known = [track for track in tracks if track.video.take or (track.image and track.image.take)]
        if not fresh and not known:
            self.stdout.write(self.style.WARNING("Запускать нечего: ни один сценарий снять нельзя."))
            return
        if fresh:
            balance = reserve.balance_snapshot(self._user, total) or {}
            if int(balance.get("after") or 0) < 0:
                raise CommandError(
                    f"Баланса не хватает: нужно {total} кр, свободно {balance.get('available')} кр. "
                    "Пополните баланс или сузьте список сценариев (--only). Ничего не запущено.")
        if not opts["yes"] and not self._confirm(total):
            self.stdout.write("Отменено: ничего не запущено.")
            return
        self._shoot(tracks)
        self._print_summary(tracks)
        if self._crash is not None:
            # Итог уже напечатан; код возврата — ненулевой, чтобы обрыв не сошёл за успех.
            raise CommandError(f"Съёмка оборвалась: {_error_text(self._crash)}. Запустите команду "
                               "ещё раз с той же меткой — она подхватит начатое.") from self._crash

    def _clean_label(self, raw) -> str:
        label = str(raw or "").strip()
        if not LABEL_RE.match(label):
            raise CommandError("--label: до 24 символов — латинские буквы, цифры, точка, дефис, "
                               "подчёркивание.")
        return label

    def _pick_scenarios(self, raw) -> list[Scenario]:
        if raw is None:
            return list(SCENARIOS)
        wanted = [part.strip() for part in str(raw).split(",") if part.strip()]
        if not wanted:
            # --only "$KEYS" с пустой переменной — не «все двенадцать»: с новой меткой
            # и --yes это была бы полная пересъёмка без единого вопроса.
            raise CommandError(f"--only: пустой список сценариев. Есть: {', '.join(KEYS)}.")
        unknown = [key for key in wanted if key not in BY_KEY]
        if unknown:
            raise CommandError(f"--only: нет сценариев {', '.join(unknown)}. Есть: {', '.join(KEYS)}.")
        return [sc for sc in SCENARIOS if sc.key in wanted]

    def _find_user(self, email):
        user = get_user_model().objects.filter(email__iexact=str(email or "").strip()).first()
        if user is None:
            raise CommandError(f"Аккаунт {email} не найден.")
        if not user.is_active:
            raise CommandError(f"Аккаунт {user.email} отключён.")
        if not user.is_staff:
            # Витрина ставит только работы сотрудников (showcase.can_publish): ролики
            # обычного аккаунта были бы сняты и оплачены зря.
            raise CommandError(f"Аккаунт {user.email} — не сотрудник (is_staff). Витрина принимает "
                               "только работы сотрудников: кредиты ушли бы впустую.")
        return user

    def _check_keys(self, scenarios) -> None:
        # Проверяем до съёмки тем же списком, что showcase.add: иначе готовые и
        # оплаченные ролики в витрину бы не встали.
        missing = [sc.key for sc in scenarios if sc.key not in showcase.CATEGORIES]
        if missing:
            raise CommandError(
                f"В витрине нет сценариев: {', '.join(missing)}. На этом сервере старый список "
                "разделов — выложите серверную часть со сценариями карусели "
                "(ShowcaseItem.CATEGORY_CHOICES, миграция vstudio 0004) и повторите.")

    def _confirm(self, total: int) -> bool:
        question = (f"Запустить съёмку на {total} кр?" if total
                    else "Новых запусков нет. Дождаться начатого и поставить готовое в витрину?")
        try:
            answer = input(f"{question} [y/N] ")
        except EOFError:
            raise CommandError("Подтверждения нет: добавьте --yes. Ничего не запущено.") from None
        return answer.strip().lower() in ("y", "yes", "д", "да")

    # ------------------------------------------------------------ план

    def _plan(self, sc: Scenario) -> Track:
        is_i2v = sc.mode == MODE_I2V
        video = Step(sc, PART_VIDEO, KIND_VIDEO, client_id(self._label, sc.key), sc.prompt,
                     pick_model(self._catalog.get(KIND_VIDEO), sc.models, first_frame=is_i2v,
                                aspect=sc.params.get("aspect_ratio")))
        track = Track(sc, position(sc.key), video)
        self._fit(video, sc.params)
        if is_i2v:
            image = Step(sc, PART_IMAGE, KIND_IMAGE, client_id(self._label, sc.key, PART_IMAGE),
                         sc.image_prompt,
                         pick_model(self._catalog.get(KIND_IMAGE), sc.image_models, cheapest=True))
            # Картинка в пропорциях ролика: иначе первый кадр обрежется.
            self._fit(image, {"aspect_ratio": video.params.get("aspect_ratio", AUTO)})
            track.image = image

        image = track.image
        if video.take is not None:
            return track
        if image is None:
            self._quote(video)
        elif image.take is None:
            self._quote(image)
            self._quote(video, stub_frame=True)
        elif image.take.status == Take.STATUS_DONE:
            frame = self._frame_inputs(image.take)
            if not frame:
                track.note = "у готовой исходной картинки нет файла — переснимите с новой меткой (--label)"
                return track
            self._quote(video, frame)
        elif image.take.status in Take.OPEN:
            self._quote(video, stub_frame=True)
        else:
            track.note = (f"исходная картинка в прошлый раз не получилась "
                          f"({image.take.error_code or image.take.status}) — переснимите с новой "
                          "меткой (--label)")
            return track

        steps = [video] if image is None or image.take is not None else [image, video]
        blocked = next((step for step in steps if not step.runnable), None)
        if blocked is None:
            track.todo = steps
        else:
            reason = blocked.blocker or "цена не посчиталась"
            track.note = reason if blocked is video else f"исходная картинка: {reason}"
        return track

    def _fit(self, step: Step, wanted: dict) -> None:
        step.take = (Take.objects.filter(user=self._user, client_request_id=step.cid)
                     .select_related("result_asset").first())
        if step.choice.row is None:
            step.blocker = step.choice.why
        else:
            step.params, step.changes = fit_params(step.choice.row, step.kind, wanted)

    def _body(self, step: Step, inputs=(), project=None) -> dict:
        """Тело POST quote/ и POST shots/. Запрос — текстом (prompt_text): в документ
        его разбирает сама студия, как текст из запасного поля фронта."""
        return {"kind": step.kind, "model": step.choice.row["id"], "prompt_text": step.prompt,
                "params": dict(step.params), "inputs": list(inputs), "project": project}

    def _frame_inputs(self, take: Take) -> list[dict]:
        """Результат дубля-картинки как первый кадр ролика (слот first_frame, как из библиотеки)."""
        asset = take.result_asset
        if asset is None:
            return []
        return [{"asset": asset.uid, "slot": ShotInput.SLOT_FIRST_FRAME, "position": 0, "role": "",
                 "included": True}]

    def _quote(self, step: Step, inputs=(), *, stub_frame: bool = False) -> None:
        """Цена и проверки шага — тем же кодом, что POST quote/ и запуск."""
        if step.choice.row is None:
            return
        try:
            prepared = views.prepare(self._user, S.parse_shot_request(self._body(step, inputs)))
        except StudioError as err:
            step.blocker = _refusal_text(err.payload())
            return
        if stub_frame:
            prepared = self._with_stub_frame(prepared)
            step.estimate = True
        data = views.quote_json(prepared, self._user)
        step.credits = data["credits"]
        step.mode = data["mode"] or ""
        step.warnings = [str(w.get("message") or w.get("code")) for w in data["warnings"]]
        try:
            views.check_can_run(self._user, prepared, prepared.credits or 0)
        except StudioError as err:
            step.blocker = _refusal_text(err.payload())

    def _with_stub_frame(self, prepared):
        """Тот же запрос с первым кадром, которого ещё нет: картинку снимем позже.

        За входное фото провайдер может брать отдельно, так что цена ролика с
        кадром и без — разные числа, а prepare() ищет кадр в базе. Подставляем
        условный кадр нужных пропорций и считаем теми же compiler.compile и
        pricing.price, что зовёт prepare(). Настоящий запуск уйдёт с настоящей
        картинкой и этой ценой: разойдутся — вьюха ответит price_changed и
        ничего не зарезервирует.
        """
        width, height = _frame_size(prepared.req.params.get("aspect_ratio"))
        stub = compiler.AssetView(uid=STUB_UID, width=width, height=height,
                                  file=f"vstudio/0/{STUB_UID}.jpg",
                                  source=Asset.SOURCE_GENERATED_IMAGE)
        compiled = compiler.compile(
            prepared.caps, prepared.req.kind, prepared.doc,
            [compiler.ResolvedInput(stub, ShotInput.SLOT_FIRST_FRAME)], prepared.req.params,
            site_base=str(getattr(settings, "SITE_BASE_URL", "") or ""),
            inline_refs=bool(getattr(settings, "VSTUDIO_INLINE_REFS", False)))
        price = pricing.price(compiled, prepared.model_obj, prepared.caps, spec=prepared.spec)
        return dataclasses.replace(prepared, compiled=compiled, price=price)

    # ------------------------------------------------------------ печать плана

    def _model_name(self, step: Step) -> str:
        if step.take is not None:
            rows = self._catalog.get(step.kind) or []
            return next((str(r["name"]) for r in rows if r.get("id") == step.take.model_ref),
                        step.take.model_ref)
        return str(step.choice.row["name"]) if step.choice.row else "—"

    def _state(self, track: Track, step: Step) -> str:
        take = step.take
        if take is not None:
            if take.status == Take.STATUS_DONE:
                return "уже снят"
            if take.status in Take.OPEN:
                return "уже снимается"
            return f"не получилось ранее ({take.error_code or take.status})"
        if step in track.todo:
            return "новый"
        if step.blocker:
            return f"нельзя: {step.blocker}"
        if step.part == PART_IMAGE:
            # Сама картинка снялась бы, но ролик под неё запустить нельзя.
            return "не нужна: ролик снять нельзя"
        return f"нельзя: {track.note or 'цена не посчиталась'}"

    def _row(self, track: Track, step: Step) -> list[str]:
        take = step.take
        if take is not None:
            # Закрытый неудачей дубль ничего не стоил: резерв снят вместе с ним.
            credits = (take.credits_charged if take.status == Take.STATUS_DONE
                       else take.credits_reserved if take.status in Take.OPEN else 0)
            cost = str(int(credits)) if credits else "—"
            mode, params = take.mode, _params_text(step.kind, take.effective)
        else:
            cost = "—" if not step.credits else f"{'≈' if step.estimate else ''}{step.credits}"
            mode = step.mode or "—"
            params = _params_text(step.kind, step.params) if step.choice.row else "—"
        label = step.scenario.title if step.part == PART_VIDEO else "исходная картинка"
        return [str(track.position), f"{step.scenario.key} · {label}", self._model_name(step), mode,
                params, cost, self._state(track, step)]

    def _print_plan(self, tracks) -> int:
        """Таблица плана и итог. Возвращает сумму кредитов новых запусков."""
        rows = []
        for track in tracks:
            if track.image is not None and (track.video.take is None or track.image.take is not None):
                rows.append(self._row(track, track.image))
            rows.append(self._row(track, track.video))
        header = ["№", "Сценарий", "Модель", "Режим", "Параметры", "Кредиты", "Состояние"]
        widths = [max(len(line[i]) for line in [header] + rows) for i in range(len(header))]
        self.stdout.write("")
        for line in [header] + rows:
            cells = [cell.rjust(widths[i]) if i in (0, 5) else cell.ljust(widths[i])
                     for i, cell in enumerate(line)]
            self.stdout.write("  ".join(cells).rstrip())

        # Про дубли прошлых запусков объяснять нечего: их модель и параметры уже в таблице.
        planned = [step for track in tracks for step in (track.image, track.video)
                   if step is not None and step.take is None]
        if planned:
            self.stdout.write("")
            self.stdout.write("Модели:")
        for step in planned:
            chosen = f"{step.choice.row['name']} — " if step.choice.row else ""
            tail = f" Пропущено: {'; '.join(step.choice.skipped)}." if step.choice.skipped else ""
            self.stdout.write(f"  {step.name}: {chosen}{step.choice.why}.{tail}")
        notes = [(step.name, text) for step in planned for text in step.changes]
        if notes:
            self.stdout.write("Параметры заменены под модель:")
            for name, text in notes:
                self.stdout.write(f"  {name}: {text}")
        warnings = [(step.name, text) for track in tracks for step in track.todo
                    for text in step.warnings]
        if warnings:
            self.stdout.write("Предупреждения студии (запуску не мешают):")
            for name, text in warnings:
                self.stdout.write(f"  {name}: {text}")

        fresh = [step for track in tracks for step in track.todo]
        total = sum(int(step.credits or 0) for step in fresh)
        videos = sum(1 for step in fresh if step.part == PART_VIDEO)
        self.stdout.write("")
        self.stdout.write(f"К запуску: видео — {videos}, картинок — {len(fresh) - videos}. "
                          f"Всего {total} кр.")
        balance = reserve.balance_snapshot(self._user, total) or {}
        after = int(balance.get("after") or 0)
        enough = f"хватает, останется {after}" if after >= 0 else f"НЕ ХВАТАЕТ {-after}"
        self.stdout.write(f"Баланс: {balance.get('balance')} кр, в резерве {balance.get('reserved')}, "
                          f"свободно {balance.get('available')} — {enough} кр.")
        if any(step.estimate for step in fresh):
            self.stdout.write("≈ — цена ролика с первым кадром посчитана до съёмки самой картинки; "
                              "если она окажется другой, ролик не запустится.")
        return total

    # ------------------------------------------------------------ съёмка

    def _say(self, text: str, style=None) -> None:
        line = f"[{timezone.localtime():%H:%M:%S}] {text}"
        self.stdout.write(style(line) if style else line)

    def _post(self, view_cls, path: str, body: dict) -> tuple[int, dict]:
        """POST во вьюху студии от имени аккаунта: без HTTP, но тем же кодом."""
        request = self._factory.post(API + path, body, format="json")
        force_authenticate(request, user=self._user)
        view = view_cls.as_view()
        if connection.settings_dict.get("ATOMIC_REQUESTS"):
            # Как у обработчика запросов: вьюха целиком в транзакции, задача
            # воркеру уходит только после её фиксации.
            view = transaction.atomic(view)
        response = view(request)
        data = response.data if isinstance(response.data, dict) else {}
        return response.status_code, data

    def _project(self) -> str | None:
        """Один проект на метку: все ролики прогона — в одной ленте студии."""
        if self._project_uid is None:
            title = PROJECT_TITLE.format(label=self._label)
            found = (Project.objects.filter(user=self._user, title=title, is_archived=False)
                     .order_by("-pk").first())
            if found is not None:
                self._project_uid = found.uid
            else:
                status, data = self._post(views.ProjectsView, "projects/", {"title": title})
                # Не создался — не беда: вьюха запуска заведёт проект сама.
                self._project_uid = str(data.get("uid") or "") if status == 201 else ""
        return self._project_uid or None

    def _free_slot(self, kind: str) -> bool:
        # Тот же счёт, что у гейта запуска. Проверяем заранее, чтобы не слать
        # заведомо отклоняемые запросы и не жечь лимит vstudio_run.
        open_n = Take.objects.filter(user=self._user, kind=kind, status__in=Take.OPEN).count()
        return open_n < reserve.max_open(kind)

    def _shoot(self, tracks) -> None:
        self._pending: list[tuple[Track, Step]] = []
        self._waiting: dict[int, tuple[Track, Step, float]] = {}
        self._project_uid = None
        self._hold_until = 0.0
        self._charged = 0
        self._unlisted = 0
        # Сколько работ этого прогона стоит в витрине включёнными и скрытыми — по
        # самим строкам, а не по --publish: строку мог включить владелец в панели.
        self._shown = 0
        self._hidden = 0
        self._crash = None
        self.stdout.write("")
        for track in tracks:
            self._enter(track)

        idle_from = None
        try:
            while self._pending or self._waiting:
                launched = self._launch_ready()
                if not (self._pending or self._waiting):
                    break
                if self._waiting or launched:
                    idle_from = None
                else:
                    # Свои дубли не идут, а запустить нельзя: места заняты чужими
                    # генерациями аккаунта или сработал лимит запросов.
                    now = time.monotonic()
                    idle_from = now if idle_from is None else idle_from
                    if now - idle_from > self._timeout:
                        self._drop_pending("у аккаунта так и не освободилось место для новой генерации")
                        break
                time.sleep(self._poll)
                self._check_waiting()
        except KeyboardInterrupt:
            self._say("Остановлено. Запущенные дубли воркер доснимет; запустите команду ещё раз с "
                      "той же меткой — она их подхватит и поставит в витрину.", self.style.WARNING)
            self._leave_open()
        except Exception as exc:
            # Сбой не про сценарий (база, кэш под лимитом запросов): вьюха зовётся
            # напрямую, и то, что по HTTP было бы одним 500, оборвало бы прогон без
            # итога. Вслепую дальше не тратим, но что запущено — говорим.
            self._crash = exc
            self._say(f"Сбой: {_error_text(exc)}. Новые запуски остановлены; запущенные дубли "
                      "воркер доснимет — запустите команду ещё раз с той же меткой.",
                      self.style.ERROR)
            self._leave_open()

    def _leave_open(self) -> None:
        """Прогон оборван: начатое доснимет воркер, остальное осталось незапущенным."""
        for track, _step, _started in self._waiting.values():
            track.outcome = TIMED_OUT
        for track, _step in self._pending:
            track.outcome = NOT_STARTED

    def _enter(self, track: Track) -> None:
        video, image = track.video, track.image
        if video.take is not None:
            self._settle(track, video, video.take, before=True)
        elif image is not None and image.take is not None:
            self._settle(track, image, image.take, before=True)
        elif track.todo:
            self._pending.append((track, track.todo[0]))
        else:
            track.outcome = SKIPPED
            self._say(f"{track.scenario.key}: пропущен — {track.note or 'запустить нельзя'}",
                      self.style.WARNING)

    def _launch_ready(self) -> bool:
        if time.monotonic() < self._hold_until:
            return False
        launched = False
        for entry in list(self._pending):
            track, step = entry
            if not self._free_slot(step.kind):
                continue
            verdict = self._launch(track, step)
            if verdict == RETRY:
                break
            self._pending.remove(entry)
            if verdict == STOP:
                track.outcome = NOT_STARTED
                self._drop_pending("новые запуски остановлены")
                break
            launched = launched or verdict == LAUNCHED
        return launched

    def _launch(self, track: Track, step: Step) -> str:
        inputs = []
        if step.part == PART_VIDEO and track.image is not None:
            inputs = self._frame_inputs(track.image.take) if track.image.take is not None else []
            if not inputs:
                # Без кадра ушёл бы обычный ролик по тексту — не тот сценарий за те же деньги.
                track.outcome = FAILED
                self._say(f"{step.name}: не запущен — у исходной картинки нет файла", self.style.ERROR)
                return DROPPED
        body = {**self._body(step, inputs, self._project()),
                "quoted_credits": step.credits, "client_request_id": step.cid}
        status, data = self._post(views.ShotsView, "shots/", body)
        code = str(data.get("error_code") or "")
        if status in (200, 202):
            uid = (data.get("take") or {}).get("uid")
            take = (Take.objects.filter(user=self._user, uid=uid).select_related("result_asset").first()
                    if uid else None)
            if take is None:
                track.outcome = FAILED
                self._say(f"{step.name}: запуск ответил без дубля — проверьте ленту студии",
                          self.style.ERROR)
                return DROPPED
            step.take = take
            if status == 202:
                self._say(f"{step.name}: запущен — {self._model_name(step)}, в резерве "
                          f"{take.credits_reserved} кр, дубль {take.uid}")
                self._waiting[take.pk] = (track, step, time.monotonic())
            else:
                # Этот клик уже был (вторая копия команды): берём его дубль.
                self._settle(track, step, take, before=True)
            return LAUNCHED
        if code == "too_many_open":
            return RETRY
        if status == 429:
            self._hold_until = time.monotonic() + float(data.get("wait") or self._poll)
            return RETRY
        text = _refusal_text(data) or f"HTTP {status}"
        if status == 402 or code in STOP_CODES:
            self._say(f"{step.name}: запуск отклонён ({code or status}) — {text}", self.style.ERROR)
            return STOP
        track.outcome = SKIPPED
        if code == "price_changed":
            self._say(f"{step.name}: не запущен — цена изменилась: в плане {step.credits} кр, сейчас "
                      f"{data.get('credits')} кр. Посмотрите план заново (--dry-run) и повторите.",
                      self.style.WARNING)
        else:
            self._say(f"{step.name}: запуск отклонён ({code or status}) — {text}", self.style.ERROR)
        return DROPPED

    def _drop_pending(self, reason: str) -> None:
        for track, step in self._pending:
            track.outcome = NOT_STARTED
            self._say(f"{step.name}: не запущен — {reason}", self.style.WARNING)
        self._pending.clear()

    def _check_waiting(self) -> None:
        takes = {take.pk: take for take in
                 Take.objects.filter(pk__in=list(self._waiting)).select_related("result_asset")}
        for pk, (track, step, started) in list(self._waiting.items()):
            take = takes.get(pk)
            if take is None:
                del self._waiting[pk]
                track.outcome = FAILED
                self._say(f"{step.name}: дубль пропал из базы", self.style.ERROR)
            elif take.status in Take.CLOSED:
                del self._waiting[pk]
                self._settle(track, step, take, before=False)
            elif time.monotonic() - started > self._timeout:
                del self._waiting[pk]
                track.outcome = TIMED_OUT
                self._say(f"{step.name}: не дождались за {self._timeout} с — дубль {take.uid} ещё "
                          "снимается. Запустите команду ещё раз с той же меткой: она его подхватит.",
                          self.style.WARNING)

    def _settle(self, track: Track, step: Step, take: Take, *, before: bool) -> None:
        """Дубль шага найден или закрылся: ждать, идти дальше или отчитаться.

        before — дубль уже был в этом состоянии до запуска команды (прошлый
        прогон с той же меткой).
        """
        step.take = take
        if take.status in Take.OPEN:
            self._say(f"{step.name}: уже снимается (дубль {take.uid}) — ждём")
            self._waiting[take.pk] = (track, step, time.monotonic())
            return
        if take.status != Take.STATUS_DONE:
            track.outcome = FAILED
            code = take.error_code or take.status
            if before:
                self._say(f"{step.name}: в прошлый раз не получилось ({code}). Переснять: "
                          f"--only {track.scenario.key} --label <новая метка>", self.style.WARNING)
            else:
                self._say(f"{step.name}: не получилось ({code}) — {take.error or 'без пояснения'} "
                          "Резерв снят.", self.style.ERROR)
            return
        if not before:
            self._charged += int(take.credits_charged or 0)
        spent = "снят ранее" if before else f"готов, списано {int(take.credits_charged or 0)} кр"
        if step.part == PART_IMAGE:
            self._say(f"{step.name}: {spent} — идёт первым кадром в ролик")
            self._queue_video(track)
            return
        track.outcome = READY_BEFORE if before else SHOT
        self._say(f"{step.name}: {spent}; {self._to_showcase(track, take)}", self.style.SUCCESS)

    def _queue_video(self, track: Track) -> None:
        video = track.video
        if not video.runnable:
            track.outcome = SKIPPED
            self._say(f"{video.name}: пропущен — {video.blocker or 'цена не посчиталась'}",
                      self.style.WARNING)
            return
        self._pending.append((track, video))
        # Ролик встаёт на своё место в очереди, а не в хвост.
        self._pending.sort(key=lambda entry: entry[0].position)

    def _to_showcase(self, track: Track, take: Take) -> str:
        """Поставить готовый ролик в витрину; возвращает, чем кончилось, словами."""
        sc = track.scenario
        active, note = self._publish, ""
        try:
            # Только карусель: работа, перенесённая в «Тренды», сохраняет свой сценарий,
            # но его место в карусели уже пустое.
            if active and (ShowcaseItem.objects.filter(category=sc.key, is_active=True,
                                                       placement=ShowcaseItem.PLACEMENT_REEL)
                           .exclude(take=take).exists()):
                # Работу, которая уже показывается, не подменяем: какая лучше,
                # владелец решит в панели.
                active = False
                note = " — в сценарии уже есть включённая работа, новая оставлена скрытой"
            item, created = showcase.add(
                {"take": take.uid, "title": sc.title, "category": sc.key, "sort": sort_for(sc.key),
                 "placement": ShowcaseItem.PLACEMENT_REEL, "show_prompt": True, "is_active": active},
                actor=self._user)
        except Exception as exc:
            # Ролик снят и оплачен: сбой витрины не должен обрывать остальные сценарии.
            self._unlisted += 1
            detail = getattr(exc, "detail", None) or f"{type(exc).__name__}: {exc}"
            return (f"в витрину НЕ поставлен ({detail}) — запустите команду ещё раз с той же "
                    f"меткой или поставьте дубль {take.uid} в панели")
        if item.is_active:
            self._shown += 1
        else:
            self._hidden += 1
        shown = "показывается" if item.is_active else "скрыт"
        if not created:
            # Строку, которая уже стоит, не трогаем: скрыть её мог и сам владелец.
            hint = (" — --publish уже стоящую строку не включает, включите в панели"
                    if self._publish and not item.is_active else "")
            return f"уже в витрине, № {item.pk} ({shown}){hint}"
        return f"в витрине № {item.pk} ({shown}){note}"

    # ------------------------------------------------------------ итог

    def _print_summary(self, tracks) -> None:
        count = {name: sum(1 for t in tracks if t.outcome == name)
                 for name in (SHOT, READY_BEFORE, FAILED, SKIPPED, NOT_STARTED, TIMED_OUT)}
        parts = [f"снято — {count[SHOT]}", f"не получилось — {count[FAILED]}"]
        for name, text in ((READY_BEFORE, "были сняты раньше"), (SKIPPED, "пропущено"),
                           (NOT_STARTED, "не запущено"), (TIMED_OUT, "не дождались")):
            if count[name]:
                parts.append(f"{text} — {count[name]}")
        if self._unlisted:
            parts.append(f"не встали в витрину — {self._unlisted}")
        try:
            balance = reserve.balance_snapshot(self._user) or {}
            money = f"Баланс: {balance.get('balance')} кр, в резерве {balance.get('reserved')}."
        except Exception:
            # После сбоя базы баланс может не прочитаться; итог нужнее, и первую
            # ошибку эта заслонить не должна.
            money = "Баланс: не прочитан."
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"Итог: {', '.join(parts)}. Списано за этот запуск: {self._charged} кр. {money}"))
        if self._shown or self._hidden:
            self.stdout.write(f"В витрине: показываются — {self._shown}, скрыты — {self._hidden}. "
                              "Посмотреть и включить: /admin-new/vstudio-showcase")
        failed = ",".join(t.scenario.key for t in tracks if t.outcome == FAILED)
        if failed:
            self.stdout.write(f"Переснять неудачные: --only {failed} --label <новая метка>")
        unfinished = ",".join(t.scenario.key for t in tracks if t.outcome in (NOT_STARTED, TIMED_OUT))
        if unfinished:
            self.stdout.write(f"Доснять остальное: та же команда с той же меткой (--only {unfinished}).")

"""Цены legacy → markup по всем активным моделям: таблица на подпись перед переключением.

Владелец переключает режим цен в админке, а прежде должен увидеть, что станет с
каждой ценой (PLAN §2.7, §6.6). Команда ничего не меняет: считает те же функции,
что списание, в обоих режимах — с сохранёнными настройками или с теми, что
переданы флагами (их можно примерить, не сохраняя).

Что в таблице: видео — 480p/720p/1080p × 5/10/15 с, притянутые к тому, что модель
умеет (так же, как при генерации); картинка — одна и одна с фото-референсом;
текст — сообщение в 2000 токенов; сцена мультфильма — на каждую видеомодель.

  python manage.py price_preview
  python manage.py price_preview --csv > prices.csv
  python manage.py price_preview --markup-pct 30 --floor-pct 20 --kgs-per-usd 87.5
  python manage.py price_preview --kind video --model bytedance/seedance-2.0
"""
from __future__ import annotations

import csv
from collections import Counter
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from ai import pricing
from ai.models import GPTModels

# Порядок групп в таблице.
KINDS = ("video", "cartoon", "image", "text")
KIND_LABELS = {"video": "видео", "image": "картинка", "text": "текст", "cartoon": "мультфильм"}
FLAG_LABELS = {"no_cost": "нет себестоимости", "floor": "ниже порога", "estimate": "оценка",
               "frame_no_cost": "кадр без себестоимости", "chat_tokens": "в чате по токенам",
               "chat_one_ref": "в чате как с 1 фото"}
VIDEO_RESOLUTIONS = ("480p", "720p", "1080p")
VIDEO_SECONDS = (5, 10, 15)
RES_ORDER = {"480p": 0, "720p": 1, "768p": 2, "1080p": 3}
TEXT_TOKENS = 2000
CARTOON_ASPECT = "16:9"
CARTOON_FRAME_ID = "google/gemini-2.5-flash-image"
CSV_FIELDS = ("model_id", "model", "kind", "shape", "cost_usd", "legacy", "markup", "delta_pct", "flags")


def _cost(value) -> str:
    if value is None:
        return ""
    return pricing.plain(Decimal(str(value)).quantize(Decimal("0.0001")))


def _delta(legacy, markup) -> int | None:
    if legacy is None or markup is None or not legacy:
        return None
    return round((markup - legacy) * 100 / legacy)


class Command(BaseCommand):
    help = "Цены legacy → markup по всем активным моделям (markdown или --csv)"

    def add_arguments(self, parser):
        parser.add_argument("--csv", action="store_true", help="CSV вместо markdown")
        parser.add_argument("--markup-pct", default=None, help="Общая наценка, %% (без сохранения)")
        parser.add_argument("--floor-pct", default=None, help="Нижний порог, %% (без сохранения)")
        parser.add_argument("--kgs-per-usd", default=None,
                            help="Курс сом/$ (без сохранения); live — живой курс")
        parser.add_argument("--kind", choices=KINDS, action="append", default=None,
                            help="Только эти виды строк (можно несколько раз)")
        parser.add_argument("--model", action="append", default=None,
                            help="Только эта модель, openrouter_id (можно несколько раз)")

    def handle(self, *args, **opts):
        cfg = self._config(opts)
        kinds = set(opts.get("kind") or KINDS)
        models = GPTModels.objects.filter(is_active=True).order_by("sort_order", "id")
        if opts.get("model"):
            models = models.filter(openrouter_id__in=opts["model"])
        self.frame_model = self._find_frame_model() if "cartoon" in kinds else None
        with pricing.override_config(cfg):
            groups: dict[str, list] = {kind: [] for kind in KINDS}
            for model in models:
                self._model_rows(model, cfg, kinds, groups)
            rows = [row for kind in KINDS for row in groups[kind]]
            if opts.get("csv"):
                self._write_csv(rows)
            else:
                self._write_markdown(rows, cfg)

    # ---------------------------------------------------------------- настройки

    @staticmethod
    def _config(opts) -> pricing.PricingConfig:
        changes = {}
        try:
            if opts.get("markup_pct") is not None:
                changes["markup_pct"] = pricing.parse_pct(opts["markup_pct"], what="Наценка")
            if opts.get("floor_pct") is not None:
                changes["floor_pct"] = pricing.parse_pct(opts["floor_pct"], what="Нижний порог")
            rate = opts.get("kgs_per_usd")
            if rate is not None:
                changes["kgs_per_usd"] = None if str(rate).strip().lower() == "live" else pricing.parse_rate(rate)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        return pricing.stored_config().with_changes(**changes)

    # ---------------------------------------------------------------- строки

    def _model_rows(self, model, cfg, kinds: set, groups: dict) -> None:
        category = str(model.category or "")
        if category == "video":
            if "video" in kinds:
                groups["video"] += self._video_rows(model, cfg)
            if "cartoon" in kinds:
                groups["cartoon"].append(self._cartoon_row(model, cfg))
        elif category == "image":
            if "image" in kinds:
                for refs in (0, 1):
                    sample = pricing.model_sample(model, cfg=cfg, refs=refs)
                    row = self._row(model, "image", sample)
                    row["flags"] += self._chat_flags(model, cfg, sample)
                    groups["image"].append(row)
        elif "text" in kinds:
            groups["text"].append(self._row(model, "text", pricing.model_sample(model, cfg=cfg,
                                                                                tokens=TEXT_TOKENS)))

    def _video_rows(self, model, cfg) -> list[dict]:
        from ai.handlers import _openrouter_config, _openrouter_video_catalog, _video_model_params

        spec = _openrouter_video_catalog(model.openrouter_id) or {}
        shapes = [(5, "720p")]
        if spec:
            or_cfg = _openrouter_config()
            shapes = []
            # Качеств в каталоге нет (Runway) — модель их не различает, хватит одного.
            for res in (VIDEO_RESOLUTIONS if spec.get("supported_resolutions") else ("720p",)):
                for seconds in VIDEO_SECONDS:
                    snapped = _video_model_params(model.openrouter_id, or_cfg, seconds, res)
                    shape = (int(snapped["duration"]), str(snapped["resolution"]))
                    if shape not in shapes:
                        shapes.append(shape)
            shapes.sort(key=lambda s: (RES_ORDER.get(s[1].lower(), 9), s[1], s[0]))
        return [self._row(model, "video", pricing.model_sample(model, cfg=cfg, spec=spec, seconds=seconds,
                                                               resolution=res))
                for seconds, res in shapes]

    def _cartoon_row(self, video_model, cfg) -> dict:
        """Сцена мультфильма на этой видеомодели: кадр + 5 с 720p в 16:9, без ручной цены."""
        from cartoon.pricing import scene_sample

        return self._row(video_model, "cartoon", scene_sample(video_model, self.frame_model, aspect=CARTOON_ASPECT,
                                                              cfg=cfg))

    @staticmethod
    def _find_frame_model():
        """Модель кадра мультфильма: самая частая у активных сцен, иначе Nano Banana."""
        from cartoon.models import CartoonPreset

        counts = Counter(CartoonPreset.objects.filter(is_active=True)
                         .values_list("image_model_id", flat=True))
        frame = GPTModels.objects.filter(pk=counts.most_common(1)[0][0]).first() if counts else None
        return frame or GPTModels.objects.filter(openrouter_id=CARTOON_FRAME_ID).first()

    @staticmethod
    def _chat_flags(model, cfg, sample: pricing.Sample) -> list[str]:
        """Чат списывает эту картинку в режиме markup не по цене строки (ai.pricing.chat_image_price)."""
        chat = pricing.chat_image_price(model, cfg=cfg.with_changes(mode=pricing.MODE_MARKUP))
        if sample.markup is None or chat.credits == sample.markup:
            return []
        return ["chat_tokens"] if chat.billing == "tokens" else ["chat_one_ref"]

    @staticmethod
    def _row(model, kind: str, sample: pricing.Sample) -> dict:
        flags = list(sample.flags)
        # Себестоимость картинки задана в «Моделях» по прайсу, а OpenRouter считает
        # картинки по мегапикселям и токенам: до сверки с журналом это оценка.
        if kind == "image" and sample.cost_usd is not None and "estimate" not in flags:
            flags.append("estimate")
        return {"model_id": model.openrouter_id, "model": model.name, "kind": kind,
                "shape": sample.shape, "cost_usd": sample.cost_usd, "legacy": sample.legacy,
                "markup": sample.markup, "delta_pct": _delta(sample.legacy, sample.markup), "flags": flags}

    # ---------------------------------------------------------------- вывод

    @staticmethod
    def _shape_text(kind: str, shape: dict) -> str:
        if kind == "video":
            return f"{shape['seconds']} с · {shape['resolution']} · {shape.get('aspect') or '—'}"
        if kind == "cartoon":
            return f"сцена {shape['seconds']} с · {shape['resolution']} · {shape['aspect']}"
        if kind == "image":
            return "1 картинка" + (f" + {shape['refs']} фото" if shape.get("refs") else "")
        return f"{shape['tokens']} токенов"

    def _write_csv(self, rows: list[dict]) -> None:
        writer = csv.writer(self.stdout, lineterminator="\n")
        writer.writerow(CSV_FIELDS)
        for row in rows:
            writer.writerow([row["model_id"], row["model"], row["kind"], self._shape_text(row["kind"], row["shape"]),
                             _cost(row["cost_usd"]), "" if row["legacy"] is None else row["legacy"],
                             "" if row["markup"] is None else row["markup"],
                             "" if row["delta_pct"] is None else row["delta_pct"], ";".join(row["flags"])])

    def _write_markdown(self, rows: list[dict], cfg) -> None:
        snap = pricing.settings_snapshot(cfg)
        basis = snap["basis"]
        rate = (f"{snap['kgs_per_usd']} сом/$ (закреплён; живой {snap['live_kgs_per_usd'] or '—'})"
                if snap["kgs_per_usd"] else f"{snap['live_kgs_per_usd'] or '—'} сом/$ (живой)")
        out = self.stdout
        out.write("# Цены: legacy → markup\n\n")
        out.write(f"Сейчас действует: {pricing.stored_config().mode}. Наценка {snap['markup_pct']} %, "
                  f"порог {snap['floor_pct']} %, курс {rate}.\n")
        if basis:
            per_credit = f"{basis['kgs_per_credit']} сом = " if basis["kgs_per_credit"] else ""
            out.write(f"Кредит: {basis['package']} · {per_credit}${basis['credit_usd']}.\n")
        else:
            out.write("Кредит: нет ни одного пакета с ценой — по себестоимости цен нет.\n")
        if snap["rate_warning"]:
            out.write("Внимание: живой курс слабее закреплённого больше чем на 2 % — цены занижены.\n")
        out.write("\n| Модель | Вид | Генерация | Себестоимость, $ | legacy | markup | Δ | Флаги |\n"
                  "|---|---|---|---|---|---|---|---|\n")
        for row in rows:
            delta = "" if row["delta_pct"] is None else f"{row['delta_pct']:+d} %".replace("-", "−")
            flags = ", ".join(FLAG_LABELS.get(f, f) for f in row["flags"])
            out.write(f"| {row['model']} (`{row['model_id']}`) | {KIND_LABELS[row['kind']]} | "
                      f"{self._shape_text(row['kind'], row['shape'])} | {_cost(row['cost_usd']) or '—'} | "
                      f"{'—' if row['legacy'] is None else row['legacy']} | "
                      f"{'—' if row['markup'] is None else row['markup']} | {delta} | {flags} |\n")
        out.write(
            "\nФлаги: «нет себестоимости» — видео в режиме markup не продаётся (отказ), картинка остаётся "
            "по прежней цене; «ниже порога» — наценка модели меньше порога, цену держит порог; "
            "«оценка» — себестоимость картинки задана в «Моделях» по прайсу, сверьте с журналом генераций; "
            "«кадр без себестоимости» — кадр сцены по прежней цене; «в чате по токенам» — в чате картинка "
            "списывается тарифом модели за токены, и он не даёт цену строки: наценку до чата доводит действие "
            "«Пересчитать тариф картинок в чате» в «Моделях»; «в чате как "
            "с 1 фото» — чат пока не сообщает число приложенных фото и берёт за правку как с одним.\n"
            "Текст в обоих режимах списывается тарифом: он меняется только действием «Пересчитать тарифы "
            "текста». Сцена мультфильма — без ручной цены пресета; в режиме markup ручная цена и «цена "
            "сцены» из админки не действуют.\n")
        overrides = self._manual_presets()
        if overrides:
            out.write(f"Сцен с ручной ценой: {overrides} — в режиме markup она не действует.\n")

    @staticmethod
    def _manual_presets() -> int:
        from cartoon.models import CartoonPreset

        return CartoonPreset.objects.filter(is_active=True, credits_override__isnull=False).exclude(
            credits_override=0).count()

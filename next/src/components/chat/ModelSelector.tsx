"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  FiChevronDown, FiCheck, FiLock, FiSearch, FiX, FiEye, FiCpu, FiGlobe, FiImage,
  FiStar, FiMessageCircle, FiEdit3, FiCode, FiZap, FiDollarSign, FiGift,
  FiVideo, FiFilm, FiAward, FiSmartphone,
} from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";

export type AiModel = {
  id: number | string;
  name: string;
  openrouter_id?: string;
  description?: string;
  sort_order?: number;
  /** free for the current tier (selectable by everyone) */
  is_free?: boolean;
  /** premium model the current user cannot use on their tier */
  locked?: boolean;
  /** per-model price multiplier (informational) */
  markup_coefficient?: number;
  /** модель принимает изображения (vision) */
  supports_vision?: boolean;
  /** группа по назначению (chat/writing/coding/... из админки) */
  category?: string;
  /** показывать в «⭐ Рекомендуемые» наверху */
  recommended?: boolean;
};

const LS_MODEL = "esai-model";

type Props = {
  value?: string; // currently selected model identifier (openrouter_id || id)
  onChange: (modelId: string, model: AiModel) => void;
  className?: string;
  /** не используется (оставлено для обратной совместимости со старым дропдауном) */
  menuDirection?: "up" | "down";
};

// Вендор → отображаемое имя + акцентный цвет точки. Ключ = первый сегмент
// openrouter_id (openai/gpt-4o → "openai").
const PROVIDERS: Record<string, { label: string; color: string }> = {
  openai: { label: "OpenAI", color: "#10a37f" },
  anthropic: { label: "Anthropic", color: "#d97757" },
  google: { label: "Google", color: "#4285f4" },
  deepseek: { label: "DeepSeek", color: "#4d6bfe" },
  "x-ai": { label: "xAI", color: "#9ca3af" },
  perplexity: { label: "Perplexity", color: "#20b8cd" },
  mistralai: { label: "Mistral", color: "#fa520f" },
  "meta-llama": { label: "Meta", color: "#0668e1" },
  qwen: { label: "Qwen", color: "#615ced" },
  moonshotai: { label: "Moonshot", color: "#1fb6ad" },
  "z-ai": { label: "Z.AI", color: "#3859ff" },
  minimax: { label: "MiniMax", color: "#f23f5d" },
  nvidia: { label: "NVIDIA", color: "#76b900" },
  microsoft: { label: "Microsoft", color: "#00a4ef" },
  cohere: { label: "Cohere", color: "#ff7759" },
  amazon: { label: "Amazon", color: "#ff9900" },
};

function providerKey(m: AiModel): string {
  const id = (m.openrouter_id || "").toLowerCase();
  const seg = id.split("/")[0];
  return PROVIDERS[seg] ? seg : "other";
}
function providerColor(m: AiModel): string {
  return PROVIDERS[providerKey(m)]?.color || "#9ca3af";
}

// Группы по НАЗНАЧЕНИЮ (просьба клиента: «чтоб людям было понятно»).
// category приходит из админки (GPTModels.category); порядок фиксированный.
// Иконки — SVG из react-icons (по просьбе клиента вместо эмодзи), каждой — свой цвет.
// label теперь резолвится через t() в компоненте (см. groups useMemo); здесь
// оставлены defaultValue-строки как fallback для порядка/иконок.
// Виртуальные группы — не приходят из админки как category, а собираются по
// флагам модели (см. groups useMemo). categoryKey() их игнорирует, иначе
// модель с такой category попала бы в группу дважды.
const VIRTUAL_CATEGORY_KEYS = ["free", "recommended"];

const CATEGORIES: Array<{ key: string; label: string; icon: React.ReactNode }> = [
  { key: "free", label: "Бесплатные", icon: <FiGift className="text-emerald-400" /> }, // виртуальная (is_free=true), просьба клиента — в самом верху
  { key: "recommended", label: "Рекомендуемые", icon: <FiStar className="text-amber-400" /> }, // виртуальная (recommended=true)
  { key: "chat", label: "Для общения", icon: <FiMessageCircle className="text-sky-400" /> },
  { key: "writing", label: "Тексты и SEO", icon: <FiEdit3 className="text-teal-400" /> },
  { key: "coding", label: "Программирование", icon: <FiCode className="text-violet-400" /> },
  { key: "reasoning", label: "Анализ и рассуждения", icon: <FiCpu className="text-purple-400" /> },
  { key: "search", label: "Поиск в интернете", icon: <FiGlobe className="text-cyan-400" /> },
  { key: "image", label: "Изображения", icon: <FiImage className="text-emerald-400" /> },
  { key: "video", label: "Видео", icon: <FiVideo className="text-rose-400" /> },
  { key: "fast", label: "Быстрые", icon: <FiZap className="text-yellow-400" /> },
  { key: "budget", label: "Экономичные", icon: <FiDollarSign className="text-lime-400" /> },
];

function categoryKey(m: AiModel): string {
  const c = (m.category || "").toLowerCase();
  if (CATEGORIES.some((x) => x.key === c && !VIRTUAL_CATEGORY_KEYS.includes(c))) return c;
  // Фолбэк для моделей без категории: image-генераторы → image, остальные → chat.
  return isImageGen(m) ? "image" : "chat";
}
function isReasoning(m: AiModel): boolean {
  const id = (m.openrouter_id || "").toLowerCase();
  return /(^|\/|-)r1(\b|$)|reason|(^|\/)o[13]\b/.test(id);
}
function isWeb(m: AiModel): boolean {
  const id = (m.openrouter_id || "").toLowerCase();
  return id.includes("perplexity") || id.includes("sonar");
}
function isImageGen(m: AiModel): boolean {
  // Категория из админки — источник истины (как у видео). Раньше смотрели
  // только на id, и модель, у которой в админке стоит «Изображения», а в id
  // слова "image" нет, попадала в группу «Изображения», но фильтром «Текст»
  // при этом считалась текстовой — группа была, а моделей в ней не было.
  if ((m.category || "").toLowerCase() === "image") return true;
  // google/gemini-2.5-flash-image → второй сегмент содержит "image" = генерация картинок
  const id = (m.openrouter_id || "").toLowerCase();
  const seg = id.split("/")[1] || "";
  return seg.includes("image");
}
function isVideoGen(m: AiModel): boolean {
  return (m.category || "").toLowerCase() === "video";
}

// Текстовая модель = всё, что не рисует картинки и не снимает видео.
function isTextModel(m: AiModel): boolean {
  return !isImageGen(m) && !isVideoGen(m);
}

/**
 * Фильтры по ВОЗМОЖНОСТЯМ — нижний ряд палитры. Раньше это была просто
 * легенда-подсказка «что означают значки»; клиент попросил сделать её
 * кликабельной: нажал «Видео» — в списке остались только видео-модели.
 *
 * Несколько фильтров можно держать включёнными одновременно, они работают по
 * ИЛИ (Картинки + Видео = всё, что генерирует медиа). Иконки и цвета те же,
 * что у бейджей справа от названия модели, — значок в чипе и значок у модели
 * читаются как одно и то же.
 */
const CAP_FILTERS: Array<{
  key: string;
  i18nKey: string;
  label: string;
  cls: string;
  icon: React.ReactNode;
  match: (m: AiModel) => boolean;
}> = [
  { key: "text", i18nKey: "chat.model.cap_text_short", label: "Текст", cls: "text-sky-400", icon: <FiMessageCircle />, match: isTextModel },
  { key: "vision", i18nKey: "chat.model.cap_vision_short", label: "Фото", cls: "text-blue-400", icon: <FiEye />, match: (m) => !!m.supports_vision },
  { key: "image", i18nKey: "chat.model.cap_image_short", label: "Картинки", cls: "text-emerald-400", icon: <FiImage />, match: isImageGen },
  { key: "video", i18nKey: "chat.model.cap_video_short", label: "Видео", cls: "text-rose-400", icon: <FiVideo />, match: isVideoGen },
  { key: "reasoning", i18nKey: "chat.model.cap_reasoning_short", label: "Рассуждение", cls: "text-purple-400", icon: <FiCpu />, match: isReasoning },
  { key: "web", i18nKey: "chat.model.cap_web_short", label: "Веб", cls: "text-amber-400", icon: <FiGlobe />, match: isWeb },
];

// «Качество» video-модели под названием (просьба клиента: SVG вместо эмодзи).
// Иконка подбирается по ТОЧНОМУ тексту description из админки; неизвестный
// текст — просто текст без иконки.
// Иконки того же приглушённого голубого, что и текст (#5DA3F0) — единый спокойный
// акцент, без пёстрых цветов и без розовой «плёнки», которая читалась красноватой.
const VQ_COLOR = "#5DA3F0";
// Ключи = ТОЧНЫЙ description из админки (всегда ru) → иконка. Это lookup-контракт
// с m.description, поэтому ключи НЕ переводим. Отображаемый текст качества
// локализуется отдельно в videoQualityLabel() ниже.
const VIDEO_QUALITY_ICONS: Record<string, React.ReactNode> = {
  "Быстрая генерация": <FiZap style={{ color: VQ_COLOR }} />,
  "Лучший баланс": <FiStar style={{ color: VQ_COLOR }} />,
  "Реалистичное видео": <FiFilm style={{ color: VQ_COLOR }} />,
  "Максимальное качество": <FiAward style={{ color: VQ_COLOR }} />,
  "Для соцсетей": <FiSmartphone style={{ color: VQ_COLOR }} />,
};
// description (ru из админки) → i18n-ключ качества видео. Неизвестный текст
// показывается как есть.
const VIDEO_QUALITY_I18N: Record<string, { key: string; def: string }> = {
  "Быстрая генерация": { key: "chat.model.video_quality.fast", def: "Быстрая генерация" },
  "Лучший баланс": { key: "chat.model.video_quality.balanced", def: "Лучший баланс" },
  "Реалистичное видео": { key: "chat.model.video_quality.realistic", def: "Реалистичное видео" },
  "Максимальное качество": { key: "chat.model.video_quality.max", def: "Максимальное качество" },
  "Для соцсетей": { key: "chat.model.video_quality.social", def: "Для соцсетей" },
};

/**
 * ModelSelector — кнопка + модальная палитра выбора модели (как у конкурентов):
 * поиск, группировка по вендору, бейджи возможностей (vision/reasoning/web),
 * замок на премиум для гостя/free (ведёт на /pricing). Центрированная модалка
 * вместо дропдауна — нет проблем с направлением/клавиатурой на мобайле.
 */
export default function ModelSelector({ value, onChange, className }: Props) {
  const { t } = useTranslation("common");
  const router = useRouter();
  const [models, setModels] = useState<AiModel[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [lockedHint, setLockedHint] = useState<string | null>(null);
  // Включённые фильтры возможностей из нижнего ряда (пусто = показываем всё).
  const [caps, setCaps] = useState<string[]>([]);
  const searchRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  const modelKey = (m: AiModel) => String(m.openrouter_id || m.id);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // auth=true: бэк считает locked по тиру пользователя (иначе всё премиум).
        const res = await fetchData<AiModel[]>("ai/models/", "GET", null, true);
        if (cancelled) return;
        const list = Array.isArray(res?.data) ? res.data : [];
        list.sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));
        setModels(list);
        if (list.length) {
          let stored = "";
          try { stored = localStorage.getItem(LS_MODEL) || ""; } catch {}
          const storedModel = list.find((m) => modelKey(m) === stored);
          const firstFree = list.find((m) => !m.locked) || list[0];
          const chosen = storedModel && !storedModel.locked ? storedModel : firstFree;
          if (!value) onChange(modelKey(chosen), chosen);
        }
      } catch {
        if (!cancelled) setModels([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Esc закрывает; при открытии фокус в поиск и сброс запроса.
  useEffect(() => {
    if (!open) return;
    setQuery("");
    setCaps([]);
    setLockedHint(null);
    const tmr = setTimeout(() => searchRef.current?.focus(), 30);
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("keydown", onKey);
    document.body.classList.add("overflow-hidden");
    return () => {
      clearTimeout(tmr);
      document.removeEventListener("keydown", onKey);
      document.body.classList.remove("overflow-hidden");
    };
  }, [open]);

  const current = models.find((m) => modelKey(m) === value);
  const label =
    current?.name ||
    (loading ? t("common.loading", { defaultValue: "Загрузка..." }) : t("chat.model.select", { defaultValue: "Выбрать модель" }));

  // Фильтр + группировка по НАЗНАЧЕНИЮ (⭐ Рекомендуемые сверху, порядок групп
  // фиксированный; внутри группы — sort_order). Точка у модели — цвет вендора.
  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const active = CAP_FILTERS.filter((f) => caps.includes(f.key));
    // Фильтры по возможностям работают по ИЛИ: «Картинки + Видео» = всё, что
    // генерирует медиа, а не пересечение (такого зверя не бывает).
    const byCaps = active.length
      ? models.filter((m) => active.some((f) => f.match(m)))
      : models;
    const filtered = q
      ? byCaps.filter((m) => (m.name || "").toLowerCase().includes(q) || (m.openrouter_id || "").toLowerCase().includes(q))
      : byCaps;
    // Дубли в «Бесплатных»/«Рекомендуемых» уместны только в обычном списке.
    // Когда пользователь сузил выборку (поиск или фильтр), одна и та же модель
    // в двух местах читается как «нашлось два раза».
    const narrowed = Boolean(q) || active.length > 0;
    const byKey: Record<string, AiModel[]> = {};
    for (const m of filtered) {
      const k = categoryKey(m);
      (byKey[k] = byKey[k] || []).push(m);
      // Бесплатные и рекомендуемые дублируются в верхних группах (как у ChatGPT).
      // «Бесплатные» идут первыми (просьба клиента).
      if (m.is_free && !narrowed) (byKey.free = byKey.free || []).push(m);
      if (m.recommended && !narrowed) (byKey.recommended = byKey.recommended || []).push(m);
    }
    return CATEGORIES
      .filter((c) => (byKey[c.key] || []).length > 0)
      .map((c) => ({
        key: c.key,
        label: t(`chat.model.category.${c.key}`, { defaultValue: c.label }),
        icon: c.icon,
        items: byKey[c.key],
      }));
  }, [models, query, caps, t]);

  const select = (m: AiModel) => {
    if (m.locked) {
      setLockedHint((prev) => (prev === modelKey(m) ? null : modelKey(m)));
      return;
    }
    const key = modelKey(m);
    try { localStorage.setItem(LS_MODEL, key); } catch {}
    onChange(key, m);
    setOpen(false);
  };

  const Badge = ({ icon, title, cls }: { icon: React.ReactNode; title: string; cls: string }) => (
    <span title={title} className={`inline-flex items-center justify-center ${cls}`}>{icon}</span>
  );

  return (
    <div className={`relative ${className || ""}`}>
      <button
        type="button"
        onClick={() => setOpen(true)}
        disabled={loading && models.length === 0}
        className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-2 hover:border-accent/60 text-foreground text-sm px-3 py-1.5 transition-colors cursor-pointer disabled:opacity-60"
        title={t("chat.model.select", { defaultValue: "Выбрать модель" })}
      >
        <span className="w-2 h-2 rounded-full bg-accent shrink-0" />
        <span className="max-w-[10rem] truncate">{label}</span>
        {current && isImageGen(current) && (
          <FiImage
            className="text-emerald-400 text-[13px] shrink-0"
            title={t("chat.model.cap_image", { defaultValue: "Генерирует изображения" })}
          />
        )}
        {current && isVideoGen(current) && (
          <FiVideo
            className="text-rose-400 text-[13px] shrink-0"
            title={t("chat.model.cap_video", { defaultValue: "Генерирует видео" })}
          />
        )}
        <FiChevronDown />
      </button>

      {open && typeof document !== "undefined" && createPortal(
        <div className="fixed inset-0 z-[1000] flex items-start sm:items-center justify-center p-3 sm:p-4">
          <div
            className="absolute inset-0"
            style={{ background: "var(--overlay, rgba(0,0,0,.55))" }}
            onClick={() => setOpen(false)}
          />
          <div className="relative w-full max-w-lg mt-[8vh] sm:mt-0 rounded-2xl border border-border bg-surface shadow-2xl overflow-hidden flex flex-col max-h-[80vh]">
            {/* Search header */}
            <div className="flex items-center gap-2 px-3.5 h-12 border-b border-border shrink-0">
              <FiSearch className="text-muted shrink-0" />
              <input
                ref={searchRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t("chat.model.search", { defaultValue: "Поиск моделей..." })}
                className="flex-1 bg-transparent outline-none text-sm text-foreground placeholder:text-muted-2"
                autoComplete="off"
                spellCheck={false}
              />
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="p-1.5 rounded-lg text-muted hover:text-foreground hover:bg-surface-2 cursor-pointer shrink-0"
                title={t("common.close", { defaultValue: "Закрыть" })}
              >
                <FiX />
              </button>
            </div>

            {/* List */}
            <div ref={listRef} className="overflow-y-auto p-1.5">
              {groups.length === 0 ? (
                <div className="px-3 py-8 text-center text-sm text-muted-2">
                  {t("chat.model.nothing", { defaultValue: "Ничего не найдено" })}
                  {caps.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setCaps([])}
                      className="mt-2 block mx-auto text-xs text-accent hover:text-accent-strong underline underline-offset-2 cursor-pointer"
                    >
                      {t("chat.model.reset_filters", { defaultValue: "Сбросить фильтры" })}
                    </button>
                  )}
                </div>
              ) : (
                groups.map((g) => (
                  <div key={g.key} className="mb-1">
                    {/* Заголовок группы — ЖЁЛТЫЙ (акцент): просьба клиента, серым было не видно */}
                    <div className="px-2.5 pt-2 pb-1 text-[11px] uppercase tracking-wide text-accent font-semibold inline-flex items-center gap-1.5">
                      <span className="text-[13px] leading-none">{g.icon}</span>
                      {g.label}
                    </div>
                    {g.items.map((m) => {
                      const active = modelKey(m) === value;
                      const locked = !!m.locked;
                      const showHint = lockedHint === modelKey(m);
                      return (
                        <div key={modelKey(m)}>
                          <button
                            type="button"
                            onClick={() => select(m)}
                            aria-disabled={locked}
                            className={`w-full text-left rounded-lg px-2.5 py-2 flex items-center gap-2.5 transition-colors cursor-pointer ${
                              active ? "bg-accent-soft" : "hover:bg-surface-2"
                            } ${locked ? "opacity-70" : ""}`}
                          >
                            <span
                              className="w-2 h-2 rounded-full shrink-0"
                              style={{ background: providerColor(m) }}
                            />
                            <span className="min-w-0 flex-1 flex flex-col">
                              <span className="truncate text-sm font-medium text-foreground">{m.name}</span>
                              {/* «Качество» video-модели под названием — приглушённый
                                  голубой (#4DA3FF @ ~82% насыщенности = #5DA3F0):
                                  читается на тёмном, не спорит с жёлтыми заголовками
                                  разделов и не перебивает название модели (просьба клиента). */}
                              {isVideoGen(m) && (m.description || "").trim() && (
                                <span
                                  className="inline-flex items-center gap-1 text-[11px] font-medium truncate"
                                  style={{ color: "#5DA3F0" }}
                                >
                                  {VIDEO_QUALITY_ICONS[(m.description || "").trim()] || null}
                                  <span className="truncate">
                                    {(() => {
                                      const d = (m.description || "").trim();
                                      const vq = VIDEO_QUALITY_I18N[d];
                                      return vq ? t(vq.key, { defaultValue: vq.def }) : d;
                                    })()}
                                  </span>
                                </span>
                              )}
                            </span>

                            {/* Capability badges */}
                            <span className="flex items-center gap-1.5 shrink-0">
                              {m.supports_vision && (
                                <Badge icon={<FiEye className="text-[13px]" />} title={t("chat.model.cap_vision", { defaultValue: "Понимает изображения" })} cls="text-blue-400" />
                              )}
                              {isImageGen(m) && (
                                <Badge icon={<FiImage className="text-[13px]" />} title={t("chat.model.cap_image", { defaultValue: "Генерирует изображения" })} cls="text-emerald-400" />
                              )}
                              {isVideoGen(m) && (
                                <Badge icon={<FiVideo className="text-[13px]" />} title={t("chat.model.cap_video", { defaultValue: "Генерирует видео" })} cls="text-rose-400" />
                              )}
                              {isReasoning(m) && (
                                <Badge icon={<FiCpu className="text-[13px]" />} title={t("chat.model.cap_reasoning", { defaultValue: "Рассуждающая модель" })} cls="text-purple-400" />
                              )}
                              {isWeb(m) && (
                                <Badge icon={<FiGlobe className="text-[13px]" />} title={t("chat.model.cap_web", { defaultValue: "Поиск в интернете" })} cls="text-amber-400" />
                              )}
                              {locked ? (
                                <span className="ml-0.5 text-[10px] uppercase tracking-wide text-accent border border-accent/40 rounded px-1 py-px">
                                  {t("chat.model.premium_badge", { defaultValue: "Премиум" })}
                                </span>
                              ) : active ? (
                                <FiCheck className="text-accent ml-0.5" />
                              ) : null}
                            </span>
                          </button>

                          {locked && showHint && (
                            <div className="mx-2 mb-1.5 mt-0.5 rounded-lg border border-accent/40 bg-accent-soft/40 p-3">
                              <p className="text-xs text-foreground leading-relaxed">
                                {t("chat.model.locked_hint", {
                                  defaultValue:
                                    "Доступно только для платных пакетов. Пополните баланс на 190 сомов, чтобы открыть все премиум-нейросети.",
                                })}
                              </p>
                              <button
                                type="button"
                                onClick={() => { setOpen(false); router.push("/pricing"); }}
                                className="mt-2 w-full inline-flex items-center justify-center rounded-lg bg-accent text-on-accent font-semibold text-xs py-2 hover:bg-accent-strong transition-colors cursor-pointer"
                              >
                                {t("balance.topup", { defaultValue: "Пополнить" })}
                              </button>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                ))
              )}
            </div>

            {/* Фильтры по возможностям. Были подсказкой-легендой, стали кнопками
                (просьба клиента): нажал «Видео» — остались только видео-модели,
                нажал ещё раз — фильтр снят. */}
            <div className="border-t border-border px-2.5 py-2 shrink-0">
              <div className="flex flex-wrap items-center gap-1.5">
                {CAP_FILTERS.map((f) => {
                  const on = caps.includes(f.key);
                  return (
                    <button
                      key={f.key}
                      type="button"
                      aria-pressed={on}
                      onClick={() => {
                        setCaps((prev) => (on ? prev.filter((k) => k !== f.key) : [...prev, f.key]));
                        // Выборка сменилась — показываем её с начала, иначе
                        // список остаётся прокрученным на старое место.
                        listRef.current?.scrollTo({ top: 0 });
                      }}
                      className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] transition-colors cursor-pointer ${
                        on
                          ? "border-accent bg-accent-soft text-foreground font-medium"
                          : "border-border text-muted-2 hover:text-foreground hover:border-accent/50"
                      }`}
                    >
                      <span className={`${f.cls} text-[13px] leading-none`}>{f.icon}</span>
                      {t(f.i18nKey, { defaultValue: f.label })}
                    </button>
                  );
                })}
                {caps.length > 0 && (
                  <button
                    type="button"
                    onClick={() => { setCaps([]); listRef.current?.scrollTo({ top: 0 }); }}
                    className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-[11px] text-muted-2 hover:text-foreground cursor-pointer"
                    title={t("chat.model.reset_filters", { defaultValue: "Сбросить фильтры" })}
                  >
                    <FiX className="text-[12px]" />
                    {t("chat.model.reset_filters", { defaultValue: "Сбросить фильтры" })}
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
}

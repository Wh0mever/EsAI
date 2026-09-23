"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { fetchData, BACKEND } from "@/tools/fetchData";

type VideoParams = {
  model: string;
  durations: number[];
  default_duration: number;
  resolutions: string[];
  default_resolution: string;
  aspect_ratios: string[];
  sizes: string[];
  frame_images: string[];
  generate_audio: boolean;
  credits_per_second: number;
  /** Точные цены с сервера: {разрешение: {секунды: кредиты}}. Зависят от
   *  разрешения (1080p у Seedance в 2,5 раза дороже 720p) — считать самим нельзя. */
  price_table?: Record<string, Record<string, number>>;
  /** Если цена зависит от пропорций (у Seedance 21:9 на треть больше пикселей). */
  price_table_by_aspect?: Record<string, Record<string, Record<string, number>>>;
};

export type VideoSettings = {
  duration: number | null;
  resolution: string | null;
  /** Пропорции кадра: 16:9, 9:16 и т.д. null — на усмотрение модели. */
  aspectRatio: string | null;
  firstFrame: string | null;
  lastFrame: string | null;
};

type Props = {
  model: string;
  value: VideoSettings;
  onChange: (patch: Partial<VideoSettings>) => void;
};

// Параметры и цены живут 10 минут: цены считаются по прайсу провайдера и могут
// поменяться, а вкладку с чатом держат открытой сутками.
const CACHE_TTL_MS = 10 * 60 * 1000;
const cache = new Map<string, { at: number; data: VideoParams }>();
const cached = (model: string): VideoParams | null => {
  const hit = cache.get(model);
  return hit && Date.now() - hit.at < CACHE_TTL_MS ? hit.data : null;
};

/* ---------- иконки: inline SVG, без лишних зависимостей ---------- */

function IconClock({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
      strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </svg>
  );
}

function IconFrame({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
      strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <circle cx="9" cy="9" r="1.6" />
      <path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21" />
    </svg>
  );
}

function IconRatio({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
      strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
      <rect x="2" y="6" width="20" height="12" rx="2" />
      <path d="M7 10v4M17 10v4" />
    </svg>
  );
}

/** Подписи к пропорциям — чтобы не гадать, где вертикаль, а где широкий кадр.
 *  Русский текст — defaultValue; перевод по ключу chat.aspect_<w>_<h>. */
export const ASPECT_HINT: Record<string, string> = {
  "16:9": "Горизонтальное — YouTube, презентации",
  "9:16": "Вертикальное — сторис, Reels, TikTok",
  "1:1": "Квадрат — лента, аватар",
  "4:3": "Классическое горизонтальное",
  "3:4": "Классическое вертикальное",
  "3:2": "Как фотография",
  "2:3": "Как фотография, вертикально",
  "4:5": "Вертикальное для ленты",
  "21:9": "Кинематографичное, очень широкое",
  "9:21": "Очень узкое вертикальное",
};

/** Переведённая подпись к пропорции (или сама пропорция, если подписи нет). */
export function aspectHint(t: TFunction, ratio: string): string {
  const ru = ASPECT_HINT[ratio];
  if (!ru) return ratio;
  return t(`chat.aspect_${ratio.replace(":", "_")}`, { defaultValue: ru });
}

export function IconAspect({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
      strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M8 5v14" />
    </svg>
  );
}

function IconSpark({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className} aria-hidden>
      <path d="M12 2.5 13.9 9l6.6 1.9-6.6 1.9L12 19.4l-1.9-6.6L3.5 10.9 10.1 9z" />
    </svg>
  );
}

function IconPlus({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
      strokeLinecap="round" className={className} aria-hidden>
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

function IconX({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3}
      strokeLinecap="round" className={className} aria-hidden>
      <path d="M6 6l12 12M18 6 6 18" />
    </svg>
  );
}

/* ---------- слот опорного кадра ---------- */

function FrameSlot({
  label,
  url,
  onPick,
  onClear,
}: {
  label: string;
  url: string | null;
  onPick: (file: File) => Promise<void>;
  onClear: () => void;
}) {
  const { t } = useTranslation("common");
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const abs = url ? (url.startsWith("/") ? BACKEND + url : url) : null;

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[11px] text-muted">{label}</span>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={async (e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          if (!f) return;
          setBusy(true);
          try {
            await onPick(f);
          } finally {
            setBusy(false);
          }
        }}
      />
      {abs ? (
        <div className="relative size-16">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={abs} alt={label} className="size-full object-cover rounded-xl border border-border" />
          {/* Маленький видимый ✕ в углу. Раньше кнопка-невидимка накрывала всю
              миниатюру: на телефоне (hover нет) любой тап по кадру молча его удалял. */}
          <button
            type="button"
            onClick={onClear}
            aria-label={t("chat.video_remove_frame", { defaultValue: "Убрать кадр" })}
            title={t("chat.video_remove_frame", { defaultValue: "Убрать кадр" })}
            className="absolute -top-2 -right-2 z-10 grid size-5 place-items-center rounded-full bg-rose-600 text-white shadow cursor-pointer"
          >
            <IconX className="size-3" />
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={busy}
          className="size-16 rounded-xl border border-dashed border-border/70 text-muted-2 grid place-items-center gap-0.5 transition-all duration-200 hover:border-accent/60 hover:text-accent-strong hover:scale-[1.03] active:scale-95 disabled:opacity-60 cursor-pointer"
        >
          {busy ? (
            <span className="size-4 rounded-full border-2 border-border border-t-accent animate-spin" />
          ) : (
            <>
              <IconPlus className="size-4" />
              <span className="text-[10px]">{t("chat.video_frame", { defaultValue: "Кадр" })}</span>
            </>
          )}
        </button>
      )}
    </div>
  );
}

/**
 * VideoParamsPanel — панель параметров генерации видео (по образцу
 * плейграунда OpenRouter, просьба клиента): длительность, качество,
 * первый и последний кадр и итоговая цена в кредитах.
 *
 * Допустимые значения НЕ выдумываются на фронте — приходят с бэкенда
 * (GET ai/video-params/), который читает каталог OpenRouter. Наборы у
 * моделей разные: Veo умеет 4/6/8 секунд, Seedance 2.5 — 4…30; последний
 * кадр поддерживают не все, поэтому слот показывается по факту поддержки.
 */
export default function VideoParamsPanel({ model, value, onChange }: Props) {
  const { t } = useTranslation("common");
  const [params, setParams] = useState<VideoParams | null>(cached(model));
  const [open, setOpen] = useState(true);

  useEffect(() => {
    if (!model) return;
    const c = cached(model);
    if (c) {
      setParams(c);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await fetchData<VideoParams>(
          "ai/video-params/?model=" + encodeURIComponent(model),
          "GET",
          null,
          false
        );
        if (cancelled || !res?.ok || !res.data) return;
        cache.set(model, { at: Date.now(), data: res.data });
        setParams(res.data);
      } catch {
        /* без параметров панель просто не показывается */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [model]);

  useEffect(() => {
    if (!params) return;
    if (value.duration == null) onChange({ duration: params.default_duration });
    if (value.resolution == null && params.default_resolution) {
      onChange({ resolution: params.default_resolution });
    }
  }, [params, value.duration, value.resolution, onChange]);

  const uploadFrame = useCallback(
    async (file: File, which: "firstFrame" | "lastFrame") => {
      const fd = new FormData();
      fd.append("files", file);
      const res = await fetchData<any>("ai/attachments/upload/", "POST", fd, true);
      const list = res?.data?.attachments || res?.data || [];
      const first = Array.isArray(list) ? list[0] : null;
      const url = first?.url || first?.preview;
      if (url) onChange({ [which]: url } as Partial<VideoSettings>);
    },
    [onChange]
  );

  const durations = useMemo(() => {
    if (!params) return [];
    const all = params.durations;
    if (all.length <= 8) return all;
    // 27 значений подряд — слишком длинный ряд; показываем разумную сетку,
    // всегда включая минимум, максимум и текущий выбор.
    const preferred = [4, 5, 6, 8, 10, 15, 20, 25, 30];
    const set = new Set<number>([
      all[0],
      all[all.length - 1],
      ...all.filter((d) => preferred.includes(d)),
    ]);
    if (value.duration != null && all.includes(value.duration)) set.add(value.duration);
    return Array.from(set).sort((a, b) => a - b);
  }, [params, value.duration]);

  if (!params) return null;

  const perSec = Number(params.credits_per_second) || 0;
  const dur = value.duration ?? params.default_duration;
  const res = value.resolution ?? params.default_resolution;
  // Цена — из таблицы сервера (то же, что спишется); умножение — только запасной путь.
  const tableFor = (r: string) =>
    (value.aspectRatio && params.price_table_by_aspect?.[value.aspectRatio]?.[r]) || params.price_table?.[r];
  const priceOf = (seconds: number, r: string = res) =>
    Number(tableFor(r)?.[String(seconds)]) || Math.max(1, Math.ceil(seconds * perSec));
  const cost = priceOf(dur);
  const supportsLast = (params.frame_images || []).includes("last_frame");

  const chip = (active: boolean) =>
    "rounded-lg px-2.5 py-1 text-xs font-semibold border transition-all duration-200 cursor-pointer active:scale-95 " +
    (active
      ? "bg-accent text-on-accent border-accent shadow-sm"
      : "bg-surface-2 text-muted border-border hover:text-foreground hover:border-accent/50");

  return (
    <div className="rounded-2xl border border-border bg-surface-2/60 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left cursor-pointer transition-colors hover:bg-surface-2"
      >
        <IconFrame className="size-4 shrink-0 text-accent-strong" />
        <span className="text-xs font-semibold text-foreground">
          {t("chat.video.panel_title", { defaultValue: "Параметры видео" })}
        </span>
        <span className="ml-auto inline-flex items-center gap-1 text-xs font-semibold text-accent-strong">
          <IconSpark className="size-3" />
          {cost}
        </span>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
          strokeLinecap="round" strokeLinejoin="round"
          className={"size-4 shrink-0 text-muted transition-transform duration-300 " + (open ? "rotate-180" : "")}
          aria-hidden>
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>

      {/* Раскрытие через grid-rows: плавно и без фиксированной высоты. */}
      <div
        className={
          "grid transition-all duration-300 ease-out " +
          (open ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0")
        }
      >
        <div className="min-h-0 overflow-hidden">
          <div className="flex flex-col gap-3 px-3 pb-3">
            <div className="flex flex-col gap-1.5">
              <span className="inline-flex items-center gap-1.5 text-[11px] text-muted">
                <IconClock className="size-3.5" />
                {t("chat.video.duration", { defaultValue: "Длительность" })}
              </span>
              <div className="flex flex-wrap gap-1.5">
                {durations.map((d) => (
                  <button
                    key={d}
                    type="button"
                    onClick={() => onChange({ duration: d })}
                    className={chip(dur === d)}
                    title={t("chat.video.duration_cost", {
                      seconds: d,
                      credits: priceOf(d),
                      defaultValue: "{{seconds}} сек — {{credits}} кредитов",
                    })}
                  >
                    {d}
                    {t("chat.video.sec_short", { defaultValue: "с" })}
                  </button>
                ))}
              </div>
            </div>

            {params.resolutions.length > 1 && (
              <div className="flex flex-col gap-1.5">
                <span className="inline-flex items-center gap-1.5 text-[11px] text-muted">
                  <IconRatio className="size-3.5" />
                  {t("chat.video.resolution", { defaultValue: "Качество" })}
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {params.resolutions.map((r) => (
                    <button
                      key={r}
                      type="button"
                      onClick={() => onChange({ resolution: r })}
                      className={chip((value.resolution ?? params.default_resolution) === r)}
                    >
                      {r}
                      {/* Цена прямо на кнопке: качество выше — ролик заметно дороже,
                          и человек должен видеть это до съёмки, а не после. */}
                      {tableFor(r)?.[String(dur)] != null && (
                        <span className="ml-1 font-normal opacity-70">· {priceOf(dur, r)}</span>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {params.aspect_ratios.length > 1 && (
              <div className="flex flex-col gap-1.5">
                <span className="inline-flex items-center gap-1.5 text-[11px] text-muted">
                  <IconAspect className="size-3.5" />
                  {t("chat.video.aspect", { defaultValue: "Соотношение сторон" })}
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {params.aspect_ratios.map((r) => (
                    <button
                      key={r}
                      type="button"
                      onClick={() => onChange({ aspectRatio: value.aspectRatio === r ? null : r })}
                      className={chip(value.aspectRatio === r)}
                      title={aspectHint(t, r)}
                    >
                      {r}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="flex items-start gap-3">
              <FrameSlot
                label={t("chat.video.first_frame", { defaultValue: "Первый кадр" })}
                url={value.firstFrame}
                onPick={(f) => uploadFrame(f, "firstFrame")}
                onClear={() => onChange({ firstFrame: null })}
              />
              {supportsLast && (
                <FrameSlot
                  label={t("chat.video.last_frame", { defaultValue: "Последний кадр" })}
                  url={value.lastFrame}
                  onPick={(f) => uploadFrame(f, "lastFrame")}
                  onClear={() => onChange({ lastFrame: null })}
                />
              )}
            </div>

            <p className="text-[11px] text-muted-2 leading-snug">
              {t("chat.video.cost_hint", {
                seconds: dur,
                credits: cost,
                defaultValue: "Ролик {{seconds}} сек — спишется {{credits}} кредитов",
              })}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

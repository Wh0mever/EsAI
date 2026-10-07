"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { FiAlertCircle, FiCheckCircle, FiFilm, FiImage, FiPlay, FiX } from "react-icons/fi";
import type { ShowcaseMedia } from "./showcaseAdmin";

/* ------------------------------------------------------------------ */
/* Классы                                                              */
/* ------------------------------------------------------------------ */

const INPUT_FRAME =
  "rounded-lg border border-border bg-surface-2 px-3 text-sm text-foreground outline-none focus:border-accent disabled:opacity-60";
/** Поле в строке списка и фильтров — той же высоты, что чипы. */
export const INPUT = `${INPUT_FRAME} py-1.5`;
export const INPUT_LG = `${INPUT_FRAME} py-2`;

const CHIP = "cursor-pointer rounded-lg border px-3 py-1.5 text-xs transition-colors";
export const chip = (on: boolean): string =>
  `${CHIP} ${on ? "border-accent bg-accent/10 text-accent" : "border-border text-muted hover:text-foreground"}`;

// Размер и цвет кнопки собираются из частей: два класса на одно свойство
// (px-3 и px-4) Tailwind разрешает по порядку в CSS, а не в className.
const BTN_FRAME =
  "inline-flex cursor-pointer items-center justify-center gap-1.5 rounded-lg disabled:cursor-not-allowed disabled:opacity-50";
const BTN_SIZE = { sm: "px-3 py-1.5 text-xs", lg: "px-4 py-2 text-sm" } as const;
const BTN_TONE = {
  plain: "border border-border text-muted transition-colors enabled:hover:text-foreground",
  danger:
    "border border-border text-muted transition-colors enabled:hover:border-status-fail/50 enabled:hover:text-status-fail",
  primary: "bg-accent font-semibold text-on-accent transition-opacity enabled:hover:opacity-90",
} as const;

export const btn = (tone: keyof typeof BTN_TONE = "plain", size: keyof typeof BTN_SIZE = "sm"): string =>
  `${BTN_FRAME} ${BTN_SIZE[size]} ${BTN_TONE[tone]}`;

export const CARD = "rounded-2xl border border-border bg-surface";

/* ------------------------------------------------------------------ */
/* Формат                                                              */
/* ------------------------------------------------------------------ */

export const fmtDate = (iso: string): string => {
  const d = new Date(iso);
  if (!iso || isNaN(d.getTime())) return iso;
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
};

/** «Видео · 16:9 · 5 с · 720p» — что за дубль, одной строкой. */
export function mediaFacts(media: ShowcaseMedia): string {
  const parts = [media.kind === "image" ? "Картинка" : "Видео"];
  if (media.aspect) parts.push(media.aspect);
  if (media.duration !== null) parts.push(`${Math.round(media.duration)} с`);
  if (media.resolution) parts.push(media.resolution);
  return parts.join(" · ");
}

/* ------------------------------------------------------------------ */
/* Мелкие блоки                                                        */
/* ------------------------------------------------------------------ */

export type Tone = "accent" | "wait" | "fail" | "muted";

const TONE: Record<Tone, string> = {
  accent: "border-accent/40 bg-accent/10 text-accent",
  wait: "border-status-wait/30 bg-status-wait/10 text-status-wait",
  fail: "border-status-fail/30 bg-status-fail/10 text-status-fail",
  muted: "border-border bg-surface-2 text-muted",
};

export function Badge({ tone = "muted", title, children }: { tone?: Tone; title?: string; children: ReactNode }) {
  return (
    <span
      title={title}
      className={`inline-flex items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium ${TONE[tone]}`}
    >
      {children}
    </span>
  );
}

export function Switch({
  on,
  label,
  title,
  disabled = false,
  onChange,
}: {
  on: boolean;
  label: string;
  title?: string;
  disabled?: boolean;
  onChange: (on: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      title={title}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className="inline-flex min-h-9 cursor-pointer items-center gap-2 text-xs disabled:cursor-not-allowed disabled:opacity-50"
    >
      <span
        className={`relative h-5 w-9 shrink-0 rounded-full border transition-colors ${
          on ? "border-accent bg-accent" : "border-border bg-surface-2"
        }`}
      >
        <span
          className={`absolute left-0.5 top-0.5 h-3.5 w-3.5 rounded-full transition-transform motion-reduce:transition-none ${
            on ? "translate-x-3.5 bg-on-accent" : "bg-muted"
          }`}
        />
      </span>
      <span className={on ? "text-foreground" : "text-muted"}>{label}</span>
    </button>
  );
}

/**
 * Превью дубля. Ролик не грузится, пока его не попросили: в списке десятки
 * карточек, а оригиналы тяжёлые. До клика — только обложка.
 */
export function Preview({ media, className = "" }: { media: ShowcaseMedia; className?: string }) {
  const [playing, setPlaying] = useState(false);
  const frame = `relative aspect-video w-full overflow-hidden bg-black ${className}`;
  const still = media.poster ?? media.image;

  if (media.kind === "video" && media.video && playing) {
    return (
      <div className={frame}>
        <video
          src={media.video}
          poster={media.poster ?? undefined}
          controls
          autoPlay
          playsInline
          className="h-full w-full object-contain"
        />
      </div>
    );
  }

  const Placeholder = media.kind === "image" ? FiImage : FiFilm;
  return (
    <div className={frame}>
      {still ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={still} alt="" loading="lazy" decoding="async" className="h-full w-full object-contain" />
      ) : (
        <div className="flex h-full w-full flex-col items-center justify-center gap-1 text-white/40">
          <Placeholder className="h-6 w-6" aria-hidden />
          {!media.video && <span className="text-[11px]">Файл недоступен</span>}
        </div>
      )}
      {media.kind === "video" && media.video && (
        <button
          type="button"
          onClick={() => setPlaying(true)}
          aria-label="Смотреть ролик"
          className="group absolute inset-0 flex cursor-pointer items-center justify-center"
        >
          <span className="flex h-11 w-11 items-center justify-center rounded-full bg-black/60 text-white transition-colors group-hover:bg-black/80">
            <FiPlay className="ml-0.5 h-5 w-5" aria-hidden />
          </span>
        </button>
      )}
    </div>
  );
}

export function Skeleton({ className }: { className: string }) {
  return <div className={`rounded-2xl bg-surface-2 motion-safe:animate-pulse ${className}`} />;
}

/* ------------------------------------------------------------------ */
/* Сообщения о действиях                                               */
/* ------------------------------------------------------------------ */

export type Notice = { id: number; tone: "ok" | "fail"; text: string };

/**
 * Всплывающие сообщения: список длинный, и строка «сохранено / не получилось»
 * вверху страницы осталась бы за экраном. Удача гаснет сама, отказ держится
 * дольше — его надо успеть прочитать.
 */
export function useNotices() {
  const [list, setList] = useState<Notice[]>([]);
  const seq = useRef(0);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const close = useCallback((id: number) => {
    const timer = timers.current.get(id);
    if (timer) clearTimeout(timer);
    timers.current.delete(id);
    setList((prev) => prev.filter((notice) => notice.id !== id));
  }, []);

  const notify = useCallback(
    (tone: Notice["tone"], text: string) => {
      const id = ++seq.current;
      setList((prev) => [...prev.slice(-2), { id, tone, text }]);
      timers.current.set(
        id,
        setTimeout(() => close(id), tone === "ok" ? 4000 : 9000),
      );
    },
    [close],
  );

  useEffect(() => {
    const pending = timers.current;
    return () => {
      for (const timer of pending.values()) clearTimeout(timer);
      pending.clear();
    };
  }, []);

  return { list, notify, close };
}

export function Notices({ list, onClose }: { list: Notice[]; onClose: (id: number) => void }) {
  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed inset-x-4 bottom-[calc(1rem+env(safe-area-inset-bottom,0px))] z-[1200] flex flex-col items-end gap-2 sm:left-auto sm:w-96"
    >
      {list.map((notice) => {
        const fail = notice.tone === "fail";
        const Icon = fail ? FiAlertCircle : FiCheckCircle;
        return (
          <div
            key={notice.id}
            role={fail ? "alert" : "status"}
            className={`pointer-events-auto flex w-full items-start gap-2 rounded-xl border bg-surface px-3 py-2.5 text-sm shadow-lg ${
              fail ? "border-status-fail/50" : "border-status-ok/50"
            }`}
          >
            <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${fail ? "text-status-fail" : "text-status-ok"}`} aria-hidden />
            <span className="min-w-0 flex-1 break-words">{notice.text}</span>
            <button
              type="button"
              onClick={() => onClose(notice.id)}
              aria-label="Закрыть сообщение"
              className="-mr-1 cursor-pointer rounded-md p-1 text-muted hover:text-foreground"
            >
              <FiX className="h-4 w-4" aria-hidden />
            </button>
          </div>
        );
      })}
    </div>
  );
}

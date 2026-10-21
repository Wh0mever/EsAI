"use client";

import { useEffect, useRef, useState, type RefObject } from "react";
import { useTranslation } from "react-i18next";
import { FiFilm, FiPlay } from "react-icons/fi";
import { VS_FOCUS, vx } from "@/components/vstudio/ui/skin";

/**
 * Кадр фрагмента: постер, а у роликов без постера (видео из чата) — первый
 * кадр самого файла. Файл — целый ролик, не облегчённое превью, поэтому
 * <video preload="metadata"> появляется, только когда карточка подъехала к
 * экрану, и сам не играет. Нажали ▶ — ролик играет здесь же, с привычными
 * кнопками браузера; второй запущенный останавливает первый.
 *
 * Всё поверх кадра — чёрно-белое в любой теме: кадр тёмный всегда.
 */

/** Играет одно превью на странице. */
let playing: HTMLVideoElement | null = null;

function onPlay(el: HTMLVideoElement) {
  if (playing && playing !== el) playing.pause();
  playing = el;
}

/** Карточка у экрана (с запасом): один раз увидели — дальше держим. */
function useNear<T extends Element>(): [RefObject<T | null>, boolean] {
  const ref = useRef<T | null>(null);
  const [near, setNear] = useState(false);
  useEffect(() => {
    const node = ref.current;
    if (!node || near) return;
    if (typeof IntersectionObserver === "undefined") {
      // Без наблюдателя (старый браузер) — кадр сразу: иначе карточка навсегда пустая.
      const id = window.setTimeout(() => setNear(true), 0);
      return () => window.clearTimeout(id);
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) setNear(true);
      },
      { rootMargin: "200px 0px" },
    );
    io.observe(node);
    return () => io.disconnect();
  }, [near]);
  return [ref, near];
}

export type MediaThumbProps = {
  poster: string | null;
  /** Ролик; null — источник пропал, показываем только постер. */
  url: string | null;
  /** Подпись для кнопки ▶ («Посмотреть: …»). */
  title: string;
  /** Вертикальный или квадратный кадр вписываем целиком, горизонтальный — на всю рамку. */
  vertical?: boolean;
  /** Можно ли смотреть (у недоступного фрагмента — нет). */
  playable?: boolean;
  /** Маленькая кнопка ▶ (миниатюра в строке ленты). */
  compact?: boolean;
  /** Ролик на карточке заиграл или встал (пауза, конец): соседние кнопки уступают место плееру. */
  onPlayingChange?: (playing: boolean) => void;
  className?: string;
};

export default function MediaThumb({
  poster,
  url,
  title,
  vertical = false,
  playable = true,
  compact = false,
  onPlayingChange,
  className,
}: MediaThumbProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const [ref, near] = useNear<HTMLDivElement>();
  const [open, setOpen] = useState(false);
  const fit = vertical ? "object-contain" : "object-cover";
  const label = t("merge.preview", { defaultValue: "Посмотреть: {{title}}", title });

  return (
    <div ref={ref} className={vx("relative h-full w-full overflow-hidden bg-black", className)}>
      {open && url ? (
        <video
          src={url}
          poster={poster ?? undefined}
          controls
          autoPlay
          playsInline
          preload="metadata"
          onPlay={(e) => {
            onPlay(e.currentTarget);
            onPlayingChange?.(true);
          }}
          onPause={() => onPlayingChange?.(false)}
          onEnded={() => onPlayingChange?.(false)}
          className="h-full w-full bg-black object-contain"
        />
      ) : (
        <>
          {poster ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={poster} alt="" loading="lazy" decoding="async" className={vx("h-full w-full", fit)} />
          ) : url && near ? (
            // Первый кадр файла: #t — чтобы Safari показал кадр, а не чёрный прямоугольник.
            <video
              src={`${url}#t=0.1`}
              muted
              playsInline
              preload="metadata"
              tabIndex={-1}
              aria-hidden="true"
              className={vx("pointer-events-none h-full w-full", fit)}
            />
          ) : (
            <span className="grid h-full w-full place-items-center text-white/40" aria-hidden="true">
              <FiFilm className={compact ? "size-4" : "size-6"} />
            </span>
          )}
          {url && playable && (
            <button
              type="button"
              onClick={() => setOpen(true)}
              aria-label={label}
              title={label}
              className={vx(
                "absolute inset-0 m-auto grid cursor-pointer place-items-center rounded-full bg-black/55 text-white transition-[background-color,transform] hover:bg-black/75 active:scale-95 motion-reduce:transition-none",
                compact ? "size-9 before:absolute before:-inset-1" : "size-11",
                VS_FOCUS,
              )}
            >
              <FiPlay className={compact ? "ml-0.5 size-4" : "ml-0.5 size-5"} aria-hidden="true" />
            </button>
          )}
        </>
      )}
    </div>
  );
}

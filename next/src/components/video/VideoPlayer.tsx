"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * VideoPlayer — сгенерированный ролик с крупной кнопкой Play по центру.
 *
 * Зачем. Раньше стоял голый <video controls>: играть можно было только через
 * маленький треугольник в системной панели снизу, и клиент справедливо
 * спросил, почему нельзя ткнуть в середину ролика, как на YouTube.
 *
 * Форма кнопки — скруглённый прямоугольник с треугольником: узнаётся так же,
 * но геометрия наша, а цвет фирменный жёлтый (просьба клиента: «чтобы этим
 * отличаться»). Системные controls оставлены — перемотка, громкость и
 * полноэкранный режим достаются бесплатно и ведут себя привычно на каждой
 * платформе; оверлей их не перекрывает (pointer-events-none + auto на самой
 * кнопке), поэтому нижняя панель остаётся кликабельной.
 */
export default function VideoPlayer({
  src,
  poster,
  className,
  autoPlay,
  playLabel = "Смотреть",
}: {
  src: string;
  poster?: string;
  className?: string;
  autoPlay?: boolean;
  /** Подпись кнопки (в чате приходит переведённая, здесь — разумный запас). */
  playLabel?: string;
}) {
  const ref = useRef<HTMLVideoElement | null>(null);
  const [playing, setPlaying] = useState(false);
  // Пока ролик не начинали смотреть, кнопка крупнее: это главное действие на
  // карточке. После первой паузы она уменьшается, чтобы не закрывать кадр.
  const [touched, setTouched] = useState(false);

  const toggle = useCallback(() => {
    const v = ref.current;
    if (!v) return;
    setTouched(true);
    if (v.paused) void v.play().catch(() => {});
    else v.pause();
  }, []);

  useEffect(() => {
    const v = ref.current;
    if (!v) return;
    const onPlay = () => { setPlaying(true); setTouched(true); };
    const onPause = () => setPlaying(false);
    v.addEventListener("play", onPlay);
    v.addEventListener("pause", onPause);
    v.addEventListener("ended", onPause);
    return () => {
      v.removeEventListener("play", onPlay);
      v.removeEventListener("pause", onPause);
      v.removeEventListener("ended", onPause);
    };
  }, []);

  return (
    <div className={`relative overflow-hidden rounded-xl border border-border bg-black ${className || ""}`}>
      <video
        ref={ref}
        controls
        playsInline
        autoPlay={autoPlay}
        preload="metadata"
        poster={poster || undefined}
        src={src}
        className="block w-full h-full"
      />

      {/* Оверлей поверх кадра. Сам по себе прозрачен для мыши — иначе он
          перехватывал бы клики по системной панели управления снизу. */}
      <div
        className={`pointer-events-none absolute inset-0 grid place-items-center transition-opacity duration-200 ${
          playing ? "opacity-0" : "opacity-100"
        }`}
      >
        <button
          type="button"
          onClick={toggle}
          tabIndex={playing ? -1 : 0}
          aria-label={playLabel}
          title={playLabel}
          className="pointer-events-auto cursor-pointer transition-transform duration-200 hover:scale-110 active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded-[18%]"
          style={{ filter: "drop-shadow(0 4px 14px rgba(0,0,0,.45))" }}
        >
          <svg
            viewBox="0 0 72 50"
            className={`${touched ? "w-14" : "w-[68px]"} h-auto transition-[width] duration-200`}
            aria-hidden="true"
          >
            {/* Скруглённая «плашка» фирменного жёлтого */}
            <rect x="0" y="0" width="72" height="50" rx="13" fill="var(--accent, #f5c518)" />
            {/* Треугольник цветом текста на акценте — тот же контраст, что у
                жёлтых кнопок сайта, поэтому в светлой теме тоже читается. */}
            <path d="M29 15.5 L47 25 L29 34.5 Z" fill="var(--on-accent, #1a1a1a)" />
          </svg>
        </button>
      </div>
    </div>
  );
}

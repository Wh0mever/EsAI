"use client";

import { useState, type ReactNode } from "react";
import { FiFilm, FiPlay } from "react-icons/fi";
import { chip } from "../vstudio-showcase/parts";
import type { ScenePreview as Preview } from "./scenesAdmin";

/**
 * Превью сцены. Ролик не грузится, пока его не попросили: сцен в библиотеке
 * больше сотни, а оригиналы тяжёлые. До клика — лёгкая обложка, как в сетке
 * библиотеки; по клику — сам ролик со звуком и управлением.
 */
export function ScenePreview({ preview, className = "" }: { preview: Preview; className?: string }) {
  const [playing, setPlaying] = useState(false);
  const frame = `relative aspect-video w-full overflow-hidden bg-black ${className}`;
  const still = preview.thumb ?? preview.poster;
  const video = preview.video ?? preview.clip;

  if (video && playing) {
    return (
      <div className={frame}>
        <video
          src={video}
          poster={preview.poster ?? undefined}
          controls
          autoPlay
          playsInline
          className="h-full w-full object-contain"
        />
      </div>
    );
  }

  return (
    <div className={frame}>
      {still ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={still} alt="" loading="lazy" decoding="async" className="h-full w-full object-contain" />
      ) : (
        <div className="flex h-full w-full flex-col items-center justify-center gap-1 text-white/40">
          <FiFilm className="h-6 w-6" aria-hidden />
          <span className="text-[11px]">{video ? "Обложки пока нет" : "Ролика пока нет"}</span>
        </div>
      )}
      {video && (
        <button
          type="button"
          onClick={() => setPlaying(true)}
          aria-label="Смотреть ролик превью"
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

/** Поле формы с подписью и подсказкой: подпись — label, клик по ней ставит фокус в поле. */
export function Field({
  label,
  hint,
  className = "",
  children,
}: {
  label: ReactNode;
  hint?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <label className={`block min-w-0 text-sm ${className}`}>
      <span className="text-muted">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted-2">{hint}</span>}
    </label>
  );
}

/** Выбор одного из вариантов чипами — для коротких списков (аудитория, пропорции). */
export function Choice<K extends string>({
  label,
  options,
  value,
  disabled = false,
  onChange,
}: {
  label: string;
  options: readonly { key: K; label: string }[];
  value: K;
  disabled?: boolean;
  onChange: (key: K) => void;
}) {
  return (
    <div className="min-w-0 text-sm">
      <span className="text-muted">{label}</span>
      <div role="group" aria-label={label} className="mt-1.5 flex flex-wrap gap-2">
        {options.map((option) => (
          <button
            key={option.key}
            type="button"
            aria-pressed={value === option.key}
            disabled={disabled}
            onClick={() => onChange(option.key)}
            className={`${chip(value === option.key)} min-h-9 disabled:cursor-not-allowed disabled:opacity-50`}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

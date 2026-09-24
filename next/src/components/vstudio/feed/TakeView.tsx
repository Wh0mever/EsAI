"use client";

import { memo, useRef, useState, type CSSProperties } from "react";
import { flushSync } from "react-dom";
import { useTranslation } from "react-i18next";
import { FiAlertTriangle, FiCheckCircle, FiImage, FiSlash } from "react-icons/fi";
import VideoPlayer from "@/components/video/VideoPlayer";
import { errorText } from "@/lib/vstudio/errors";
import type { AssetJSON, ShotInputJSON, TakeLite } from "@/lib/vstudio/types";
import { formatClock, isOpenStatus, labelNumber, mediaRatio, statusPhrase } from "./feedLogic";
import TakeStatus from "./TakeStatus";

/**
 * Рамка кадра: ширина по колонке, но высота не больше 70vh — вертикальное
 * 9:16 на компьютере не растягивается на три экрана.
 */
function frameStyle(ratio: number): CSSProperties {
  const r = Number.isFinite(ratio) && ratio > 0 ? ratio : 16 / 9;
  return {
    aspectRatio: `${r}`,
    width: "100%",
    maxWidth: `min(100%, calc(70vh * ${r.toFixed(4)}))`,
  };
}

/**
 * Ролик в ленте — это preload="none" (§9.6): до нажатия стоит только постер
 * (картинка с loading="lazy"), и лента из 20 роликов не качает ни байта
 * видео. VideoPlayer (у него зашит preload="metadata") монтируется по
 * нажатию — сразу в том же обработчике (flushSync), и play() зовётся внутри
 * жеста: иначе iOS Safari не запустит ролик со звуком и попросит второй тап.
 * Кнопка — та же жёлтая «плашка», что у самого плеера: подмена незаметна.
 */
function ResultVideo({
  asset,
  ratio,
  playLabel,
  durationText,
}: {
  asset: AssetJSON;
  ratio: number;
  playLabel: string;
  durationText: string;
}) {
  const boxRef = useRef<HTMLDivElement | null>(null);
  const [active, setActive] = useState(false);

  const start = () => {
    flushSync(() => setActive(true));
    const video = boxRef.current?.querySelector("video");
    if (video) void video.play().catch(() => {});
  };

  return (
    <div ref={boxRef} style={frameStyle(ratio)} className="relative mx-auto">
      {active && asset.url ? (
        <VideoPlayer
          src={asset.url}
          poster={asset.thumb_url || undefined}
          className="h-full w-full"
          playLabel={playLabel}
        />
      ) : (
        <button
          type="button"
          onClick={start}
          disabled={!asset.url}
          aria-label={playLabel}
          title={playLabel}
          className="group relative block h-full w-full cursor-pointer overflow-hidden rounded-xl border border-border bg-black focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-default"
        >
          {asset.thumb_url && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={asset.thumb_url} alt="" loading="lazy" decoding="async" className="h-full w-full object-contain" />
          )}
          <span className="absolute inset-0 grid place-items-center" aria-hidden>
            <svg
              viewBox="0 0 72 50"
              className="h-auto w-[68px] transition-transform duration-200 group-hover:scale-110 group-active:scale-95"
              style={{ filter: "drop-shadow(0 4px 14px rgba(0,0,0,.45))" }}
            >
              <rect x="0" y="0" width="72" height="50" rx="13" fill="var(--accent, #f5c518)" />
              <path d="M29 15.5 L47 25 L29 34.5 Z" fill="var(--on-accent, #1a1a1a)" />
            </svg>
          </span>
          {durationText && (
            <span className="absolute bottom-2 right-2 rounded-md bg-black/65 px-1.5 py-0.5 text-[11px] font-medium tabular-nums text-white">
              {durationText}
            </span>
          )}
        </button>
      )}
    </div>
  );
}

function ResultImage({ asset, ratio, alt }: { asset: AssetJSON; ratio: number; alt: string }) {
  const src = asset.url || asset.thumb_url;
  if (!src) return null;
  return (
    <a
      href={asset.url || src}
      target="_blank"
      rel="noopener noreferrer"
      style={frameStyle(ratio)}
      className="relative mx-auto block cursor-zoom-in overflow-hidden rounded-xl border border-border bg-surface-2"
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt={alt} loading="lazy" decoding="async" className="h-full w-full object-contain" />
    </a>
  );
}

type Tr = (key: string, options?: Record<string, unknown>) => string;

/** «0:10» на постере: длина файла, иначе заказанная длительность; пусто — не знаем. */
function durationOf(take: TakeLite): string {
  const s = take.result?.duration_s ?? take.effective?.duration ?? null;
  return typeof s === "number" && Number.isFinite(s) && s > 0 ? formatClock(Math.round(s)) : "";
}

/** Подпись входа для «Модели не подошло: @Image 2»: кадры переводятся, @Image N — нет. */
function inputLabel(t: Tr, input: ShotInputJSON | undefined): string {
  if (!input) return "";
  if (input.slot === "first_frame") return t("subject.first_frame", { defaultValue: "@Первый кадр" });
  if (input.slot === "last_frame") return t("subject.last_frame", { defaultValue: "@Последний кадр" });
  const n = labelNumber(input.label);
  return n ? `@Image ${n}` : t("subject.excluded", { defaultValue: "Выключенное фото" });
}

export type TakeViewProps = {
  take: TakeLite;
  /** Входы кадра: виноватый вход (error.input) называем по его метке. */
  inputs: ShotInputJSON[];
  onCancel?: () => void;
  canceling?: boolean;
};

/**
 * Один дубль (§9.6): идущий — статус с секундомером и полосой по ETA;
 * готовый — плеер или картинка; неудачный — причина по error_code, виноватый
 * вход и «Кредиты не списаны»; отменённый и потерянный — своя строка.
 */
function TakeView({ take, inputs, onCancel, canceling }: TakeViewProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const open = isOpenStatus(take.status);
  const phrase = statusPhrase(take);
  const statusText = t(phrase.key, { defaultValue: phrase.ru, ...(phrase.params || {}) });
  const ratio = mediaRatio(take.result, take.effective?.aspect_ratio, take.kind);
  const noCharge = take.charge_state === "released" || (!open && take.status !== "done" && !take.credits?.charged);

  const failure =
    take.status === "failed"
      ? errorText(t, {
          code: take.error?.code || "provider_error",
          message: take.error?.message || "",
          // У картинки свои тексты (errors.<code>_image): «…изображение», а не «…видео».
          context: take.kind === "image" ? "image" : undefined,
        })
      : "";
  const culprit = take.error?.input ? inputs.find((i) => i.asset.uid === take.error?.input) : undefined;
  const culpritText = culprit
    ? t("run.culprit", { defaultValue: "Модели не подошло: {{label}}", label: inputLabel(t as Tr, culprit) })
    : "";

  // Живой регион переживает смену статуса — поэтому диктор скажет «Видео готово».
  const announce = take.status === "failed" ? `${statusText}. ${failure}` : statusText;

  return (
    <div className="flex w-full flex-col gap-2" data-take={take.uid}>
      <span className="sr-only" role="status" aria-live="polite">
        {announce}
      </span>

      {/* Идущий дубль — компактная плашка во всю ширину карточки: в узкой
          рамке 9:16 статус и кнопки переносились бы по словам, а два видео
          и четыре картинки в работе растянули бы ленту на несколько экранов. */}
      {open && (
        <div className="relative overflow-hidden rounded-xl border border-border bg-surface-2">
          <div className="pointer-events-none absolute inset-0 animate-pulse bg-gradient-to-br from-accent/10 via-transparent to-status-progress/10" />
          <div className="relative flex min-h-28 items-end p-3 sm:min-h-32 sm:p-4">
            <TakeStatus take={take} onCancel={onCancel} canceling={canceling} />
          </div>
        </div>
      )}

      {take.status === "done" &&
        (take.result && (take.result.url || take.result.thumb_url) ? (
          take.kind === "video" || take.result.kind === "video" ? (
            <ResultVideo
              asset={take.result}
              ratio={ratio}
              playLabel={t("run.actions.play", { defaultValue: "Смотреть" })}
              durationText={durationOf(take)}
            />
          ) : (
            <ResultImage asset={take.result} ratio={ratio} alt={statusText} />
          )
        ) : (
          <div className="flex items-center gap-2 rounded-xl border border-border bg-surface-2 p-3 text-sm text-muted">
            <FiImage aria-hidden />
            {statusText}
          </div>
        ))}

      {take.status === "failed" && (
        <div className="flex flex-col gap-1.5 rounded-xl border border-status-fail/40 bg-status-fail/10 p-3">
          <p className="flex items-start gap-2 text-sm text-foreground">
            <FiAlertTriangle className="mt-0.5 shrink-0 text-status-fail" aria-hidden />
            <span>{failure}</span>
          </p>
          {culpritText && <p className="pl-6 text-xs font-medium text-status-fail">{culpritText}</p>}
        </div>
      )}

      {take.status === "lost" && (
        <div className="flex items-start gap-2 rounded-xl border border-status-wait/40 bg-status-wait/10 p-3 text-sm text-foreground">
          <FiAlertTriangle className="mt-0.5 shrink-0 text-status-wait" aria-hidden />
          <span>{statusText}</span>
        </div>
      )}

      {take.status === "canceled" && (
        <div className="flex items-center gap-2 rounded-xl border border-border bg-surface-2 p-3 text-sm text-muted">
          <FiSlash className="shrink-0" aria-hidden />
          <span>{statusText}</span>
        </div>
      )}

      {!open && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {take.status === "done" && take.credits?.charged > 0 && (
            <span className="inline-flex items-center gap-1 text-muted">
              <FiCheckCircle className="text-status-ok" aria-hidden />
              {t("run.charged", { defaultValue: "Списано {{n}} кр", n: take.credits.charged })}
            </span>
          )}
          {take.status === "done" && !take.credits?.charged && take.charge_state === "released" && (
            <span className="inline-flex items-center gap-1 text-muted">
              <FiCheckCircle className="text-status-ok" aria-hidden />
              {t("run.free", { defaultValue: "Бесплатно — за наш счёт" })}
            </span>
          )}
          {take.status !== "done" && take.status !== "lost" && noCharge && (
            <span className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-muted">
              <FiCheckCircle className="text-status-ok" aria-hidden />
              {t("run.noCharge", { defaultValue: "Кредиты не списаны" })}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

export default memo(TakeView);

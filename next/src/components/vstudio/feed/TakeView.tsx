"use client";

import { memo, useCallback, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { flushSync } from "react-dom";
import { useTranslation } from "react-i18next";
import { FiAlertTriangle, FiCheckCircle, FiImage, FiMaximize2, FiSlash } from "react-icons/fi";
import VideoPlayer from "@/components/video/VideoPlayer";
import { takeErrorText } from "@/lib/vstudio/errors";
import type { AssetJSON, ShotInputJSON, TakeLite } from "@/lib/vstudio/types";
import { VS_FOCUS, VS_ON_MEDIA, VS_SHEEN_ON_MEDIA, VS_TAG, vx } from "../ui/skin";
import { prefersReducedMotion } from "../ui/useAutoplayAllowed";
import { formatClock, isOpenStatus, labelNumber, mediaRatio, statusPhrase } from "./feedLogic";
import TakeStatus, { TakeProgress } from "./TakeStatus";
import { useInView } from "./useInView";

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

/** Кадр с пропорцией меньше этой не достаёт до краёв карточки: по бокам нужна подложка. */
const BACKDROP_BELOW_RATIO = 1.5;

/**
 * Рамка кадра в ленте: та же, что у плеера, чтобы подмена постера на плеер была незаметна.
 * Геометрия — как у VS_MEDIA (ui/skin.ts), а цвет подложки свой: чёрной она становится,
 * когда картинка её уже закрыла. Пока файл грузится (у картинки это полный размер),
 * в светлой теме на белой карточке стояла бы чёрная плита — там подложка в тон пустого
 * кадра, как у LazyClip. В тёмной теме она чёрная всегда.
 *
 * Кромка закрытого кадра лежит на его чёрной подложке, поэтому её подсветка при наведении
 * белая в обеих темах: чернила темы на чёрном не видны.
 */
const FRAME = "relative overflow-hidden rounded-xl border border-border";
const FRAME_ON = "bg-black hover:border-white/25";
const FRAME_BARE = "bg-surface-3 hover:border-border-strong dark:bg-black dark:hover:border-white/25";
/** Кольцо фокуса внутрь: сцена обрезает всё, что выходит за кадр. */
const FRAME_FOCUS = vx(VS_FOCUS, "focus-visible:ring-inset");

/**
 * Что стало с картинкой кадра по этому адресу: загрузилась или не открылась.
 * Картинка из кэша бывает готова раньше, чем React повесит onLoad, — её ловит ref.
 */
function useFrameImage(src: string | null) {
  const [seen, setSeen] = useState<{ src: string; ok: boolean } | null>(null);
  const mount = useCallback(
    (img: HTMLImageElement | null) => {
      if (src && img && img.complete && img.naturalWidth > 0) setSeen({ src, ok: true });
    },
    [src],
  );
  const onLoad = useCallback(() => {
    if (src) setSeen({ src, ok: true });
  }, [src]);
  const onError = useCallback(() => {
    if (src) setSeen({ src, ok: false });
  }, [src]);
  const now = seen && seen.src === src ? seen : null;
  return { loaded: now?.ok === true, failed: now?.ok === false, mount, onLoad, onError };
}

/**
 * Сцена под кадр: он стоит по центру, а по бокам — его же размытая копия.
 * Без неё вертикальный ролик в широкой карточке висит в пустоте. Копия — уже
 * загруженный постер (второго запроса нет). На телефоне кадр и так во всю
 * ширину, у широкого кадра боков почти нет — там её не рисуем.
 *
 * В тёмной теме копия приглушена (40 %) и тонет в карточке. На белой карточке
 * та же прозрачность разбавила бы её белым — тёмный ролик дал бы серую грязь, —
 * поэтому в светлой теме копия стоит в полную силу: бока продолжают кадр.
 */
function Stage({ backdrop, ratio, children }: { backdrop: string | null; ratio: number; children: ReactNode }) {
  return (
    <div className="relative isolate overflow-hidden rounded-xl">
      {backdrop && ratio < BACKDROP_BELOW_RATIO && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={backdrop}
          alt=""
          aria-hidden
          loading="lazy"
          decoding="async"
          className="pointer-events-none absolute inset-0 -z-10 hidden h-full w-full scale-125 object-cover blur-2xl sm:block dark:opacity-40"
        />
      )}
      {children}
    </div>
  );
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
  const poster = asset.thumb_url || null;
  const { loaded, failed, mount, onLoad, onError } = useFrameImage(poster);
  // Постера нет или он не открылся — рамка чёрная сразу: закрыть её нечему, а плеер,
  // который встанет на её место по нажатию, тоже чёрный.
  const covered = loaded || failed || !poster;

  const start = () => {
    flushSync(() => setActive(true));
    const video = boxRef.current?.querySelector("video");
    if (video) void video.play().catch(() => {});
  };

  return (
    <Stage backdrop={asset.thumb_url || null} ratio={ratio}>
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
            className={vx(
              FRAME,
              covered ? FRAME_ON : FRAME_BARE,
              FRAME_FOCUS,
              // Блик идёт по постеру — тихий в обеих темах.
              VS_SHEEN_ON_MEDIA,
              "vs-sheen group block h-full w-full cursor-pointer transition-colors disabled:cursor-default",
            )}
          >
            {poster && (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                ref={mount}
                src={poster}
                alt=""
                loading="lazy"
                decoding="async"
                onLoad={onLoad}
                onError={onError}
                className="h-full w-full object-contain"
              />
            )}
            <span className="absolute inset-0 grid place-items-center" aria-hidden>
              <svg
                viewBox="0 0 72 50"
                className="h-auto w-[68px] drop-shadow-[0_4px_14px_rgba(0,0,0,0.45)] transition-transform duration-200 group-hover:scale-110 group-active:scale-95 motion-reduce:transform-none"
              >
                <rect x="0" y="0" width="72" height="50" rx="13" fill="var(--accent)" />
                <path d="M29 15.5 L47 25 L29 34.5 Z" fill="var(--on-accent)" />
              </svg>
            </span>
            {durationText && (
              <span className={vx(VS_ON_MEDIA, "absolute bottom-2.5 right-2.5 tabular-nums")}>{durationText}</span>
            )}
          </button>
        )}
      </div>
    </Stage>
  );
}

function ResultImage({ asset, ratio, alt }: { asset: AssetJSON; ratio: number; alt: string }) {
  const src = asset.url || asset.thumb_url || null;
  // Не загрузилась — рамка остаётся светлой: на ней читается подпись, которую браузер ставит вместо картинки.
  const { loaded, mount, onLoad } = useFrameImage(src);
  if (!src) return null;
  return (
    <Stage backdrop={asset.thumb_url || src} ratio={ratio}>
      <a
        href={asset.url || src}
        target="_blank"
        rel="noopener noreferrer"
        style={frameStyle(ratio)}
        className={vx(
          FRAME,
          loaded ? FRAME_ON : FRAME_BARE,
          FRAME_FOCUS,
          "group mx-auto block cursor-zoom-in transition-colors",
        )}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          ref={mount}
          src={src}
          alt={alt}
          loading="lazy"
          decoding="async"
          onLoad={onLoad}
          className="h-full w-full object-contain"
        />
        <span
          className="pointer-events-none absolute right-2.5 top-2.5 grid size-8 place-items-center rounded-full bg-black/55 text-sm text-white opacity-0 backdrop-blur-sm transition-opacity duration-200 group-hover:opacity-100 group-focus-visible:opacity-100"
          aria-hidden
        >
          <FiMaximize2 />
        </span>
      </a>
    </Stage>
  );
}

/** Уголки видоискателя: по одному на каждый угол рамки. */
const FINDER_CORNERS = [
  "left-0 top-0 rounded-tl-[3px] border-l border-t",
  "right-0 top-0 rounded-tr-[3px] border-r border-t",
  "bottom-0 left-0 rounded-bl-[3px] border-b border-l",
  "bottom-0 right-0 rounded-br-[3px] border-b border-r",
];

/**
 * Рамка видоискателя в пропорции будущего кадра: пока идёт съёмка, видно,
 * что получится — вертикаль 9:16 или широкий 16:9. Высота одна и та же,
 * меняется только ширина, поэтому блок дубля не растёт вместе с кадром.
 */
function Viewfinder({ ratio }: { ratio: number }) {
  const r = Math.min(2.4, Math.max(0.5, Number.isFinite(ratio) && ratio > 0 ? ratio : 16 / 9));
  return (
    <span className="relative block h-16 max-w-full sm:h-24" style={{ aspectRatio: `${r}` }}>
      {/* На светлой «плёнке» контур в 7 % чернил теряется — в светлой теме он чуть плотнее. */}
      <span className="absolute inset-0 rounded-[3px] border border-vs-ink/[0.12] dark:border-vs-ink/[0.07]" />
      {FINDER_CORNERS.map((corner) => (
        <span key={corner} className={vx("absolute size-3 border-vs-accent/70", corner)} />
      ))}
      <span className="absolute left-1/2 top-1/2 h-px w-2.5 -translate-x-1/2 -translate-y-1/2 bg-vs-ink/25" />
      <span className="absolute left-1/2 top-1/2 h-2.5 w-px -translate-x-1/2 -translate-y-1/2 bg-vs-ink/25" />
    </span>
  );
}

/** За экраном «плёнка» и кольцо загрузки стоят: класс гасит анимацию у блока и у всего внутри. */
const OFFSCREEN = "[animation-play-state:paused] [&_*]:[animation-play-state:paused]";

/**
 * Идущий дубль — «плёнка проявляется»: полоса во всю ширину карточки с
 * видоискателем, статусом и шкалой по нижней кромке. Не рамка в размер кадра:
 * в узкой 9:16 статус и кнопки переносились бы по словам, а два видео и четыре
 * картинки в работе растянули бы ленту на несколько экранов.
 */
function OpenTake({
  take,
  ratio,
  label,
  onCancel,
  canceling,
}: {
  take: TakeLite;
  ratio: number;
  label: string;
  onCancel?: () => void;
  canceling?: boolean;
}) {
  const [ref, inView] = useInView<HTMLDivElement>();
  return (
    <div
      ref={ref}
      className={vx(
        "vs-film vs-grain relative isolate overflow-hidden rounded-xl border border-vs-ink/10",
        !inView && OFFSCREEN,
      )}
    >
      <span
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_85%_at_50%_0%,var(--accent-soft),transparent_72%)]"
        aria-hidden
      />
      <div className="relative flex min-h-40 flex-col sm:min-h-52">
        <div className="grid flex-1 place-items-center px-4 pt-5 sm:pt-6" aria-hidden>
          <Viewfinder ratio={ratio} />
        </div>
        <div className="p-3 sm:p-4">
          <TakeStatus take={take} onCancel={onCancel} canceling={canceling} />
        </div>
      </div>
      <TakeProgress take={take} label={label} />
    </div>
  );
}

/** Блок закрытого дубля без результата: цвет статуса — только в тонкой рамке и лёгкой заливке. */
const NOTE_BOX = "flex items-start gap-2.5 rounded-xl border p-3 text-sm leading-snug";
const NOTE_ICON = "grid size-7 shrink-0 place-items-center rounded-full text-sm";
const NOTE_NEUTRAL = "border-vs-ink/10 bg-vs-ink/[0.03] text-muted";

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

/**
 * Чем готовый дубль закончился для кошелька: «Списано N кр» или «Бесплатно —
 * за наш счёт». Метка в строке параметров карточки — рядом с моделью и
 * длительностью, а не между роликом и его подписью.
 */
export const TakeReceipt = memo(function TakeReceipt({
  take,
}: {
  take: Pick<TakeLite, "status" | "credits" | "charge_state">;
}) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  if (take.status !== "done") return null;
  const text =
    take.credits?.charged > 0
      ? t("run.charged", { defaultValue: "Списано {{n}} кр", n: take.credits.charged })
      : take.charge_state === "released"
        ? t("run.free", { defaultValue: "Бесплатно — за наш счёт" })
        : "";
  if (!text) return null;
  return (
    <span className={VS_TAG}>
      <FiCheckCircle className="shrink-0 text-status-ok" aria-hidden />
      {text}
    </span>
  );
});

export type TakeViewProps = {
  take: TakeLite;
  /** Входы кадра: виноватый вход (error.input) называем по его метке. */
  inputs: ShotInputJSON[];
  onCancel?: () => void;
  canceling?: boolean;
};

/**
 * Один дубль (§9.6): идущий — «плёнка» со статусом, секундомером и шкалой по
 * ETA; готовый — плеер или картинка на сцене; неудачный — причина по
 * error_code, виноватый вход и «Кредиты не списаны»; потерянный — тоже причина
 * по error_code; отменённый — своя строка. Что списано за готовый дубль,
 * показывает TakeReceipt в карточке.
 */
function TakeView({ take, inputs, onCancel, canceling }: TakeViewProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const open = isOpenStatus(take.status);
  const phrase = statusPhrase(take);
  const statusText = t(phrase.key, { defaultValue: phrase.ru, ...(phrase.params || {}) });
  const ratio = mediaRatio(take.result, take.effective?.aspect_ratio, take.kind);
  const noCharge = take.charge_state === "released" || (!open && take.status !== "done" && !take.credits?.charged);

  // И у failed, и у lost причину называет error.code: одна фраза на весь lost выдавала
  // «ролик снят, но не сохранён» за «не подтвердили запуск».
  const failure = takeErrorText(t, take);
  const culprit = take.error?.input ? inputs.find((i) => i.asset.uid === take.error?.input) : undefined;
  const culpritText = culprit
    ? t("run.culprit", { defaultValue: "Модели не подошло: {{label}}", label: inputLabel(t as Tr, culprit) })
    : "";

  // Живой регион переживает смену статуса — поэтому диктор скажет «Видео готово».
  const announce = failure ? `${statusText}. ${failure}` : statusText;

  // Дубль досняли на глазах у человека — кадр «проявляется» один раз. Готовые
  // кадры из истории и дубли, на которые перелистнули карусель, стоят сразу.
  const resultRef = useRef<HTMLDivElement | null>(null);
  const seen = useRef({ uid: take.uid, open });
  useLayoutEffect(() => {
    const before = seen.current;
    seen.current = { uid: take.uid, open };
    const el = resultRef.current;
    if (!el || before.uid !== take.uid || !before.open || take.status !== "done") return;
    if (typeof el.animate !== "function" || prefersReducedMotion()) return;
    // За экраном проявлять не для кого.
    const box = el.getBoundingClientRect();
    if (box.bottom < 0 || box.top > window.innerHeight) return;
    const develop = el.animate(
      [
        { opacity: 0, transform: "scale(0.985)", filter: "brightness(1.35)" },
        { opacity: 1, transform: "none", filter: "none" },
      ],
      { duration: 700, easing: "cubic-bezier(0.16, 1, 0.3, 1)" },
    );
    return () => develop.cancel();
  }, [take.uid, take.status, open]);

  // Рядом с отказом или отменой: человеку важно сразу увидеть, что денег не взяли.
  const noChargeNote =
    !open && take.status !== "done" && take.status !== "lost" && noCharge ? (
      <span className="inline-flex items-center gap-1.5 text-xs text-muted">
        <FiCheckCircle className="shrink-0 text-status-ok" aria-hidden />
        {t("run.noCharge", { defaultValue: "Кредиты не списаны" })}
      </span>
    ) : null;

  return (
    <div className="flex w-full flex-col gap-2" data-take={take.uid}>
      <span className="sr-only" role="status" aria-live="polite">
        {announce}
      </span>

      {open && <OpenTake take={take} ratio={ratio} label={statusText} onCancel={onCancel} canceling={canceling} />}

      {take.status === "done" && (
        <div ref={resultRef}>
          {take.result && (take.result.url || take.result.thumb_url) ? (
            take.kind === "video" || take.result.kind === "video" ? (
              <ResultVideo
                // У каждого дубля свой постер: перелистнули карусель — плеер прошлого дубля не остаётся.
                key={take.uid}
                asset={take.result}
                ratio={ratio}
                playLabel={t("run.actions.play", { defaultValue: "Смотреть" })}
                durationText={durationOf(take)}
              />
            ) : (
              <ResultImage asset={take.result} ratio={ratio} alt={statusText} />
            )
          ) : (
            <div className={vx(NOTE_BOX, NOTE_NEUTRAL, "items-center")}>
              <FiImage className="shrink-0" aria-hidden />
              {statusText}
            </div>
          )}
        </div>
      )}

      {take.status === "failed" && (
        <div className={vx(NOTE_BOX, "border-status-fail/25 bg-status-fail/[0.07]")}>
          <span className={vx(NOTE_ICON, "bg-status-fail/15 text-status-fail")} aria-hidden>
            <FiAlertTriangle />
          </span>
          <div className="flex min-w-0 flex-1 flex-col gap-1.5 pt-0.5">
            <p className="text-foreground">{failure}</p>
            {culpritText && <p className="text-xs font-medium text-status-fail">{culpritText}</p>}
            {noChargeNote}
          </div>
        </div>
      )}

      {take.status === "lost" && (
        <div className={vx(NOTE_BOX, "border-status-wait/25 bg-status-wait/[0.07]")}>
          <span className={vx(NOTE_ICON, "bg-status-wait/15 text-status-wait")} aria-hidden>
            <FiAlertTriangle />
          </span>
          <p className="min-w-0 flex-1 pt-0.5 text-foreground">{failure}</p>
        </div>
      )}

      {take.status === "canceled" && (
        <div className={vx(NOTE_BOX, NOTE_NEUTRAL, "flex-wrap items-center")}>
          <FiSlash className="shrink-0" aria-hidden />
          <span>{statusText}</span>
          {noChargeNote && <span className="ml-auto">{noChargeNote}</span>}
        </div>
      )}
    </div>
  );
}

export default memo(TakeView);

"use client";

import { useEffect, useEffectEvent, useRef, useState } from "react";
import type { RefObject } from "react";
import { VS_FOCUS, vx } from "./skin";
import { useReducedMotion } from "./useAutoplayAllowed";

/**
 * Тонкие сегменты под каруселью: сколько кадров и какой сейчас.
 *
 * С progressMs активный сегмент заполняется за это время — так видно, когда
 * карусель перелистнётся сама. Заполнение — настоящая анимация (Web Animations),
 * поэтому её можно поставить на паузу (paused) и узнать, что она дошла до
 * конца (onProgressEnd): владелец может листать по этому сигналу и не держать
 * свой таймер, который разошёлся бы с полоской. Без progressMs и при «меньше
 * движения» активный сегмент просто закрашен, а onProgressEnd не зовётся.
 * За экраном и в скрытой вкладке заполнение стоит само, без подсказки владельца.
 *
 * С onSelect сегменты — кнопки. Они узкие, и на телефоне в них трудно
 * попасть, поэтому главный жест там — смахивание самой карусели.
 *
 * С tone неактивные сегменты окрашены цветом состояния (дубли кадра: готов,
 * не получился, идёт) — исход каждого виден, не перелистывая. Активный всегда
 * золотой: его состояние и так на экране.
 *
 * Дорожка — «чернилами» темы (vs-ink): белая на тёмной сцене, тёмная на
 * светлой. Заполнение — золото для линий (vs-accent), как у шкалы дубля: яркое
 * в тёмной теме, тёмное в светлой. Яркое золото на «бумаге» и на белой
 * карточке сливалось с дорожкой, и активный сегмент был бледнее соседних.
 */
export type SegmentTone = "ok" | "fail" | "wait" | "progress" | "idle";

const TONE: Record<SegmentTone, string> = {
  ok: "bg-status-ok/55",
  fail: "bg-status-fail/60",
  wait: "bg-status-wait/55",
  progress: "bg-status-progress/60",
  idle: "bg-vs-ink/15",
};

export type SegmentsProps = {
  count: number;
  /** Номер активного сегмента, с нуля. */
  active: number;
  /** За сколько миллисекунд заполнится активный сегмент; null — без заполнения. */
  progressMs?: number | null;
  /** Заполнение стоит: курсор над каруселью, фокус внутри, играет ролик по нажатию. */
  paused?: boolean;
  /** Активный сегмент заполнился до конца. */
  onProgressEnd?: () => void;
  onSelect?: (index: number) => void;
  /** Подпись сегмента для скринридера («Кадр 3 из 12»); без неё — номер. */
  label?: (index: number) => string;
  /** Подпись всей группы. */
  ariaLabel?: string;
  /** Цвет состояния неактивного сегмента; без него все дорожки одинаковые. */
  tone?: (index: number) => SegmentTone;
  className?: string;
};

export type SegmentFillProps = {
  ms: number;
  paused: boolean;
  onEnd?: () => void;
  /**
   * По чьей видимости судить, что полоска на экране; без него — по её дорожке.
   * Нужен ряду, который прокручивается вбок (названия под каруселью): дорожка
   * активного чипа может уехать за его край, а сам ряд всё ещё перед глазами.
   */
  anchor?: RefObject<Element | null>;
};

/**
 * Заполнение активного сегмента — часы карусели. Ставится в дорожку с
 * position: relative и overflow: hidden. Снаружи нужен тем, кто рисует свои
 * сегменты (ряд названий под каруселью первого экрана), но листает по тем же
 * часам, что и Segments.
 */
export function SegmentFill({ ms, paused, onEnd, anchor }: SegmentFillProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const anim = useRef<Animation | null>(null);
  const ended = useEffectEvent(() => onEnd?.());
  // Полоска не на экране или вкладка скрыта: двигать нечего, и листать карусель вслепую незачем.
  const [unseen, setUnseen] = useState(false);
  const hold = paused || unseen;

  useEffect(() => {
    // Наблюдаем дорожку, а не саму заливку: та в начале сжата в ноль.
    const track = anchor?.current ?? ref.current?.parentElement;
    if (!track) return;
    let offscreen = false;
    const sync = () => setUnseen(offscreen || document.hidden);
    const io =
      typeof IntersectionObserver === "undefined"
        ? null
        : new IntersectionObserver((entries) => {
            offscreen = !entries[entries.length - 1].isIntersecting;
            sync();
          });
    io?.observe(track);
    document.addEventListener("visibilitychange", sync);
    return () => {
      io?.disconnect();
      document.removeEventListener("visibilitychange", sync);
    };
  }, [anchor]);

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof el.animate !== "function") return;
    const run = el.animate([{ transform: "scaleX(0)" }, { transform: "scaleX(1)" }], {
      duration: Math.max(1, ms),
      easing: "linear",
      fill: "both",
    });
    run.onfinish = () => ended();
    anim.current = run;
    return () => {
      run.onfinish = null;
      run.cancel();
      anim.current = null;
    };
  }, [ms]);

  // Отдельно от создания и после него: новая анимация тоже обязана встать на паузу.
  useEffect(() => {
    const run = anim.current;
    if (!run) return;
    if (hold) run.pause();
    else if (run.playState === "paused") run.play();
  }, [hold, ms]);

  return <span ref={ref} className="absolute inset-0 origin-left rounded-full bg-vs-accent" />;
}

export default function Segments({
  count,
  active,
  progressMs = null,
  paused = false,
  onProgressEnd,
  onSelect,
  label,
  ariaLabel,
  tone,
  className,
}: SegmentsProps) {
  const reduced = useReducedMotion();
  if (count <= 1) return null;

  const timed = typeof progressMs === "number" && progressMs > 0 && !reduced;
  const total = Math.floor(count);
  const current = Math.min(Math.max(0, Math.floor(active)), total - 1);

  const bar = (i: number) => (
    <span
      className={vx(
        "relative block h-[3px] w-full overflow-hidden rounded-full",
        tone && i !== current ? TONE[tone(i)] : TONE.idle,
      )}
    >
      {i === current &&
        (timed ? (
          // key: новый активный сегмент — заполнение с нуля.
          <SegmentFill key={current} ms={progressMs} paused={paused} onEnd={onProgressEnd} />
        ) : (
          <span className="absolute inset-0 rounded-full bg-vs-accent" />
        ))}
    </span>
  );

  return (
    <div
      role={onSelect ? "group" : "img"}
      aria-label={ariaLabel ?? `${current + 1} / ${total}`}
      className={vx("flex w-full items-center justify-center gap-1.5", className)}
    >
      {Array.from({ length: total }, (_, i) =>
        onSelect ? (
          <button
            key={i}
            type="button"
            onClick={() => onSelect(i)}
            aria-label={label ? label(i) : String(i + 1)}
            aria-current={i === current ? "true" : undefined}
            // Полоска 3 px, а нажимать удобно в полосу 44 px: её даёт невидимая область вокруг.
            className={vx(
              "relative flex h-3 min-w-0 max-w-10 flex-1 cursor-pointer items-center rounded-full before:absolute before:inset-x-0 before:-inset-y-4 before:content-['']",
              VS_FOCUS,
            )}
          >
            {bar(i)}
          </button>
        ) : (
          <span key={i} className="flex h-3 min-w-0 max-w-10 flex-1 items-center">
            {bar(i)}
          </span>
        ),
      )}
    </div>
  );
}

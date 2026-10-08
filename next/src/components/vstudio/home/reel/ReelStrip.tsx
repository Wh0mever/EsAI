"use client";

import { memo, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import LazyClip from "../../ui/LazyClip";
import Segments from "../../ui/Segments";
import { vx } from "../../ui/skin";
import { prefersReducedMotion } from "../../ui/useAutoplayAllowed";
import { useReveal } from "../../ui/useReveal";
import ReelCaption from "./ReelCaption";
import { REEL_ENTER, type ReelLayoutProps } from "./reelLayout";
import { REEL_INTERVAL_MS } from "./reelMath";
import { useReelAuto, useReelPause } from "./useReelPause";

/**
 * Карусель первого экрана на телефоне: лента с прилипанием, без 3D (§2.2).
 *
 * Листает сам браузер — пальцем, с инерцией и прилипанием к центру; страница
 * при этом прокручивается вверх-вниз как обычно. Активным считается кадр,
 * вставший в центр: в нём играет ролик и видна кнопка, остальные — постеры
 * чуть меньше и бледнее. Какой кадр в центре, узнаём по тому же
 * IntersectionObserver, что и видимость, — без обработчика прокрутки.
 */

/** Доля кадра в окне ленты, с которой он считается вставшим в центр. */
const CENTER_SHARE = 0.6;
const SHARE_STEPS = [0.5, 0.6, 0.7, 0.8, 0.9, 1];
/**
 * Кадр должен простоять в центре столько, чтобы стать активным. Без этого при
 * быстром пролистывании (и когда лента сама возвращается к началу) каждый
 * промелькнувший кадр успевал бы начать загрузку своего ролика.
 */
const SETTLE_MS = 120;

const CARD = "relative aspect-video w-[84vw] max-w-[420px] shrink-0 snap-center snap-always overflow-hidden rounded-2xl";
const CARD_LIVE = "bg-black transition-[scale,opacity,box-shadow] duration-300 ease-out motion-reduce:transition-none";
// Тень активного кадра. Лента обрезает всё, что ниже её полей (20 px): в тёмной
// теме срез чёрной тени на чёрной сцене не виден, на светлой он лёг бы ровной
// серой полосой под кадром — там тень короче и целиком помещается в поля.
const CARD_ON =
  "shadow-[0_6px_14px_color-mix(in_srgb,var(--vs-ink)_18%,transparent)] dark:shadow-[0_16px_36px_rgba(0,0,0,0.65)] group-focus-visible/reel:outline-2 group-focus-visible/reel:outline-offset-2 group-focus-visible/reel:outline-vs-accent/80";
// Соседний кадр бледнее — уходит в цвет сцены, какой бы она ни была.
const CARD_OFF = "scale-[0.96] opacity-70";
/** Поля по краям ленты: с ними первый и последний кадр тоже встают в центр. */
const SPACER = "w-[calc((100%-min(84vw,420px))/2-0.75rem)] shrink-0";
// Вертикальный запас внутри ленты — под тень активного кадра: прокручиваемый блок обрезает всё, что выходит за него.
const STRIP =
  "vs-noscroll group/reel relative -my-2 flex snap-x snap-mandatory gap-3 overscroll-x-contain py-5 focus-visible:outline-none";
const SKELETON = [0, 1, 2];

function ReelStrip({ items, loading, onUse }: ReelLayoutProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const reveal = useReveal<HTMLDivElement>();
  const root = useRef<HTMLDivElement>(null);
  const strip = useRef<HTMLDivElement>(null);
  const pause = useReelPause(root);
  const auto = useReelAuto();

  const [centered, setCentered] = useState(0);
  const [touching, setTouching] = useState(false);

  const count = items.length;
  // Список мог стать короче, пока лента на экране.
  const index = Math.min(centered, Math.max(0, count - 1));
  const idsKey = useMemo(() => items.map((item) => item.id).join("\n"), [items]);

  useEffect(() => {
    const box = strip.current;
    if (!box || !idsKey || typeof IntersectionObserver === "undefined") return;
    const cards = Array.from(box.querySelectorAll<HTMLElement>("[data-reel-card]"));
    const shares = new Map<Element, number>();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) shares.set(entry.target, entry.isIntersecting ? entry.intersectionRatio : 0);
        let best = -1;
        let top = 0;
        cards.forEach((card, i) => {
          const share = shares.get(card) ?? 0;
          if (share >= CENTER_SHARE && share > top) {
            top = share;
            best = i;
          }
        });
        // Между кадрами (ни один не в центре) активным остаётся прежний.
        if (best < 0) return;
        clearTimeout(timer);
        timer = setTimeout(() => setCentered(best), SETTLE_MS);
      },
      { root: box, threshold: SHARE_STEPS },
    );
    cards.forEach((card) => io.observe(card));
    return () => {
      clearTimeout(timer);
      io.disconnect();
    };
  }, [idsKey]);

  const toCard = (i: number) => {
    const box = strip.current;
    const card = box?.querySelector<HTMLElement>(`[data-reel-card="${i}"]`);
    if (!box || !card) return;
    const left = card.offsetLeft - (box.clientWidth - card.offsetWidth) / 2;
    box.scrollTo({ left, behavior: prefersReducedMotion() ? "auto" : "smooth" });
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    const next = index + (e.key === "ArrowLeft" ? -1 : 1);
    if (next < 0 || next >= count) return;
    e.preventDefault();
    // Кнопка кадра, который сейчас уедет из центра, станет недоступна — фокус
    // забираем на саму ленту, иначе он пропал бы и стрелки перестали бы листать.
    const box = strip.current;
    if (box && box !== document.activeElement && box.contains(document.activeElement)) {
      box.focus({ preventScroll: true });
    }
    toCard(next);
  };

  const frame = (i: number) =>
    t("home.reel.frame", { defaultValue: "Кадр {{n}} из {{total}}", n: i + 1, total: count });
  const running = auto && count > 1;

  return (
    <div ref={root} className="w-full" onKeyDown={onKeyDown} {...pause.focusHandlers}>
      <div ref={reveal} className="vs-reveal" style={REEL_ENTER}>
        <div
          ref={strip}
          role="group"
          aria-roledescription={t("home.reel.carousel", { defaultValue: "карусель" })}
          aria-label={t("home.reel.label", { defaultValue: "Примеры роликов" })}
          tabIndex={count > 1 ? 0 : -1}
          className={vx(STRIP, count > 0 ? "overflow-x-auto" : "overflow-hidden")}
          onTouchStart={() => setTouching(true)}
          onTouchEnd={() => setTouching(false)}
          onTouchCancel={() => setTouching(false)}
          {...pause.hoverHandlers}
        >
          <span aria-hidden className={SPACER} />
          {count === 0
            ? loading &&
              SKELETON.map((k) => <div key={k} aria-hidden className={vx(CARD, "vs-film", k > 0 && CARD_OFF)} />)
            : items.map((item, i) => {
                const on = i === index;
                return (
                  <div
                    key={item.id}
                    data-reel-card={i}
                    role="group"
                    aria-label={frame(i)}
                    className={vx(CARD, CARD_LIVE, on ? CARD_ON : CARD_OFF)}
                  >
                    <LazyClip
                      src={item.video}
                      poster={item.poster}
                      mode="active"
                      active={on}
                      alt=""
                      className="absolute inset-0"
                      rounded="rounded-2xl"
                    />
                    <span
                      aria-hidden
                      className="pointer-events-none absolute inset-0 rounded-2xl border border-vs-ink/10"
                    />
                    <ReelCaption item={item} shown={on} quick onUse={onUse} />
                    {!on && (
                      // Листать с клавиатуры — стрелками; сосед-кнопка нужен пальцу и мыши.
                      <button
                        type="button"
                        tabIndex={-1}
                        aria-label={
                          item.title
                            ? t("home.reel.show", { defaultValue: "Показать: {{title}}", title: item.title })
                            : frame(i)
                        }
                        onClick={() => toCard(i)}
                        className="absolute inset-0 cursor-pointer rounded-2xl"
                      />
                    )}
                  </div>
                );
              })}
          <span aria-hidden className={SPACER} />
        </div>

        {count > 1 ? (
          <Segments
            count={count}
            active={index}
            progressMs={running ? REEL_INTERVAL_MS : null}
            paused={pause.paused || touching}
            // С последнего кадра лента возвращается к первому.
            onProgressEnd={() => toCard(index + 1 < count ? index + 1 : 0)}
            className="mt-3 px-6"
          />
        ) : (
          // Место под сегменты держим и без них: кадры не должны сдвинуть страницу, когда придут.
          <div aria-hidden className="mt-3 h-3" />
        )}
      </div>
    </div>
  );
}

export default memo(ReelStrip);

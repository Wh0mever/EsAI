"use client";

import { useId } from "react";
import { useTranslation } from "react-i18next";
import { FiLoader, FiPlus, FiUser, FiZap } from "react-icons/fi";
import { useOnScreen } from "@/components/vstudio/home/tools/useOnScreen";
import LazyClip, { CLIP_BLANK } from "@/components/vstudio/ui/LazyClip";
import { VS_CARD, VS_ON_MEDIA, vx } from "@/components/vstudio/ui/skin";
import { useAutoplayAllowed } from "@/components/vstudio/ui/useAutoplayAllowed";
import type { CardPrice, Preset } from "../cartoonTypes";
import { CS_CARD_BTN, CS_SKELETON } from "../ui/cartoonSkin";

export type SceneCardProps = {
  preset: Preset;
  /** Цена и длительность при нынешних настройках дока. */
  price: CardPrice;
  /** Герой выбран: есть примерка и ролики «герой + сцена». */
  hero: boolean;
  /** Кадр выбранного героя в этой сцене; "" — не примеряли. */
  frame: string;
  /** Ролик пары «выбранный герой + сцена»; "" — ещё не снимали. */
  heroVideo: string;
  /** Эта сцена добавляется в ленту / какая-то сцена добавляется. */
  adding: boolean;
  addLocked: boolean;
  /** Эту сцену примеряют / какую-то сцену примеряют. */
  tryingOn: boolean;
  tryLocked: boolean;
  onAdd: (p: Preset) => void;
  onTryOn: (p: Preset) => void;
};

const BADGE = vx(VS_ON_MEDIA, "pointer-events-none absolute left-2 top-2");
const SPIN = "animate-spin motion-reduce:animate-none";

/**
 * Кадр с героем, ролика пары ещё нет: он медленно движется камерой, чтобы
 * сцена не выглядела застывшей, и честно подписан «кадр». Движется, только
 * пока виден и человек не просил «меньше движения». Им же оживает кадр
 * черновика в ленте сцен.
 */
export function LiveFrame({ src }: { src: string }) {
  const autoplay = useAutoplayAllowed();
  const [watch, seen] = useOnScreen<HTMLImageElement>();
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      ref={watch}
      src={src}
      alt=""
      loading="lazy"
      decoding="async"
      draggable={false}
      className={vx("absolute inset-0 h-full w-full object-cover", autoplay && seen && "studio-live")}
    />
  );
}

/**
 * Карточка сцены библиотеки. Ролик заводит LazyClip: под курсором или фокусом
 * с клавиатуры (наведение слушается на всей карточке — data-vs-clip-host), без
 * курсора — когда карточка на экране; сколько играет разом, решает общий
 * бюджет. «Меньше движения» или экономия трафика — постер и кнопка запуска.
 */
export default function SceneCard({
  preset: p,
  price,
  hero,
  frame,
  heroVideo,
  adding,
  addLocked,
  tryingOn,
  tryLocked,
  onAdd,
  onTryOn,
}: SceneCardProps) {
  const { t } = useTranslation("common");
  const titleId = useId();
  return (
    <div data-vs-clip-host="" className={vx(VS_CARD, "vs-card-hover flex w-full flex-col overflow-hidden")}>
      <div className={vx("relative aspect-video w-full overflow-hidden", CLIP_BLANK)}>
        {hero && heroVideo ? (
          <>
            {/* Эту пару уже снимали: показываем настоящий ролик сцены с
                выбранным героем — сразу и бесплатно. */}
            <LazyClip
              src={heroVideo}
              poster={frame || p.preview_poster || null}
              mode="hover"
              alt=""
              rounded="rounded-none"
              className="absolute inset-0"
            />
            <span className={BADGE}>{t("studio_ui.with_hero")}</span>
          </>
        ) : frame ? (
          <>
            <LiveFrame src={frame} />
            <span className={BADGE}>{t("studio_ui.hero_frame")}</span>
          </>
        ) : (
          <LazyClip
            src={p.preview_video || null}
            poster={p.preview_poster || null}
            mode="hover"
            alt=""
            rounded="rounded-none"
            className="absolute inset-0"
          />
        )}
      </div>
      <div className="flex flex-1 flex-col gap-1 p-2.5 sm:p-3">
        <h3 id={titleId} className="line-clamp-1 text-sm font-semibold text-foreground">
          {p.title}
        </h3>
        {p.subtitle && <p className="line-clamp-2 text-[12px] leading-snug text-muted-2">{p.subtitle}</p>}
        <p className="mt-auto inline-flex items-center gap-1 pt-1.5 text-[12px] tabular-nums text-muted">
          <FiZap aria-hidden className="shrink-0 text-vs-accent" />
          {price.credits != null
            ? t("studio_ui.price", { credits: price.credits, duration: price.duration })
            : t("studio_ui.price_unavailable", { defaultValue: "Цена сейчас недоступна" })}
        </p>
        {/* Низ карточки — столбиком: на телефоне цена, примерка и «В ленту» в
            одну строку не помещались, и главная кнопка уезжала за край (жалоба клиента). */}
        <div className="mt-1 flex flex-col gap-1.5">
          {hero && !frame && (
            <button
              type="button"
              onClick={() => onTryOn(p)}
              disabled={tryLocked}
              aria-busy={tryingOn || undefined}
              aria-describedby={titleId}
              title={t("studio_ui.try_on_hint")}
              className={vx(
                CS_CARD_BTN,
                "!border-transparent !bg-transparent !px-2 text-center leading-tight !text-muted hover:!bg-vs-ink/[0.06] hover:!text-foreground max-sm:!text-[12px]",
              )}
            >
              {tryingOn ? <FiLoader aria-hidden className={vx("shrink-0", SPIN)} /> : <FiUser aria-hidden className="shrink-0" />}
              {/* Цена — до нажатия (просьба клиента), гостю тоже:
                  бесплатной примерки без входа больше нет (11.10.2026). */}
              {p.tryon_credits != null
                ? t("studio_ui.try_on_price", { credits: p.tryon_credits })
                : t("studio_ui.try_on")}
            </button>
          )}
          <button
            type="button"
            onClick={() => onAdd(p)}
            disabled={addLocked}
            aria-busy={adding || undefined}
            aria-describedby={titleId}
            className={vx(CS_CARD_BTN, "text-center leading-tight hover:!border-vs-accent/45")}
          >
            {adding ? (
              <FiLoader aria-hidden className={vx("shrink-0", SPIN)} />
            ) : (
              <FiPlus aria-hidden className="shrink-0 text-vs-accent" />
            )}
            {t("studio_ui.add")}
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * Сетка-заглушка, пока грузится витрина: кадр, две строки и кнопка — почти
 * итоговая высота карточки. «Плёнка» переливается, только пока сетка на экране.
 */
export function SceneGridSkeleton({ count, className }: { count: number; className: string }) {
  const [watch, seen] = useOnScreen<HTMLUListElement>();
  return (
    <ul ref={watch} aria-hidden className={className}>
      {Array.from({ length: count }, (_, i) => (
        <li key={i} className="flex min-w-0">
          <div className={vx(VS_CARD, "flex w-full flex-col overflow-hidden")}>
            <span className={vx("block aspect-video w-full", seen ? "vs-film" : CS_SKELETON)} />
            <span className="flex flex-col gap-2 p-2.5 sm:p-3">
              <span className={vx("block h-3 w-3/4 rounded-full", CS_SKELETON)} />
              <span className={vx("block h-2.5 w-1/2 rounded-full", CS_SKELETON)} />
              <span className={vx("mt-3 block h-11 w-full rounded-full md:h-9", CS_SKELETON)} />
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}

"use client";

import Link from "next/link";
import { memo } from "react";
import { useTranslation } from "react-i18next";
import { FiArrowUpRight, FiVideo } from "react-icons/fi";
import { VS_BTN_GOLD, VS_ON_MEDIA, vx } from "../../ui/skin";
import type { ReelItem } from "../showreelData";

export type ReelCaptionProps = {
  item: ReelItem;
  /** Кадр активный: подпись видна, кнопка доступна. */
  shown: boolean;
  /** Лента телефона: кадр встаёт на место сам, под пальцем, — подписи ждать почти нечего. */
  quick?: boolean;
  onUse: (item: ReelItem) => void;
};

const ACTION = `${VS_BTN_GOLD} max-w-full !px-4 !text-[13px] md:!min-h-9`;

// Подпись выходит, когда кадр уже встал на место (сцена едет 600 мс и к этому
// времени почти остановилась), и по частям: сначала затемнение с названием,
// следом кнопка. Уходит быстро и вся разом.
const FADE = "transition-opacity ease-out motion-reduce:transition-none";
const RISE = "ease-[var(--vs-ease)] motion-reduce:transition-none";
const WAIT = { stage: ["delay-[340ms]", "delay-[430ms]"], strip: ["delay-100", "delay-200"] } as const;

/**
 * Подпись активного кадра карусели: название, откуда кадр и золотая кнопка.
 *
 * Лежит в каждом кадре, но видна только у активного: когда кадр уезжает вбок,
 * подпись гаснет вместе с ним, а у нового проступает, когда тот встал. Скрытая
 * подпись недоступна ни мыши, ни клавиатуре, ни скринридеру.
 *
 * Раскладка зависит от ширины самого кадра, а не окна. На широком — как в
 * макете: название с плашками слева внизу, кнопка справа. На узком (телефон,
 * сцена на невысоком экране) кнопка рядом с названием не помещается: плашки и
 * название уходят наверх, кнопка остаётся внизу. Середина кадра при этом
 * свободна — там стоит кнопка «Смотреть», когда ролики не заводятся сами.
 */
function ReelCaption({ item, shown, quick = false, onUse }: ReelCaptionProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });

  // Сцену мультстудии за работу видеостудии не выдаём: у неё своя подпись и своя дорога (§0.6).
  const cartoon = item.source === "cartoon";
  const source = cartoon ? t("home.reel.cartoon", { defaultValue: "Мультстудия" }) : item.subtitle;
  const seconds = item.duration ? Math.round(item.duration) : 0;
  const label = cartoon
    ? t("home.reel.hero", { defaultValue: "Снять со своим героем" })
    : item.prompt
      ? t("home.reel.like", { defaultValue: "Снять похожее" })
      : t("home.reel.model", { defaultValue: "Выбрать эту модель" });

  const badges = (source || seconds > 0) && (
    <div className="flex max-w-full items-center gap-1.5">
      {source && <span className={vx(VS_ON_MEDIA, "min-w-0 truncate")}>{source}</span>}
      {seconds > 0 && (
        <span className={vx(VS_ON_MEDIA, "shrink-0 tabular-nums")}>
          {t("home.reel.seconds", { defaultValue: "{{n}} с", n: seconds })}
        </span>
      )}
    </div>
  );

  const use = () => onUse(item);
  const tabIndex = shown ? undefined : -1;
  const action =
    cartoon && item.href ? (
      <Link href={item.href} draggable={false} tabIndex={tabIndex} onClick={use} className={ACTION}>
        <span className="min-w-0 truncate">{label}</span>
        <FiArrowUpRight aria-hidden className="shrink-0 text-[15px]" />
      </Link>
    ) : (
      <button type="button" tabIndex={tabIndex} onClick={use} className={ACTION}>
        <FiVideo aria-hidden className="shrink-0 text-[15px]" />
        <span className="min-w-0 truncate">{label}</span>
      </button>
    );

  const [first, second] = WAIT[quick ? "strip" : "stage"];

  return (
    <div
      inert={!shown}
      aria-hidden={shown ? undefined : true}
      className={vx(
        "@container pointer-events-none absolute inset-0 flex flex-col justify-end",
        FADE,
        shown ? vx("opacity-100 duration-500", first) : "opacity-0 duration-200",
      )}
    >
      <span aria-hidden className="vs-shade absolute inset-x-0 bottom-0 h-1/2 @[400px]:h-3/5" />
      {/* Узкий кадр: название наверху — ему нужно своё затемнение. */}
      <span
        aria-hidden
        className="absolute inset-x-0 top-0 h-1/2 bg-linear-to-b from-black/70 to-transparent @[400px]:hidden"
      />
      <div className="relative flex h-full flex-col items-start justify-between gap-2 p-3 @[400px]:h-auto @[400px]:flex-row @[400px]:items-end @[400px]:gap-3 @[400px]:p-4 @[560px]:p-5">
        {/* Название проявляется вместе с затемнением, здесь — только подъём. На узком кадре плашки над названием. */}
        <div
          className={vx(
            "flex min-w-0 max-w-full flex-col-reverse gap-1.5 transition-[translate] @[400px]:flex-col",
            RISE,
            shown ? vx("translate-y-0 duration-500", first) : "translate-y-2 duration-200",
          )}
        >
          {item.title && (
            <p className="truncate text-lg font-semibold text-white @[480px]:text-xl">{item.title}</p>
          )}
          {badges}
        </div>
        <div
          className={vx(
            "flex max-w-full shrink-0 transition-[opacity,translate]",
            RISE,
            shown
              ? vx("pointer-events-auto translate-y-0 opacity-100 duration-500", second)
              : "translate-y-2 opacity-0 duration-200",
          )}
        >
          {action}
        </div>
      </div>
    </div>
  );
}

export default memo(ReelCaption);

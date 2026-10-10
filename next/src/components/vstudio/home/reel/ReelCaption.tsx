"use client";

import Link from "next/link";
import { memo, useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiArrowDownLeft, FiArrowUpRight, FiVideo } from "react-icons/fi";
import { VS_BTN_GOLD, VS_ON_MEDIA, vx } from "../../ui/skin";
import type { ReelItem } from "../showreelData";
import { isPortrait, namedByModel } from "./reelMath";

export type ReelCaptionProps = {
  item: ReelItem;
  /**
   * Имя кадра (reelMath.reelNames): у ролика студии — сценарий, у сцены
   * мультстудии — её название. То же имя стоит на чипе под каруселью.
   */
  name: string;
  /** Кадр активный: подпись видна, кнопка доступна. */
  shown: boolean;
  /** Лента телефона: кадр встаёт на место сам, под пальцем, — подписи ждать почти нечего. */
  quick?: boolean;
  onUse: (item: ReelItem) => void;
};

// Кнопка светлеет и тогда, когда курсор над самим кадром (group/frame ставит кадр, по которому можно
// нажать): нажатие на кадр делает то же, что она.
const ACTION = `${VS_BTN_GOLD} max-w-full !px-4 !text-[13px] md:!min-h-9 group-hover/frame:brightness-[1.06]`;

// Подпись выходит, когда кадр уже встал на место (сцена едет 600 мс и к этому
// времени почти остановилась), и по частям: сначала затемнение с названием,
// следом кнопка. Уходит быстро и вся разом.
const FADE = "transition-opacity ease-out motion-reduce:transition-none";
const RISE = "ease-[var(--vs-ease)] motion-reduce:transition-none";
const WAIT = { stage: ["delay-[340ms]", "delay-[430ms]"], strip: ["delay-100", "delay-200"] } as const;

/**
 * Вставка с исходным фото (Image → Video) — в правом верхнем углу кадра: этот
 * угол свободен и на широком кадре, и на узком. На совсем узком кадре её нет:
 * там она встала бы на название. Белая кромка и чёрная тень — это слой поверх
 * видео, от темы он не зависит.
 */
const INSET =
  "absolute right-3 top-3 hidden transition-opacity duration-500 motion-reduce:transition-none @[280px]:block @[400px]:right-4 @[400px]:top-4 @[560px]:right-5 @[560px]:top-5";
const INSET_FRAME = "block overflow-hidden rounded-lg bg-black shadow-[0_6px_18px_rgb(0_0_0/0.5)] ring-1 ring-white/75";
// Размер вставки не зависит от фото: оно обрезается по рамке, как и сам ролик.
const INSET_WIDE = "aspect-video w-[68px] @[400px]:w-24 @[560px]:w-28";
const INSET_TALL = "aspect-[9/16] w-9 @[400px]:w-12 @[560px]:w-14";
const INSET_TAG =
  "absolute -bottom-2 left-1/2 flex -translate-x-1/2 items-center gap-0.5 whitespace-nowrap rounded-full bg-white px-1.5 py-px text-[9px] font-semibold leading-3 text-black shadow-[0_1px_4px_rgb(0_0_0/0.4)]";
/** На узком кадре название стоит наверху, рядом со вставкой: место под неё оставляем справа. */
const INSET_ROOM = "@[280px]:pr-[5.5rem] @[400px]:pr-0";

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
 *
 * Сама подпись нажатий не ловит (кроме кнопки): нажатие на кадр мимо кнопки
 * достаётся кадру — он применяет пример так же, как кнопка.
 */
function ReelCaption({ item, name, shown, quick = false, onUse }: ReelCaptionProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });

  // Состояния «по адресу»: сменилось фото — прежние отметки сами теряют силу.
  const [loaded, setLoaded] = useState<string | null>(null);
  const [broken, setBroken] = useState<string | null>(null);
  // Фото грузим, только когда кадр стал активным. Загруженное дальше не убираем: уходя, оно гаснет вместе с подписью.
  const frame = item.startFrame;
  const photo = (shown || loaded === frame) && frame !== broken ? frame : null;
  const photoMount = useCallback(
    (img: HTMLImageElement | null) => {
      // Картинка из кэша могла загрузиться раньше, чем React повесил onLoad.
      if (img && img.complete && img.naturalWidth > 0) setLoaded(frame);
    },
    [frame],
  );

  // Сцену мультстудии за работу видеостудии не выдаём: у неё своя подпись и своя дорога (§0.6).
  const cartoon = item.source === "cartoon";
  const source = cartoon ? t("home.reel.cartoon", { defaultValue: "Мультстудия" }) : item.subtitle;
  const seconds = item.duration ? Math.round(item.duration) : 0;
  // Назвать кадр нечем, кроме модели, — она уже стоит плашкой, второй раз заголовком не пишем.
  const title = namedByModel(name, item) ? "" : name;
  const label = cartoon
    ? t("home.reel.hero", { defaultValue: "Снять со своим героем" })
    : item.prompt
      ? t("home.reel.like", { defaultValue: "Снять похожее" })
      : t("home.reel.model", { defaultValue: "Выбрать эту модель" });
  // Скринридеру — с именем кадра: в карусели десятки одинаковых кнопок.
  const named = name ? `${label}: ${name}` : undefined;

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
      <Link href={item.href} draggable={false} tabIndex={tabIndex} aria-label={named} onClick={use} className={ACTION}>
        <span className="min-w-0 truncate">{label}</span>
        <FiArrowUpRight aria-hidden className="shrink-0 text-[15px]" />
      </Link>
    ) : (
      <button type="button" tabIndex={tabIndex} aria-label={named} onClick={use} className={ACTION}>
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
      {photo && (
        // «Фото → видео»: из чего сделан ролик. Проступает, когда картинка пришла; не пришла — вставки нет.
        <span className={vx(INSET, loaded === photo ? "opacity-100" : "opacity-0")}>
          <span className={vx(INSET_FRAME, isPortrait(item.aspect) ? INSET_TALL : INSET_WIDE)}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              ref={photoMount}
              src={photo}
              alt={t("home.reel.photoAlt", { defaultValue: "Фото, с которого начался ролик" })}
              loading="lazy"
              decoding="async"
              draggable={false}
              onLoad={() => setLoaded(photo)}
              onError={() => setBroken(photo)}
              className="h-full w-full object-cover"
            />
          </span>
          <span aria-hidden className={INSET_TAG}>
            {t("home.reel.photo", { defaultValue: "Фото" })}
            <FiArrowDownLeft className="text-[10px]" />
          </span>
        </span>
      )}
      <div className="relative flex h-full flex-col items-start justify-between gap-2 p-3 @[400px]:h-auto @[400px]:flex-row @[400px]:items-end @[400px]:gap-3 @[400px]:p-4 @[560px]:p-5">
        {/* Название проявляется вместе с затемнением, здесь — только подъём. На узком кадре плашки над названием. */}
        <div
          className={vx(
            "flex min-w-0 max-w-full flex-col-reverse gap-1.5 transition-[translate] @[400px]:flex-col",
            photo && INSET_ROOM,
            RISE,
            shown ? vx("translate-y-0 duration-500", first) : "translate-y-2 duration-200",
          )}
        >
          {title && (
            // Тень — на случай, когда кадр ещё не закрыт: в светлой теме заглушка под ним светлая,
            // и одного затемнения белому названию мало. На тёмном ролике её не видно. Тень
            // короткая: строку обрезает truncate, широкое свечение он срезал бы по её краям.
            <p className="truncate text-lg font-semibold text-white [text-shadow:0_1px_2px_rgb(0_0_0/0.8),0_0_6px_rgb(0_0_0/0.5)] @[480px]:text-xl">
              {title}
            </p>
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

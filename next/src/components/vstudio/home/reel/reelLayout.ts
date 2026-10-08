import type { CSSProperties } from "react";
import type { ReelItem } from "../showreelData";

/** Что получают обе раскладки карусели: сцена (от 768 px) и лента телефона. */
export type ReelLayoutProps = {
  items: ReelItem[];
  /** Имена кадров в том же порядке (reelMath.reelNames): подпись кадра и чип под каруселью. */
  names: readonly string[];
  /** Кадров ещё нет — заглушки в той же расстановке. */
  loading: boolean;
  onUse: (item: ReelItem) => void;
};

/** Карусель выходит на экран следом за заголовком, а не вместе с ним (vs-reveal читает --vs-delay). */
export const REEL_ENTER = { "--vs-delay": "120ms" } as CSSProperties;

/**
 * В карусели — ролики самой студии, а не сцены мультстудии. Источники в ней не
 * смешиваются (showreelData), поэтому судим по первому кадру. У роликов студии
 * под каруселью ряд названий, и нажатие на активный кадр применяет пример;
 * у сцен мультстудии всё по-прежнему: сегменты и кнопка-ссылка.
 */
export function isStudioReel(items: readonly ReelItem[]): boolean {
  return items[0]?.source === "vstudio";
}

/**
 * Нажали на сам активный кадр, а не на кнопку в нём. Кнопки («Смотреть»,
 * золотая) отвечают за себя сами — их нажатие сюда тоже всплывает, и без этой
 * проверки пример применился бы дважды.
 */
export function isBareClick(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest("a, button") === null;
}

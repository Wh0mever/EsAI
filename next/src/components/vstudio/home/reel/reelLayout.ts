import type { CSSProperties } from "react";
import type { ReelItem } from "../showreelData";

/** Что получают обе раскладки карусели: сцена (от 768 px) и лента телефона. */
export type ReelLayoutProps = {
  items: ReelItem[];
  /** Кадров ещё нет — заглушки в той же расстановке. */
  loading: boolean;
  onUse: (item: ReelItem) => void;
};

/** Карусель выходит на экран следом за заголовком, а не вместе с ним (vs-reveal читает --vs-delay). */
export const REEL_ENTER = { "--vs-delay": "120ms" } as CSSProperties;

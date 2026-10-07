/**
 * Первый экран: общий вид карточек «Модели студии» и «Инструменты режиссёра».
 *
 * Сами фактуры (vs-card, vs-sheen) описаны в app/globals.css и собраны в
 * ui/skin.ts; здесь — то, что нужно именно карточке-кнопке с картинкой сверху.
 */
import type { CSSProperties } from "react";
import { VS_CARD, VS_CARD_BTN, VS_FOCUS, vx } from "../../ui/skin";

/**
 * Карточка-кнопка: картинка сверху, текст под ней, блик при наведении.
 *  — Кольцо фокуса с !important: vs-card задаёт свою тень вне слоёв Tailwind и
 *    перебивает кольцо из VS_FOCUS — без этого фокус с клавиатуры не виден.
 *  — Нажатие через transform: именно его плавно ведёт vs-card.
 */
const CARD_BODY =
  "vs-sheen flex h-full w-full flex-col focus-visible:!ring-2 motion-safe:active:[transform:scale(0.985)]";

export const HOME_CARD = vx(VS_CARD_BTN, CARD_BODY);

/**
 * Та же карточка в выбранном состоянии. Без vs-card-hover: его :hover сильнее
 * vs-card-on и под курсором гасил бы золотую кромку выбранной карточки.
 */
export const HOME_CARD_ON = vx(VS_CARD, "vs-card-on cursor-pointer text-left", VS_FOCUS, CARD_BODY);

/** Ставится на секцию рядом с vs-reveal: по её vs-in выходят карточки. */
export const HOME_CELLS = "group/cells";

/**
 * Ячейка с карточкой: появляется, когда секция получила vs-in (useReveal), со
 * своей задержкой --vs-delay. При «меньше движения» видна сразу.
 */
export const HOME_CELL_IN =
  "translate-y-3 opacity-0 transition-[opacity,translate] delay-[var(--vs-delay,0ms)] duration-700 ease-[var(--vs-ease)] group-[.vs-in]/cells:translate-y-0 group-[.vs-in]/cells:opacity-100 motion-reduce:translate-y-0 motion-reduce:opacity-100 motion-reduce:transition-none";

const STAGGER_MS = 60;
/** Дальше пятой карточки задержка не растёт (§1: не больше 240 мс). */
const STAGGER_MAX = 4;

/** Задержка появления карточки по её месту в ряду. */
export function staggerStyle(index: number): CSSProperties {
  return { "--vs-delay": `${Math.min(index, STAGGER_MAX) * STAGGER_MS}ms` } as CSSProperties;
}

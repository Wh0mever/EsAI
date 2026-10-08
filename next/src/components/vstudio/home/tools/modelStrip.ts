/**
 * Первый экран, лента «Модели студии»: что написать на карточке модели и как
 * выбрать модель нажатием (§2.2 ModelStrip).
 *
 * Тексты заново не сочиняем. Метки возможностей и цена — те же, что в списке
 * моделей панели параметров (settingsModel, settingsText): иначе одна и та же
 * модель называлась бы по-разному в двух местах одного экрана. Здесь только
 * отбор — на карточку помещаются три метки, и первыми идут те, по которым
 * модель выбирают: свои фото, звук, длина ролика, качество.
 *
 * Выбор идёт теми же функциями, что и в панели (selectKind / selectModel):
 * память «последняя модель вида» и недонабранный seed ведут себя одинаково,
 * откуда бы человек ни выбрал модель.
 *
 * Модуль без React и разметки — его проверяет node-тест tools.test.mjs на
 * настоящем редьюсере.
 */
import type { Dispatch } from "react";
import type { ComposerState, ModelJSON, ModelsResponse, VsAction, VsKind } from "@/lib/vstudio/types";
import { modelBadges, switchKindChoice } from "../../settings/settingsModel";
import { fmtNum, type SettingsTextKey, type TextRef } from "../../settings/settingsText";
import { getKindMemory, selectKind, selectModel } from "../../settings/useRunSettingsSync";

type Models = Pick<ModelsResponse, "video" | "image">;
type Choice = Pick<ComposerState, "kind" | "model" | "params">;

/* ------------------------------------------------------------------ */
/* Метки и цена                                                        */
/* ------------------------------------------------------------------ */

/** Метка карточки: бейдж из панели параметров или своя — число пропорций у картинок. */
export type StripFact = { kind: "badge"; ref: TextRef } | { kind: "aspects"; n: number };

export const STRIP_FACTS_MAX = 3;

/** Что важнее при выборе модели — то и остаётся на карточке, когда меток больше трёх. */
const FACT_ORDER: readonly SettingsTextKey[] = [
  "settings.badge.refs",
  "settings.badge.audio",
  "settings.badge.duration",
  "settings.badge.resolution",
  "settings.badge.frames",
  "settings.badge.firstFrame",
];

export function stripFacts(model: ModelJSON, kind: VsKind): StripFact[] {
  const rank = (ref: TextRef) => {
    const i = FACT_ORDER.indexOf(ref.key);
    return i < 0 ? FACT_ORDER.length : i;
  };
  const facts: StripFact[] = [...modelBadges(model, kind)]
    .sort((a, b) => rank(a) - rank(b))
    .map((ref) => ({ kind: "badge", ref }));
  // У картинок нет ни длительности, ни качества — выбирают по форматам кадра.
  const aspects = model.caps.aspect_ratios?.length ?? 0;
  if (kind === "image" && aspects > 1) facts.push({ kind: "aspects", n: aspects });
  return facts.slice(0, STRIP_FACTS_MAX);
}

/** «от 160 кр» у видео, «12 кр за картинку» у картинок; null — цену не посчитать. */
export function stripPrice(model: ModelJSON, kind: VsKind): TextRef | null {
  const n = kind === "image" ? (model.per_image ?? model.price_from) : model.price_from;
  if (!n) return null;
  return { key: kind === "image" ? "settings.perImage" : "settings.priceFrom", params: { n: fmtNum(n) } };
}

/* ------------------------------------------------------------------ */
/* Шапка карточки                                                      */
/* ------------------------------------------------------------------ */

/**
 * Фон шапки: два пятна цвета вендора на подложке темы (--surface-2) — тёмной
 * в тёмной теме, светлой в светлой: там цвет вендора ложится пастелью. Чужих
 * кадров и логотипов на карточке модели нет — только цвет (§0.6).
 */
export function vendorArt(color: string): string {
  return [
    `radial-gradient(120% 140% at 0% 0%, color-mix(in srgb, ${color} 42%, transparent), transparent 62%)`,
    `radial-gradient(90% 120% at 100% 100%, color-mix(in srgb, ${color} 18%, transparent), transparent 60%)`,
    "var(--surface-2)",
  ].join(", ");
}

/** Число 0…1 из строки (FNV-1a): одна и та же модель всегда получает один и тот же рисунок. */
function seed(text: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0) / 0xffffffff;
}

/**
 * Центр «объектива» на шапке, в процентах её ширины и высоты. У моделей одного
 * вендора цвет и буква совпадают — кольца стоят по-разному, и карточки не
 * выглядят копиями друг друга.
 */
export function artLens(modelId: string): { x: number; y: number } {
  return {
    x: Math.round(56 + seed(modelId) * 30),
    y: Math.round(4 + seed(`${modelId}#`) * 44),
  };
}

/* ------------------------------------------------------------------ */
/* Выбор                                                               */
/* ------------------------------------------------------------------ */

/**
 * Нажали карточку модели (не под замком). Модель другого вида выбирается в два
 * шага: сначала вид — он сам ставит свою последнюю или первую доступную
 * модель, — потом нужная модель уже от этого состояния. Так параметры, с
 * которыми человек уходил из вида, возвращаются вместе с моделью.
 */
export function chooseModel(
  dispatch: Dispatch<VsAction>,
  models: Models | null,
  composer: Choice,
  kind: VsKind,
  modelId: string,
): void {
  const current: Choice = { kind: composer.kind, model: composer.model, params: composer.params };
  if (kind === current.kind) {
    selectModel(dispatch, models, current, modelId);
    return;
  }
  selectKind(dispatch, models, current, kind);
  // Стор уже на новом виде, а наш снимок composer — ещё нет. Что именно там
  // выбралось, считаем той же функцией и по той же памяти, что и selectKind.
  const landed = switchKindChoice(models, kind, current.params, getKindMemory());
  const base: Choice = landed ?? { kind, model: null, params: { aspect_ratio: current.params.aspect_ratio } };
  selectModel(dispatch, models, base, modelId);
}

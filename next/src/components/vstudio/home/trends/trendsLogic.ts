/**
 * «Тренды» первого экрана: сколько карточек видно и что на каждой написано.
 *
 * Ролики сюда ставит владелец в админке (место «Тренды» вместо карусели),
 * разбирает ответ витрины showreelData.trendItems. Модуль чистый (без React)
 * — его проверяет node-тест trends.test.mjs.
 */
import { isPortrait } from "../reel/reelMath";
import type { ReelItem } from "../showreelData";

/**
 * Карточек до «Показать ещё» и в каждой следующей порции: два ряда по четыре
 * на широком экране, четыре по два — на телефоне.
 */
export const TRENDS_PAGE = 8;

/** Сколько карточек видно после `extra` нажатий «Показать ещё». */
export function trendsLimit(extra: number): number {
  const pages = Number.isFinite(extra) ? Math.max(0, Math.trunc(extra)) : 0;
  return TRENDS_PAGE * (pages + 1);
}

/**
 * Что обещает карточка — как кнопка карусели: «Снять похожее», если владелец
 * открыл запрос; без запроса от работы остаётся только модель, и подпись
 * говорит об этом прямо.
 */
export type TrendAction = "like" | "model";

export function trendAction(item: Pick<ReelItem, "prompt">): TrendAction {
  return item.prompt ? "like" : "model";
}

export type TrendText = {
  /** Название; пусто — карточке нужно запасное (его подставляет компонент: оно переводится). */
  title: string;
  /** Вторая строка — модель; пусто, если она уже стоит названием. */
  subtitle: string;
};

/** Название и модель под кадром. Без названия карточку называет модель — второй раз её не пишем. */
export function trendText(item: Pick<ReelItem, "title" | "subtitle">): TrendText {
  if (item.title) return { title: item.title, subtitle: item.subtitle };
  return { title: item.subtitle, subtitle: "" };
}

/** Секунды для плашки на кадре; 0 — плашки нет. */
export function trendSeconds(item: Pick<ReelItem, "duration">): number {
  return item.duration && item.duration > 0 ? Math.max(1, Math.round(item.duration)) : 0;
}

/**
 * Как вписать ролик в рамку 16:9. Вертикальный обрезанный по рамке потерял бы
 * голову и ноги — его показываем целиком, с полями по бокам; остальные
 * заполняют рамку.
 */
export function trendFit(item: Pick<ReelItem, "aspect">): "cover" | "contain" {
  return isPortrait(item.aspect) ? "contain" : "cover";
}

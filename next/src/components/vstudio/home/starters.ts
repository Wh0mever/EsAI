/**
 * Заготовки первого экрана — тексты, которые в запрос подставили мы, а не
 * набрал человек: сценарии «С чего начать» (templates.ts) и запросы роликов
 * карусели и «Трендов».
 *
 * Запрос, в котором одна из них стоит нетронутой, можно заменить другой: между
 * примерами человек переключается свободно (feed/examples.starterReplaceable).
 * Список один на оба входа — чипы сценариев (feed/RunThread, HomeSlot) и
 * «Снять похожее» (StudioHome). Разойдись они, чип заменял бы пример, а пример
 * чип — нет, и в запросе остался бы текст одного ролика с моделью другого.
 *
 * Модуль без React — его проверяет node-тест home.test.mjs.
 */
import type { TFunction } from "i18next";
import type { ReelItem } from "./showreelData";
import { VS_TEMPLATES } from "./templates";

/** t из useTranslation("vstudio") или простая функция (тесты). */
type Translate = TFunction | ((key: string, options?: Record<string, unknown>) => unknown);

/** examples — ролики первого экрана, чьи запросы можно подставить: карусель и «Тренды». */
export function homeStarters(t: Translate, examples: readonly Pick<ReelItem, "prompt">[]): string[] {
  const fn = t as (key: string, options?: Record<string, unknown>) => unknown;
  const out: string[] = [];
  for (const tpl of VS_TEMPLATES) {
    // И перевод, и русский исходник: заготовку могли взять до смены языка.
    out.push(tpl.prompt);
    const translated = fn(`home.tpl.${tpl.id}.prompt`, { defaultValue: tpl.prompt });
    if (typeof translated === "string" && translated !== tpl.prompt) out.push(translated);
  }
  // Запрос есть только у роликов студии, и то если владелец разрешил его показывать.
  for (const item of examples) if (item.prompt) out.push(item.prompt);
  return out;
}

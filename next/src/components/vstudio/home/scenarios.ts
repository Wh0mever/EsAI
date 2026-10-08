/**
 * Сценарии карусели первого экрана: двенадцать случаев, ради которых приходят
 * в студию, — по одному ролику на каждый.
 *
 * Ключи — значения ShowcaseItem.category на сервере (core/vstudio/models.py),
 * порядок списка — порядок кадров в карусели. «Другое» сценарием не считается:
 * такая работа встаёт в хвост карусели и подписывается своим названием.
 *
 * Не путать со сценариями из templates.ts: те кладут в запрос заготовку, эти
 * называют готовые ролики. Названия переводятся ключами home.scenario.<ключ>
 * (ns vstudio), русский здесь — defaultValue.
 *
 * Модуль без React — его проверяет node-тест home.test.mjs.
 */
import type { TFunction } from "i18next";

export const SCENARIOS = [
  "film",
  "ad",
  "person",
  "car",
  "action",
  "scifi",
  "fashion",
  "music",
  "i2v",
  "anim",
  "real",
  "vertical",
] as const;

export type ScenarioKey = (typeof SCENARIOS)[number];

const OTHER = "other";

const TEXT: Record<ScenarioKey | typeof OTHER, { key: string; ru: string }> = {
  film: { key: "home.scenario.film", ru: "Киносцена" },
  ad: { key: "home.scenario.ad", ru: "Реклама товара" },
  person: { key: "home.scenario.person", ru: "Персонаж" },
  car: { key: "home.scenario.car", ru: "Автомобиль" },
  action: { key: "home.scenario.action", ru: "Экшен" },
  scifi: { key: "home.scenario.scifi", ru: "Фантастика" },
  fashion: { key: "home.scenario.fashion", ru: "Fashion" },
  music: { key: "home.scenario.music", ru: "Музыкальный клип" },
  i2v: { key: "home.scenario.i2v", ru: "Image → Video" },
  anim: { key: "home.scenario.anim", ru: "Анимация" },
  real: { key: "home.scenario.real", ru: "Реалистичная сцена" },
  vertical: { key: "home.scenario.vertical", ru: "Reels / TikTok" },
  other: { key: "home.scenario.other", ru: "Другое" },
};

/** t из useTranslation("vstudio") или простая функция (тесты). */
type Translate = TFunction | ((key: string, options?: Record<string, unknown>) => unknown);

export function isScenario(key: unknown): key is ScenarioKey {
  return typeof key === "string" && (SCENARIOS as readonly string[]).includes(key);
}

/**
 * Название сценария, каким его знает сервер, — русское, на любом языке сайта.
 * Им панель и команда съёмки подписывают работу, пока владелец не дал ей своё
 * название; так что в title оно значит «своего названия нет». Для ключа не из
 * списка — пустая строка.
 */
export function scenarioDefault(key: string | null | undefined): string {
  return isScenario(key) ? TEXT[key].ru : "";
}

/**
 * Короткое название сценария: «Реклама товара», «Image → Video». Для ключа не
 * из списка (и для null) — пустая строка: подпись тогда берут у самой работы.
 */
export function scenarioLabel(t: Translate, key: string | null | undefined): string {
  if (!isScenario(key) && key !== OTHER) return "";
  const text = TEXT[key];
  const fn = t as (key: string, options?: Record<string, unknown>) => unknown;
  const out = fn(text.key, { ns: "vstudio", defaultValue: text.ru });
  return typeof out === "string" ? out : text.ru;
}

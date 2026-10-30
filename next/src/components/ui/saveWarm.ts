/**
 * Прогрев «Скачать» на iPhone: решения без браузера — их проверяет
 * saveWarm.test.mjs обычным Node; сами загрузки ведёт tools/saveMedia.
 *
 * Системное окно «Сохранить видео» открывается только в жесте, а загрузка,
 * начатая нажатием, за SHARE_BUDGET_MS не успевает, и вместо окна человек ждёт
 * шторку. Поэтому файл начинает качаться раньше, пока кнопка на экране. Это
 * трафик человека и память телефона — отсюда все ограничения ниже.
 */
import type { EnvHints, SaveEnv } from "@/tools/saveEnv";

/** Кнопка считается увиденной, когда на экране не меньше половины её… */
export const WARM_MIN_RATIO = 0.5;
/** …и так не меньше секунды: при быстрой прокрутке ленты ничего не качаем. */
export const WARM_VISIBLE_MS = 1000;
/** Одновременно качается один файл: иначе прогрев отнимал бы канал у самого видео на экране. */
export const WARM_MAX_ACTIVE = 1;
/** В памяти не больше двух файлов: на экране телефона редко больше двух результатов сразу. */
export const WARM_MAX_KEPT = 2;
/** Больше этого в памяти не держим: тяжёлый файл догрузит шторка, как и раньше. */
export const WARM_MAX_BYTES = 30 * 1024 * 1024;

export const warmTooBig = (bytes: number): boolean => bytes > WARM_MAX_BYTES;

/**
 * Стоит ли здесь прогревать. Только iPhone и iPad: ограничение SHARE_BUDGET_MS есть
 * только там, на Android и компьютере saveMedia ждёт файл до конца.
 *
 * Встроенные браузеры (Telegram, Instagram) файл в системное окно обычно не отдают
 * и ведут в Safari — качать незачем. У установленного приложения в user agent нет
 * «Safari/», и detectEnv записывает его в wkwebview, поэтому смотрим ещё на standalone.
 */
export function warmAllowed(env: SaveEnv, hints: Pick<EnvHints, "hasShare" | "hasCanShare">, saveData: boolean): boolean {
  if (saveData || !env.handheld || env.os !== "ios") return false;
  if (env.inApp && !env.standalone) return false;
  return hints.hasShare && hints.hasCanShare;
}

/** Что сейчас лежит в памяти загрузок. */
export type WarmEntry = {
  url: string;
  /** Ещё качается. */
  loading: boolean;
  /**
   * Можно выбросить: файл взят прогревом, кнопки на экране нет, шторка его не держит
   * и сохранение не идёт. То, что начал сам человек нажатием, не выбрасываем.
   */
  spare: boolean;
};

export type WarmPlan = { start: string | null; evict: string | null };

const NOTHING: WarmPlan = { start: null, evict: null };

/**
 * Какой файл начать качать следующим. wanted — адреса кнопок на экране в порядке
 * появления, entries — загрузки в порядке начала, skip — адреса, для которых
 * прогрев уже не удался (велик, сервер отказал): не повторяем его по кругу.
 * Место в памяти кончилось — вытесняем самый старый файл, ушедший с экрана.
 */
export function planWarm(wanted: string[], entries: WarmEntry[], skip: ReadonlySet<string>): WarmPlan {
  const known = new Set(entries.map((e) => e.url));
  const start = wanted.find((url) => !known.has(url) && !skip.has(url));
  if (!start) return NOTHING;
  if (entries.filter((e) => e.loading).length >= WARM_MAX_ACTIVE) return NOTHING;
  if (entries.length < WARM_MAX_KEPT) return { start, evict: null };
  if (entries.length > WARM_MAX_KEPT) return NOTHING;
  const spare = entries.find((e) => e.spare && !e.loading);
  return spare ? { start, evict: spare.url } : NOTHING;
}

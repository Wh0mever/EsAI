"use client";

/**
 * Витрина первого экрана: настоящие ролики для карусели и «Трендов».
 *
 * Два публичных запроса — работы видеостудии и сцены мультстудии (названия
 * сцен переводит сервер, поэтому запрос несёт язык). Каждый может не ответить
 * сам по себе: тогда его часть считается пустой, а первый экран живёт на
 * второй. Разбор ответов и выбор кадров карусели делает showreelData.ts.
 * Вместе с работами студии приходят «Тренды» и размер карусели — настройка
 * владельца.
 *
 * Кэш общий для вкладки и привязан к языку: первый экран монтируется заново
 * при каждом возврате к «Новой генерации», а сцены за 10 минут не меняются.
 * Параллельные вызовы делят один запрос. Неудачный ответ держим недолго, а
 * после сбоя сети или сервера пробуем ещё сами — иначе один обрыв связи
 * оставил бы первый экран без роликов, пока человек не уйдёт и не вернётся.
 *
 * В режиме фикстур запросы всё равно идут на сервер: локальный стенд их
 * проксирует, а заглушек для витрины в фикстурах нет.
 */
import { useEffect, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";
import { apiLang, type ApiLang } from "@/lib/apiLang";
import { fetchData } from "@/tools/fetchData";
import {
  EMPTY_SHOWREEL,
  REEL_SIZE,
  buildShowreel,
  cartoonItems,
  reelSizeOf,
  studioItems,
  trendItems,
  type ReelItem,
  type ShowreelData,
} from "./showreelData";

export type { ReelItem } from "./showreelData";

export type Showreel = ShowreelData & {
  /** «Тренды»: ролики, которые владелец поставил в сетку под инструментами, а не в карусель. */
  trends: ReelItem[];
  /** Показать пока нечего: первый запрос ещё в пути. */
  loading: boolean;
};

export const SHOWREEL_TTL_MS = 10 * 60 * 1000;
/** Сколько помним ответ, в котором хотя бы один источник не ответил. */
export const SHOWREEL_RETRY_MS = 30 * 1000;
/** Сколько раз подряд пробуем сами после сбоя (30 с, 1 мин, 2 мин). */
const MAX_RETRIES = 3;

type Entry = {
  view: Showreel;
  at: number;
  ok: boolean;
  studio: ReelItem[];
  cartoon: ReelItem[];
  /** Сколько роликов студии владелец отвёл карусели (reel_size в ответе витрины). */
  size: number;
  trends: ReelItem[];
  /** Отпечаток содержимого: тот же ответ не должен перерисовывать карусель. */
  sig: string;
};

const LOADING: Showreel = { ...EMPTY_SHOWREEL, trends: [], loading: true };

const cache = new Map<ApiLang, Entry>();
const inflight = new Map<ApiLang, Promise<void>>();
const retryTimers = new Map<ApiLang, ReturnType<typeof setTimeout>>();
const attempts = new Map<ApiLang, number>();
/** Последнее показанное — на время, пока витрина на новом языке ещё в пути. */
let lastView: Showreel | null = null;
const listeners = new Set<() => void>();

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => {
    listeners.delete(onChange);
  };
}

function isFresh(entry: Entry | undefined, now: number): boolean {
  return !!entry && now - entry.at < (entry.ok ? SHOWREEL_TTL_MS : SHOWREEL_RETRY_MS);
}

/** Сбой, который пройдёт сам: нет сети, сервер перегружен или упал. 403 и 404 сами не пройдут. */
const isTransient = (res: { ok: boolean; status: number }) =>
  !res.ok && (res.status === 0 || res.status === 429 || res.status >= 500);

function planRetry(lang: ApiLang): void {
  const done = attempts.get(lang) ?? 0;
  if (done >= MAX_RETRIES || retryTimers.has(lang)) return;
  attempts.set(lang, done + 1);
  const timer = setTimeout(() => {
    retryTimers.delete(lang);
    // Первый экран уже закрыт — спросим при следующем открытии.
    if (listeners.size > 0) void loadShowreel(lang);
  }, SHOWREEL_RETRY_MS * 2 ** done);
  retryTimers.set(lang, timer);
}

/**
 * Что показать на этом языке прямо сейчас. Пока своя витрина не пришла, но
 * была другая (человек сменил язык), оставляем её: подписи сменятся через
 * мгновение, а заглушки на месте роликов мигнули бы заметнее.
 */
function snapshotFor(lang: ApiLang): Showreel {
  return cache.get(lang)?.view ?? lastView ?? LOADING;
}

/** Что уже есть в кэше (без запроса) — то же, что отдаст хук. */
export function peekShowreel(lang: ApiLang): Showreel {
  return snapshotFor(lang);
}

/**
 * Загрузить витрину (или взять из кэша). Устаревшую показываем, пока идёт
 * новая. retryFailed — не ждать срока у неудачного ответа (вернулась сеть).
 */
export function loadShowreel(lang: ApiLang, retryFailed = false): Promise<void> {
  const cached = cache.get(lang);
  if (isFresh(cached, Date.now()) && !(retryFailed && cached && !cached.ok)) return Promise.resolve();
  const running = inflight.get(lang);
  if (running) return running;

  const promise = Promise.all([
    fetchData<unknown>("vstudio/showcase/", "GET", null, false),
    fetchData<unknown>(`cartoon/presets/?lang=${lang}`, "GET", null, false),
  ])
    .then(([showcase, presets]) => {
      const prev = cache.get(lang);
      // Источник не ответил — его часть пустая. Но при обновлении сбой не
      // должен стереть ролики, которые уже на экране: берём прежние.
      const studio = showcase.ok ? studioItems(showcase.data) : (prev?.studio ?? []);
      const cartoon = presets.ok ? cartoonItems(presets.data) : (prev?.cartoon ?? []);
      // Размер карусели приходит тем же ответом, что и ролики: не ответил — держим
      // прежний, иначе на время сбоя карусель из 24 роликов сжалась бы до 12.
      const size = showcase.ok ? reelSizeOf(showcase.data) : (prev?.size ?? REEL_SIZE);
      // «Тренды» приходят тем же ответом: не ответил — тоже держим прежние.
      const trends = showcase.ok ? trendItems(showcase.data) : (prev?.trends ?? []);
      // Размер — в отпечатке: владелец мог сменить его, не тронув ни одного ролика.
      const sig = JSON.stringify([studio, cartoon, size, trends]);
      const view =
        prev && prev.sig === sig ? prev.view : { ...buildShowreel(studio, cartoon, size), trends, loading: false };
      const ok = showcase.ok && presets.ok;
      cache.set(lang, { view, at: Date.now(), ok, studio, cartoon, size, trends, sig });
      lastView = view;
      if (ok) attempts.delete(lang);
      else if (isTransient(showcase) || isTransient(presets)) planRetry(lang);
    })
    .catch(() => {
      // fetchData не бросает; сюда попадём только при ошибке разбора — тогда
      // показываем пустую витрину, а не вечную загрузку.
      if (cache.has(lang)) return;
      const view = { ...EMPTY_SHOWREEL, trends: [], loading: false };
      cache.set(lang, { view, at: Date.now(), ok: false, studio: [], cartoon: [], size: REEL_SIZE, trends: [], sig: "" });
    })
    .finally(() => {
      inflight.delete(lang);
      for (const l of [...listeners]) l();
    });
  inflight.set(lang, promise);
  return promise;
}

/** Для тестов: забыть всё. */
export function resetShowreelCache(): void {
  for (const timer of retryTimers.values()) clearTimeout(timer);
  retryTimers.clear();
  attempts.clear();
  cache.clear();
  inflight.clear();
  lastView = null;
}

const onServer = () => LOADING;

export function useShowreel(): Showreel {
  const { i18n } = useTranslation("vstudio", { useSuspense: false });
  const lang = apiLang(i18n.language);
  const view = useSyncExternalStore(subscribe, () => snapshotFor(lang), onServer);

  useEffect(() => {
    void loadShowreel(lang);
    // Вкладку держат открытой сутками: при возврате на неё обновляем устаревшее.
    const onVisible = () => {
      if (document.visibilityState === "visible") void loadShowreel(lang);
    };
    const onOnline = () => void loadShowreel(lang, true);
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", onOnline);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", onOnline);
    };
  }, [lang]);

  return view;
}

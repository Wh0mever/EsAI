"use client";

/**
 * Видеостудия: список моделей (GET vstudio/models/) с кэшем на 10 минут.
 *
 * Кэш общий для всей вкладки (модуль, а не компонент): панель параметров,
 * мобильный чип и контейнер студии зовут хук одновременно, а запрос уходит
 * один. Сервер кэширует ответ на 10 минут по тарифу — чаще спрашивать
 * бессмысленно, а цены и locked могут поменяться, поэтому и дольше держать
 * нельзя. Кэш привязан к человеку (user_id из токена): вход, выход и смена
 * аккаунта сразу дают свежий список.
 *
 * Когда перезапрашиваем:
 *   - при первом использовании и когда кэш старше 10 минут (вкладку держат сутками);
 *   - при возврате на вкладку, если кэш устарел;
 *   - по balance:refresh, если в списке есть модели под замком: после оплаты
 *     они открываются, и замок не должен висеть ещё 10 минут.
 */
import { useCallback, useEffect, useEffectEvent, useSyncExternalStore } from "react";
import { getModels } from "@/lib/vstudio/api";
import type { ModelsResponse, VsError, VsResult } from "@/lib/vstudio/types";
import { getToken } from "@/tools/fetchData";

export const MODELS_TTL_MS = 10 * 60 * 1000;

export type ModelsSnapshot = {
  data: ModelsResponse | null;
  loading: boolean;
  error: VsError | null;
  /** Чей это список: user_id из токена или "guest". */
  who: string | null;
  /** Когда пришёл ответ (Date.now()); 0 — ещё не было. */
  at: number;
};

const EMPTY: ModelsSnapshot = { data: null, loading: false, error: null, who: null, at: 0 };

let snapshot: ModelsSnapshot = EMPTY;
let inflight: { who: string; promise: Promise<VsResult<ModelsResponse>> } | null = null;
const listeners = new Set<() => void>();

function emit(next: ModelsSnapshot) {
  snapshot = next;
  for (const l of listeners) l();
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

const getSnapshot = () => snapshot;
const getServerSnapshot = () => EMPTY;

/** Кто сейчас вошёл: user_id из JWT (payload не проверяем — это только ключ кэша). */
export function currentIdentity(): string {
  try {
    const token = getToken("access") || getToken("refresh");
    if (!token) return "guest";
    const part = token.split(".")[1] || "";
    const json = JSON.parse(atob(part.replace(/-/g, "+").replace(/_/g, "/")));
    const id = json?.user_id ?? json?.sub;
    return id != null ? `u${id}` : "user";
  } catch {
    return "user";
  }
}

/** Гость — нет ни access, ни refresh (замок у такого ведёт на вход, а не в пэйволл). */
export function isGuest(): boolean {
  try {
    return !getToken("access") && !getToken("refresh");
  } catch {
    return true;
  }
}

function isFresh(s: ModelsSnapshot, who: string, now: number): boolean {
  return !!s.data && s.who === who && now - s.at < MODELS_TTL_MS;
}

/**
 * Загрузить модели (или взять из кэша). Параллельные вызовы делят один запрос.
 * force — мимо кэша (после оплаты, по кнопке «Повторить»).
 */
export async function loadVStudioModels(opts: { force?: boolean } = {}): Promise<VsResult<ModelsResponse>> {
  const who = currentIdentity();
  const now = Date.now();
  if (!opts.force && isFresh(snapshot, who, now) && snapshot.data) {
    return { ok: true, status: 200, data: snapshot.data };
  }
  if (inflight && inflight.who === who) return inflight.promise;

  // Список другого человека не показываем ни секунды: его замки и цены — не наши.
  const keep = snapshot.who === who ? snapshot.data : null;
  emit({ ...snapshot, data: keep, who, loading: true, error: null, at: keep ? snapshot.at : 0 });

  const promise = getModels().then((res) => {
    if (inflight?.promise === promise) inflight = null;
    // Пока шёл запрос, мог смениться аккаунт — такой ответ уже не нужен.
    if (currentIdentity() !== who) return res;
    if (res.ok) emit({ data: res.data, loading: false, error: null, who, at: Date.now() });
    else if (res.error.code !== "aborted") emit({ ...snapshot, loading: false, error: res.error });
    else emit({ ...snapshot, loading: false });
    return res;
  });
  inflight = { who, promise };
  return promise;
}

/** Сбросить кэш: следующий useVStudioModels / loadVStudioModels спросит сервер. */
export function invalidateVStudioModels(): void {
  if (snapshot.at) emit({ ...snapshot, at: 0 });
}

/** Что уже есть в кэше (без запроса). */
export function peekVStudioModels(): ModelsResponse | null {
  return snapshot.data;
}

/** Для тестов: полностью забыть кэш. */
export function resetVStudioModelsCache(): void {
  inflight = null;
  emit(EMPTY);
}

export type UseVStudioModels = {
  data: ModelsResponse | null;
  loading: boolean;
  error: VsError | null;
  /** Перезапросить мимо кэша. */
  reload: () => Promise<VsResult<ModelsResponse>>;
};

/**
 * Модели студии. onLoaded вызывается при каждом новом ответе (первая загрузка
 * и обновления раз в 10 минут) — туда удобно положить dispatch models/loaded.
 */
export function useVStudioModels(opts: { enabled?: boolean; onLoaded?: (data: ModelsResponse) => void } = {}): UseVStudioModels {
  const enabled = opts.enabled !== false;
  const snap = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const revalidate = useEffectEvent(() => {
    if (!enabled) return;
    const who = currentIdentity();
    if (!isFresh(snapshot, who, Date.now())) void loadVStudioModels();
  });

  useEffect(() => {
    revalidate();
    const onFocus = () => revalidate();
    const onVisible = () => {
      if (document.visibilityState === "visible") revalidate();
    };
    // После оплаты премиум-модели открываются: обновить замки сразу.
    const onBalance = () => {
      const d = snapshot.data;
      if (enabled && d && [...d.video, ...d.image].some((m) => m.locked)) void loadVStudioModels({ force: true });
    };
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("balance:refresh", onBalance);
    return () => {
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("balance:refresh", onBalance);
    };
  }, [enabled]);

  const onLoaded = useEffectEvent((data: ModelsResponse) => opts.onLoaded?.(data));
  useEffect(() => {
    if (snap.data) onLoaded(snap.data);
  }, [snap.data]);

  const reload = useCallback(() => loadVStudioModels({ force: true }), []);

  return { data: snap.data, loading: snap.loading, error: snap.error, reload };
}

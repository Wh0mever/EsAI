/**
 * Опрос открытых дублей (§9.4) без React: расписание, пауза на скрытой
 * вкладке, отступ после ошибок, поиск «закрылся» — чтобы это проверял
 * node-тест (takePoller.test.mjs), а не ожидание на стенде.
 *
 * Правила:
 * - GET takes/?ids= каждые 3 с, пока среди открытых есть дубль моложе 2 минут
 *   (считаем от момента, когда мы его увидели: часы телефона могут врать);
 *   дальше каждые 6 с;
 * - скрытая вкладка — пауза; wake() (visibilitychange, online) — сразу запрос;
 * - открытых нет — таймеров нет;
 * - ошибка сети или 5xx — отступ 6 → 12 → 24 → 30 с, 429 — 15 с;
 *   401/403 — пауза до нового набора дублей или wake();
 * - uid, которого сервер 3 раза подряд не вернул (удалён, чужой), больше
 *   не спрашиваем — иначе опрос не остановился бы никогда.
 *
 * Один запрос за раз: медленный ответ не наслаивается на следующий тик.
 */
import { isOpenStatus } from "./feedLogic";
import type { TakeLite, Uid, VsError, VsResult } from "@/lib/vstudio/types";

export const POLL_FAST_MS = 3000;
export const POLL_SLOW_MS = 6000;
export const POLL_FAST_WINDOW_MS = 120_000;
export const POLL_MAX_BACKOFF_MS = 30_000;
export const POLL_THROTTLED_MS = 15_000;
/** Сколько раз подряд сервер может «не знать» uid, прежде чем мы перестанем спрашивать. */
export const POLL_GONE_AFTER = 3;

export type SettledTake = {
  take: TakeLite;
  /** Каким дубль был у нас до ответа (undefined — стор его не знал). */
  prev: TakeLite | undefined;
};

type Handle = unknown;

export type TakePollerDeps = {
  poll: (uids: Uid[]) => Promise<VsResult<{ items: TakeLite[] }>>;
  /** Текущая запись стора — чтобы понять, что дубль закрылся именно сейчас. */
  known: (uid: Uid) => TakeLite | undefined;
  /** Свежие дубли (все, что вернул сервер) и те, что закрылись этим ответом. */
  onItems: (items: TakeLite[], settled: SettledTake[]) => void;
  onError?: (error: VsError) => void;
  onGone?: (uids: Uid[]) => void;
  now?: () => number;
  hidden?: () => boolean;
  timers?: { set: (fn: () => void, ms: number) => Handle; clear: (h: Handle) => void };
};

export type TakePoller = {
  /** Набор открытых дублей из стора. Пустой — опрос замирает. */
  setOpen: (uids: readonly Uid[]) => void;
  /** Вкладка снова видна или сеть вернулась: спросить сейчас. */
  wake: () => void;
  /** Размонтирование: таймеры сняты, ответы в полёте выбрасываются. */
  stop: () => void;
  /** Для тестов и отладки. */
  inspect: () => { open: Uid[]; active: Uid[]; scheduled: number | null; inFlight: boolean; failures: number; paused: boolean };
};

/** Пауза до следующего запроса. */
export function pollDelay(o: { now: number; firstSeen: readonly number[]; failures: number; lastCode: string | null }): number {
  if (o.lastCode === "throttled") return POLL_THROTTLED_MS;
  if (o.failures > 0) return Math.min(POLL_MAX_BACKOFF_MS, POLL_FAST_MS * 2 ** o.failures);
  const young = o.firstSeen.some((t) => o.now - t < POLL_FAST_WINDOW_MS);
  return young ? POLL_FAST_MS : POLL_SLOW_MS;
}

/**
 * Дубли, которые этим ответом перешли в конечный статус. Спрашиваем мы
 * только открытые, но стор мог закрыть дубль и сам (ответ «Отменить»,
 * соседний опрос) — такие второй раз не празднуем.
 */
export function settledFrom(items: readonly TakeLite[], known: (uid: Uid) => TakeLite | undefined): SettledTake[] {
  const out: SettledTake[] = [];
  for (const take of items) {
    if (isOpenStatus(take.status)) continue;
    const prev = known(take.uid);
    if (prev && !isOpenStatus(prev.status)) continue;
    out.push({ take, prev });
  }
  return out;
}

const STOP_CODES = new Set(["unauthorized", "vstudio_disabled", "premium_locked"]);

export function createTakePoller(deps: TakePollerDeps): TakePoller {
  const now = deps.now || (() => Date.now());
  const hidden = deps.hidden || (() => false);
  const timers = deps.timers || {
    set: (fn: () => void, ms: number) => setTimeout(fn, ms),
    clear: (h: Handle) => clearTimeout(h as ReturnType<typeof setTimeout>),
  };

  let open: Uid[] = [];
  const firstSeen = new Map<Uid, number>();
  const missing = new Map<Uid, number>();
  const gone = new Set<Uid>();
  let timer: Handle | null = null;
  let scheduledMs: number | null = null;
  /** Когда сработает таймер (по now()): новый дубль не должен ждать чужой медленный тик. */
  let dueAt = 0;
  let inFlight = false;
  let wakeAfter = false;
  let failures = 0;
  let lastCode: string | null = null;
  let paused = false;
  let stopped = false;

  const active = () => open.filter((u) => !gone.has(u));

  function clear() {
    if (timer !== null) timers.clear(timer);
    timer = null;
    scheduledMs = null;
    dueAt = 0;
  }

  function schedule(ms: number) {
    clear();
    if (stopped || paused || !active().length) return;
    scheduledMs = ms;
    dueAt = now() + ms;
    timer = timers.set(() => {
      timer = null;
      scheduledMs = null;
      void tick();
    }, ms);
  }

  function nextDelay() {
    const seen = active().map((u) => firstSeen.get(u) ?? now());
    return pollDelay({ now: now(), firstSeen: seen, failures, lastCode });
  }

  async function tick() {
    if (stopped || paused) return;
    const uids = active();
    if (!uids.length) return;
    // Скрытая вкладка: не спрашиваем, ждём wake() от visibilitychange.
    // Сервер в это время перестаёт видеть vstudio:seen и пришлёт пуш сам.
    if (hidden()) return;
    if (inFlight) {
      wakeAfter = true;
      return;
    }
    inFlight = true;
    let res: VsResult<{ items: TakeLite[] }>;
    try {
      res = await deps.poll(uids);
    } catch {
      res = { ok: false, status: 0, error: { status: 0, code: "network", message: "", data: {} } };
    }
    inFlight = false;
    if (stopped) return;

    if (res.ok) {
      failures = 0;
      lastCode = null;
      const items = Array.isArray(res.data?.items) ? res.data.items : [];
      const got = new Set(items.map((t) => t.uid));
      const newlyGone: Uid[] = [];
      for (const u of uids) {
        if (got.has(u)) {
          missing.delete(u);
          continue;
        }
        const n = (missing.get(u) || 0) + 1;
        missing.set(u, n);
        if (n >= POLL_GONE_AFTER) {
          gone.add(u);
          newlyGone.push(u);
        }
      }
      const settled = settledFrom(items, deps.known);
      // Закрытые больше не спрашиваем, даже если стор обновится позже.
      const closed = new Set(items.filter((t) => !isOpenStatus(t.status)).map((t) => t.uid));
      if (closed.size) {
        open = open.filter((u) => !closed.has(u));
        for (const u of closed) {
          firstSeen.delete(u);
          missing.delete(u);
        }
      }
      if (items.length) deps.onItems(items, settled);
      if (newlyGone.length) deps.onGone?.(newlyGone);
    } else {
      const code = String(res.error.code || "");
      if (code === "aborted") {
        // Отмену делает только stop(); сюда не попадаем, но и не считаем ошибкой.
      } else if (STOP_CODES.has(code) || res.status === 401 || res.status === 403) {
        paused = true;
        deps.onError?.(res.error);
        return;
      } else {
        failures += 1;
        lastCode = code;
        deps.onError?.(res.error);
      }
    }

    if (wakeAfter) {
      wakeAfter = false;
      schedule(0);
      return;
    }
    schedule(nextDelay());
  }

  return {
    setOpen(uids) {
      const next = Array.from(new Set(uids));
      const before = new Set(open);
      const added = next.filter((u) => !before.has(u));
      open = next;
      const keep = new Set(next);
      for (const u of [...firstSeen.keys()]) if (!keep.has(u)) firstSeen.delete(u);
      for (const u of [...missing.keys()]) if (!keep.has(u)) missing.delete(u);
      for (const u of [...gone]) if (!keep.has(u)) gone.delete(u);
      const t = now();
      for (const u of added) if (!firstSeen.has(u)) firstSeen.set(u, t);
      // Новый дубль — повод снова попробовать после 401 (человек мог войти заново).
      if (added.length) paused = false;
      if (!active().length) {
        clear();
        return;
      }
      if (inFlight) return;
      if (timer === null) {
        schedule(nextDelay());
        return;
      }
      // Свежий дубль (только что нажали «Создать» или «Повторить») при
      // медленном 6-секундном ритме старых: первый ответ — через 3 с, не позже.
      // Отступ после ошибок не сокращаем — сеть от нового дубля не починится.
      if (added.length && failures === 0) {
        const want = nextDelay();
        if (now() + want < dueAt) schedule(want);
      }
    },
    wake() {
      if (stopped) return;
      paused = false;
      if (!active().length || hidden()) return;
      if (inFlight) {
        wakeAfter = true;
        return;
      }
      clear();
      void tick();
    },
    stop() {
      stopped = true;
      clear();
    },
    inspect() {
      return { open: [...open], active: active(), scheduled: scheduledMs, inFlight, failures, paused };
    },
  };
}

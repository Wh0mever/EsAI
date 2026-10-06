/**
 * Слежение за QR-счётом, пока на витрине висит баннер «незавершённая оплата».
 *
 * Зачем. Баннер рисуется по одному ответу сервера, а этот ответ почти всегда
 * вчерашний: адрес статуса сам GoPay не спрашивает, он только ставит
 * перепроверку в очередь и отдаёт старую строку. Человек, который только что
 * оплатил в приложении банка и вернулся на перезагруженную страницу, видел бы
 * «незавершённая оплата… осталось 12:40» — и это тот самый момент, когда
 * платят второй раз (возврата через API у GoPay нет).
 *
 * Поэтому, пока баннер на экране, спрашиваем статус ещё: первый раз через
 * ~4 с (перепроверка, поставленная первым запросом, к этому времени прошла),
 * дальше раз в 7 с. Оплачен или зачисляется — просим открыть экран QR (он
 * покажет «Оплачено» и обновит баланс). Закрыт без оплаты — баннер убираем.
 *
 * Без React и без window — расписание проверяет node-тест
 * (qrBannerWatch.test.mjs), а не ожидание на стенде.
 *
 * Правила:
 * - один запрос за раз; скрытая вкладка — пауза, wake() — сразу запрос;
 * - сбой сети или сервера — отступ 8 → 16 → 30 с; после шести сбоев подряд
 *   молчим до wake();
 * - после срока счёта смотрим ещё минуту: оплата могла уйти на последней
 *   секунде. Дальше — только по wake().
 */
import { clockSkewMs, isQrInvoice, normalizeQrInvoice, shouldStopPolling } from "@/lib/qrpay";
import type { QrInvoice, QrUiState } from "@/types/qrpay";

/** Первый повтор: перепроверка у GoPay, поставленная первым запросом, уже прошла. */
export const BANNER_FIRST_RECHECK_MS = 4000;
export const BANNER_POLL_MS = 7000;
export const BANNER_MAX_BACKOFF_MS = 30_000;
/** Сколько смотрим за счётом после его срока (как и экран оплаты). */
export const BANNER_GRACE_MS = 60_000;
/** Столько сбоев подряд — и ждём, пока человек вернётся на вкладку. */
export const BANNER_GIVE_UP_AFTER = 6;

export type QrBannerVerdict = "open" | "keep" | "drop";

/**
 * Что делать баннеру с очередным состоянием счёта.
 * open — оплачен или зачисляется: открыть экран QR;
 * keep — ждёт оплаты (или только что истёк): следим дальше;
 * drop — закрыт без оплаты: звать не к чему.
 */
export function bannerVerdict(state: QrUiState, deadlineMs: number, nowMs: number): QrBannerVerdict {
  if (state === "paid" || state === "processing") return "open";
  if (state === "awaiting_payment") return "keep";
  // Истёкший досматриваем минуту — то же правило, что у экрана оплаты.
  if (state === "expired" && !shouldStopPolling(state, deadlineMs, nowMs)) return "keep";
  return "drop";
}

/** Пауза до следующего запроса; null — по расписанию больше не спрашиваем. */
export function bannerPollDelayMs(answers: number, failures: number, deadlineMs: number, nowMs: number): number | null {
  if (failures >= BANNER_GIVE_UP_AFTER) return null;
  if (Number.isFinite(deadlineMs) && nowMs - deadlineMs > BANNER_GRACE_MS) return null;
  const base = answers <= 1 ? BANNER_FIRST_RECHECK_MS : BANNER_POLL_MS;
  if (failures > 0) return Math.min(BANNER_MAX_BACKOFF_MS, base * 2 ** failures);
  return base;
}

type Handle = unknown;

/** Ответ адреса статуса — в форме fetchData. */
export type QrStatusAnswer = { ok: boolean; status: number; data?: unknown };

export type QrBannerSeed = {
  invoice: QrInvoice;
  /** часы сервера минус часы браузера на момент этого ответа */
  skewMs: number;
};

export type QrBannerWatchDeps = {
  fetch: (orderId: string) => Promise<QrStatusAnswer>;
  /** счёт всё ещё ждёт оплаты: свежие срок и часы сервера для баннера */
  onUpdate?: (invoice: QrInvoice, skewMs: number) => void;
  /** оплачен или зачисляется — открыть экран QR на этом заказе */
  onOpen: (invoice: QrInvoice) => void;
  /** закрыт без оплаты или счёта больше нет — баннер убрать */
  onClosed: (orderId: string) => void;
  now?: () => number;
  hidden?: () => boolean;
  timers?: { set: (fn: () => void, ms: number) => Handle; clear: (h: Handle) => void };
};

export type QrBannerWatch = {
  /** Вкладка снова видна (вернулись из приложения банка): спросить сейчас. */
  wake: () => void;
  /** Баннер убран: таймер снят, ответ в полёте выбрасывается. */
  stop: () => void;
  /** Для тестов и отладки. */
  inspect: () => { scheduled: number | null; inFlight: boolean; answers: number; failures: number; done: boolean };
};

/** Срок счёта по часам браузера; NaN — срок неизвестен. */
function localDeadlineMs(invoice: QrInvoice, skewMs: number): number {
  const parsed = invoice.expires_at ? Date.parse(invoice.expires_at) : NaN;
  return Number.isFinite(parsed) ? parsed - skewMs : NaN;
}

/**
 * Начать следить за счётом. `seed` — уже полученный ответ «ждёт оплаты»
 * (от useQrReturn): тогда первый запрос — повторный, через ~4 с. Без него
 * спрашиваем сразу.
 */
export function createQrBannerWatch(
  orderId: string,
  deps: QrBannerWatchDeps,
  seed?: QrBannerSeed | null
): QrBannerWatch {
  const now = deps.now ?? (() => Date.now());
  const hidden = deps.hidden ?? (() => false);
  const timers = deps.timers ?? {
    set: (fn: () => void, ms: number) => setTimeout(fn, ms),
    clear: (h: Handle) => clearTimeout(h as ReturnType<typeof setTimeout>),
  };

  let timer: Handle | null = null;
  let scheduled: number | null = null;
  let inFlight = false;
  /** stop() или окончательный ответ: больше ничего не делаем */
  let done = false;
  /** сколько раз сервер уже ответил «ждёт оплаты» */
  let answers = 0;
  let failures = 0;
  let deadlineMs = NaN;
  /** растёт на каждый запрос и на stop(): ответ на устаревший запрос не нужен */
  let ticket = 0;

  const usableSeed =
    seed && seed.invoice.order_id === orderId && seed.invoice.ui_state === "awaiting_payment" ? seed : null;
  if (usableSeed) {
    answers = 1;
    deadlineMs = localDeadlineMs(usableSeed.invoice, usableSeed.skewMs);
  }

  const clear = () => {
    if (timer !== null) timers.clear(timer);
    timer = null;
    scheduled = null;
  };

  const schedule = () => {
    clear();
    if (done) return;
    const delay = bannerPollDelayMs(answers, failures, deadlineMs, now());
    if (delay === null) return;
    scheduled = delay;
    timer = timers.set(() => {
      timer = null;
      scheduled = null;
      // На скрытой вкладке не спрашиваем: вернётся — wake() спросит сразу.
      if (hidden()) return;
      void request();
    }, delay);
  };

  const finish = () => {
    done = true;
    ticket += 1;
    clear();
  };

  async function request(): Promise<void> {
    if (done || inFlight) return;
    const mine = ++ticket;
    inFlight = true;
    let res: QrStatusAnswer;
    try {
      res = await deps.fetch(orderId);
    } catch {
      res = { ok: false, status: 0 };
    }
    if (mine !== ticket) return; // остановили или перезапустили, пока летел ответ
    inFlight = false;

    if (res.ok && isQrInvoice(res.data)) {
      const invoice = normalizeQrInvoice(res.data);
      const at = now();
      const skewMs = clockSkewMs(invoice.server_time, at);
      const deadline = localDeadlineMs(invoice, skewMs);
      const verdict = bannerVerdict(invoice.ui_state, deadline, at);
      if (verdict === "open") {
        finish();
        deps.onOpen(invoice);
        return;
      }
      if (verdict === "drop") {
        finish();
        deps.onClosed(orderId);
        return;
      }
      failures = 0;
      answers += 1;
      deadlineMs = deadline;
      // Истёкший счёт баннеру не показываем — только досматриваем.
      if (invoice.ui_state === "awaiting_payment") deps.onUpdate?.(invoice, skewMs);
      schedule();
      return;
    }
    if (res.status === 404) {
      // Счёта нет или он чужой (в браузере вошли под другим аккаунтом).
      finish();
      deps.onClosed(orderId);
      return;
    }
    if (res.status === 401 || res.status === 403) {
      // Сессии нет: спрашивать не от чьего имени. Баннер не трогаем.
      finish();
      return;
    }
    failures += 1;
    schedule();
  }

  if (usableSeed) schedule();
  else if (!hidden()) void request();

  return {
    wake: () => {
      if (done || hidden()) return;
      // Человек вернулся — сети даём новую попытку без накопленного отступа.
      failures = 0;
      clear();
      void request();
    },
    stop: finish,
    inspect: () => ({ scheduled, inFlight, answers, failures, done }),
  };
}

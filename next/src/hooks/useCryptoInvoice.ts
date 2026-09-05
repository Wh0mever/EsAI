"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchData } from "@/tools/fetchData";
import { clearCryptoSession } from "@/lib/cryptoSession";
import type { CryptoInvoice } from "@/types/crypto";

/**
 * Опрос состояния криптосчёта, пока человек платит.
 *
 * Решения, которые здесь важны:
 *  - опрашиваем цепочкой setTimeout, а не интервалом: медленный ответ не
 *    должен накладываться сам на себя;
 *  - чем дольше ждём, тем реже спрашиваем (5 -> 10 -> 15 с): первые минуты
 *    самые важные, дальше человек уже просто ждёт подтверждения сети;
 *  - на скрытой вкладке не опрашиваем вовсе, при возврате — сразу;
 *  - останавливаемся ТОЛЬКО по конечному статусу, а не по таймеру: перевод,
 *    отправленный в последнюю секунду, всё равно дойдёт и будет зачислен;
 *  - ошибки сети не показываем красным. Человек в этот момент отправляет
 *    деньги, и «ошибка» на экране читается как «деньги пропали».
 */

export type UseCryptoInvoice = {
  invoice: CryptoInvoice | null;
  secondsLeft: number;
  polling: boolean;
  /** несколько неудачных опросов подряд — показываем тихое «повторяем…» */
  stale: boolean;
  notFound: boolean;
  refresh: () => void;
};

const TERMINAL = new Set(["paid", "expired", "failed"]);
// Сколько ещё опрашиваем после нуля на таймере: сеть могла подтвердить перевод
// на последней секунде.
const GRACE_MS = 3 * 60 * 1000;

function intervalFor(elapsedMs: number): number {
  if (elapsedMs < 5 * 60 * 1000) return 5000;
  if (elapsedMs < 10 * 60 * 1000) return 10000;
  return 15000;
}

export async function fetchCryptoInvoice(orderId: string) {
  return fetchData<CryptoInvoice>(`plans/purchase/crypto/${orderId}/`, "GET", null, true);
}

export function useCryptoInvoice(
  orderId: string | null,
  options: { initial?: CryptoInvoice | null; onPaid?: (invoice: CryptoInvoice) => void } = {}
): UseCryptoInvoice {
  const { initial = null, onPaid } = options;
  const [invoice, setInvoice] = useState<CryptoInvoice | null>(initial);
  const [secondsLeft, setSecondsLeft] = useState(initial?.seconds_left ?? 0);
  const [polling, setPolling] = useState(false);
  const [failures, setFailures] = useState(0);
  const [notFound, setNotFound] = useState(false);

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startedAt = useRef<number>(Date.now());
  const paidNotified = useRef(false);
  const requestId = useRef(0);
  const onPaidRef = useRef(onPaid);
  onPaidRef.current = onPaid;

  const stopped = useRef(false);

  // --- таймер обратного отсчёта: считаем от срока, а не тикаем счётчик ------
  useEffect(() => {
    if (!invoice?.expires_at) return;
    const deadline = new Date(invoice.expires_at).getTime();
    const tick = () => setSecondsLeft(Math.max(0, Math.round((deadline - Date.now()) / 1000)));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [invoice?.expires_at]);

  const poll = useCallback(async () => {
    if (!orderId || stopped.current) return;
    const id = ++requestId.current;
    setPolling(true);
    const res = await fetchCryptoInvoice(orderId);
    if (id !== requestId.current) return; // пришёл ответ на устаревший запрос
    setPolling(false);

    if (res.status === 404) {
      setNotFound(true);
      stopped.current = true;
      // Счёта больше нет — баннеру «незавершённая оплата» не за что цепляться.
      clearCryptoSession();
      return;
    }
    if (!res.ok || !res.data) {
      setFailures((n) => n + 1);
      return;
    }

    setFailures(0);
    setInvoice(res.data);

    if (res.data.ui_state === "paid" && !paidNotified.current) {
      paidNotified.current = true;
      clearCryptoSession();
      try {
        window.dispatchEvent(new CustomEvent("balance:refresh"));
      } catch {
        // не критично: баланс подтянется при следующей загрузке
      }
      onPaidRef.current?.(res.data);
    }
    if (TERMINAL.has(res.data.ui_state)) {
      const deadline = res.data.expires_at ? new Date(res.data.expires_at).getTime() : 0;
      // Просроченный счёт ещё некоторое время держим под наблюдением: деньги
      // могли уйти перед самым закрытием.
      if (res.data.ui_state !== "expired" || Date.now() - deadline > GRACE_MS) {
        stopped.current = true;
      }
    }
  }, [orderId]);

  // --- сама цепочка опросов -------------------------------------------------
  useEffect(() => {
    if (!orderId) return;
    stopped.current = false;
    paidNotified.current = false;
    startedAt.current = Date.now();

    const schedule = () => {
      if (timer.current) clearTimeout(timer.current);
      if (stopped.current) return;
      const base = intervalFor(Date.now() - startedAt.current);
      const backoff = failures > 0 ? Math.min(15000, base * 2 ** failures) : base;
      timer.current = setTimeout(async () => {
        if (document.hidden) {
          schedule();
          return;
        }
        await poll();
        schedule();
      }, backoff);
    };

    // Если счёт пришёл вместе с ответом на создание, первый опрос не нужен —
    // экран уже показывает адрес и сумму.
    if (!initial) void poll();
    schedule();

    const onVisible = () => {
      if (!document.hidden && !stopped.current) void poll();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      if (timer.current) clearTimeout(timer.current);
      document.removeEventListener("visibilitychange", onVisible);
    };
    // failures входит в зависимости намеренно: после сбоя пересобираем
    // расписание с увеличенной паузой.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orderId, poll, failures]);

  const refresh = useCallback(() => {
    if (!orderId) return;
    stopped.current = false;
    setFailures(0);
    void poll();
  }, [orderId, poll]);

  return { invoice, secondsLeft, polling, stale: failures >= 3, notFound, refresh };
}

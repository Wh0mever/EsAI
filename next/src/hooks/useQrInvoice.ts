"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchData } from "@/tools/fetchData";
import { clearQrSession } from "@/lib/qrSession";
import {
  clockSkewMs,
  isQrInvoice,
  normalizeQrInvoice,
  pollDelayMs,
  secondsLeft as secondsLeftAt,
  shouldStopPolling,
} from "@/lib/qrpay";
import type { QrInvoice, QrUiState } from "@/types/qrpay";

/**
 * Опрос состояния QR-счёта, пока человек платит.
 *
 * Механика та же, что у криптосчёта (useCryptoInvoice):
 *  - цепочка setTimeout, а не интервал: медленный ответ не накладывается сам
 *    на себя;
 *  - на скрытой вкладке не опрашиваем, при возврате — сразу. Именно так
 *    ловится «оплатил в приложении банка и вернулся», если страница выжила;
 *  - ошибки сети красным не показываем: человек в этот момент платит, и слово
 *    «ошибка» читается как «деньги пропали». После трёх сбоев — тихое
 *    «повторяем…».
 *
 * Отличия: QR живёт минуты, поэтому опрос чаще (3–5 с), а отсчёт идёт по
 * часам СЕРВЕРА — с телефоном, у которого сбито время, таймер иначе показал
 * бы «истёк» на живом коде или наоборот.
 */

export type UseQrInvoice = {
  invoice: QrInvoice | null;
  secondsLeft: number;
  polling: boolean;
  /** несколько неудачных опросов подряд — показываем тихое «повторяем…» */
  stale: boolean;
  notFound: boolean;
  refresh: () => void;
  /** подставить только что созданный счёт и опрашивать уже его */
  replace: (invoice: QrInvoice) => void;
};

export async function fetchQrInvoice(orderId: string) {
  return fetchData<QrInvoice>(`plans/purchase/qr/${encodeURIComponent(orderId)}/`, "GET", null, true);
}

/** Срок счёта по часам браузера: срок сервера минус расхождение часов. */
function localDeadline(invoice: QrInvoice, receivedAtMs: number): number {
  const parsed = invoice.expires_at ? Date.parse(invoice.expires_at) : NaN;
  if (Number.isFinite(parsed)) return parsed - clockSkewMs(invoice.server_time, receivedAtMs);
  // Срок не пришёл — считаем от «осталось секунд» на момент ответа.
  return receivedAtMs + invoice.seconds_left * 1000;
}

type Tracked = {
  /** номер заказа, который опрашиваем */
  id: string | null;
  /** номер из пропсов, по которому собрано это состояние */
  source: string | null;
  invoice: QrInvoice | null;
  /** расхождение часов сервера и браузера на последнем ответе */
  skewMs: number;
  /** номер «запуска» цепочки: растёт при замене счёта и ручной проверке */
  run: number;
};

export function useQrInvoice(
  orderId: string | null,
  options: { initial?: QrInvoice | null; onPaid?: (invoice: QrInvoice) => void } = {}
): UseQrInvoice {
  const { initial = null, onPaid } = options;

  const [tracked, setTracked] = useState<Tracked>(() => {
    const first = initial && isQrInvoice(initial) ? normalizeQrInvoice(initial) : null;
    return {
      id: first?.order_id || orderId,
      source: orderId,
      invoice: first,
      skewMs: first ? clockSkewMs(first.server_time, Date.now()) : 0,
      run: 0,
    };
  });
  const [left, setLeft] = useState(() => tracked.invoice?.seconds_left ?? 0);
  const [polling, setPolling] = useState(false);
  const [failures, setFailures] = useState(0);
  const [notFound, setNotFound] = useState(false);

  // Открыли окно на другом заказе, не размонтируя хук: начинаем с чистого листа.
  if (tracked.source !== orderId) {
    setTracked({ id: orderId, source: orderId, invoice: null, skewMs: 0, run: tracked.run + 1 });
    setFailures(0);
    setNotFound(false);
    setLeft(0);
  }

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const requestId = useRef(0);
  const stopped = useRef(false);
  const failuresRef = useRef(0);
  const startedAt = useRef(0);
  const processingSince = useRef<number | null>(null);
  const paidNotified = useRef<string | null>(null);
  // Что сейчас на экране — для расписания опроса, которое живёт вне рендера.
  const stateRef = useRef<QrUiState>("awaiting_payment");
  const onPaidRef = useRef(onPaid);
  useEffect(() => {
    onPaidRef.current = onPaid;
  }, [onPaid]);

  const activeId = tracked.id;
  const run = tracked.run;

  // --- обратный отсчёт: считаем от срока, а не тикаем счётчик ---------------
  const expiresAt = tracked.invoice?.expires_at ?? null;
  const skewMs = tracked.skewMs;
  useEffect(() => {
    if (!expiresAt) return;
    const tick = () => setLeft(secondsLeftAt(expiresAt, Date.now(), skewMs));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [expiresAt, skewMs]);

  /** Принять ответ сервера: состояние, часы, «оплачено», пора ли остановиться. */
  const accept = useCallback((raw: QrInvoice, receivedAtMs: number) => {
    const invoice = normalizeQrInvoice(raw);
    const skew = clockSkewMs(invoice.server_time, receivedAtMs);
    stateRef.current = invoice.ui_state;
    if (invoice.ui_state === "processing") {
      if (processingSince.current === null) processingSince.current = receivedAtMs;
    } else {
      processingSince.current = null;
    }
    setTracked((prev) => (prev.id === invoice.order_id ? { ...prev, invoice, skewMs: skew } : prev));
    if (!invoice.expires_at) setLeft(invoice.seconds_left);

    if (invoice.ui_state === "paid" && paidNotified.current !== invoice.order_id) {
      paidNotified.current = invoice.order_id;
      try {
        window.dispatchEvent(new CustomEvent("balance:refresh"));
      } catch {
        // не критично: баланс подтянется при следующей загрузке
      }
      onPaidRef.current?.(invoice);
    }

    const stop = shouldStopPolling(
      invoice.ui_state,
      // Срок не пришёл вовсе — «минуты после срока» отсчитывать не от чего.
      invoice.expires_at || invoice.ui_state !== "expired" ? localDeadline(invoice, receivedAtMs) : NaN,
      receivedAtMs,
      processingSince.current ?? undefined
    );
    if (stop) {
      stopped.current = true;
      // «Зачисляем» подсказку не стирает: после перезагрузки человек должен
      // снова увидеть этот экран, а не пустую витрину.
      if (invoice.ui_state !== "processing") clearQrSession(invoice.order_id);
    }
  }, []);

  const poll = useCallback(
    async (id: string) => {
      if (stopped.current) return;
      const request = ++requestId.current;
      setPolling(true);
      const res = await fetchQrInvoice(id);
      if (request !== requestId.current) return; // ответ на устаревший запрос
      setPolling(false);

      if (res.status === 404) {
        stopped.current = true;
        setNotFound(true);
        // Счёта больше нет — баннеру «незавершённая оплата» не за что цепляться.
        clearQrSession(id);
        return;
      }
      if (!res.ok || !isQrInvoice(res.data)) {
        failuresRef.current += 1;
        setFailures(failuresRef.current);
        return;
      }
      failuresRef.current = 0;
      setFailures(0);
      accept(res.data, Date.now());
    },
    [accept]
  );

  // --- сама цепочка опросов -------------------------------------------------
  // Пересобирается только при смене заказа или ручном перезапуске (run):
  // паузу после сбоев расписание берёт из failuresRef на каждом шаге.
  const invoiceRef = useRef<QrInvoice | null>(tracked.invoice);
  useEffect(() => {
    invoiceRef.current = tracked.invoice;
  }, [tracked.invoice]);
  const pollFirst = useRef(false);

  useEffect(() => {
    if (!activeId) return;
    let alive = true;
    stopped.current = false;
    failuresRef.current = 0;
    startedAt.current = Date.now();

    const schedule = () => {
      if (timer.current) clearTimeout(timer.current);
      if (!alive || stopped.current) return;
      const delay = pollDelayMs(Date.now() - startedAt.current, failuresRef.current, stateRef.current);
      timer.current = setTimeout(async () => {
        if (!alive) return;
        if (document.hidden) {
          schedule();
          return;
        }
        await poll(activeId);
        schedule();
      }, delay);
    };

    const known = invoiceRef.current && invoiceRef.current.order_id === activeId ? invoiceRef.current : null;
    if (known) {
      stateRef.current = known.ui_state;
    } else {
      stateRef.current = "awaiting_payment";
      processingSince.current = null;
    }
    // Счёт пришёл вместе с ответом на создание и ждёт оплаты — экран уже всё
    // показывает, первый опрос не нужен. Во всех остальных случаях (возврат к
    // счёту, «уже оплачен», ручная проверка) спрашиваем сервер сразу.
    const immediate = pollFirst.current || !known || known.ui_state !== "awaiting_payment";
    pollFirst.current = false;
    void (async () => {
      if (immediate) await poll(activeId);
      schedule();
    })();

    // Вернулись из приложения банка: спрашиваем сразу, не дожидаясь таймера.
    const onVisible = () => {
      if (!document.hidden && !stopped.current) void poll(activeId);
    };
    // Страницу подняли из памяти кнопкой «назад» — таймеры в ней стояли.
    const onShow = (e: PageTransitionEvent) => {
      if (!e.persisted || stopped.current) return;
      void poll(activeId);
      schedule();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("pageshow", onShow);
    return () => {
      alive = false;
      // Ответ на запрос, начатый этой цепочкой, уже никому не нужен.
      requestId.current += 1;
      if (timer.current) clearTimeout(timer.current);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("pageshow", onShow);
    };
  }, [activeId, run, poll]);

  const refresh = useCallback(() => {
    failuresRef.current = 0;
    setFailures(0);
    pollFirst.current = true;
    // Перезапуск цепочки: она могла уже остановиться (QR истёк, «зачисляем»
    // дольше пяти минут), и одного запроса мало — нужно снова следить.
    setTracked((prev) => (prev.id ? { ...prev, run: prev.run + 1 } : prev));
  }, []);

  const replace = useCallback((next: QrInvoice) => {
    if (!isQrInvoice(next)) return;
    const invoice = normalizeQrInvoice(next);
    const now = Date.now();
    failuresRef.current = 0;
    processingSince.current = null;
    pollFirst.current = false;
    invoiceRef.current = invoice;
    setFailures(0);
    setNotFound(false);
    setPolling(false);
    setLeft(invoice.seconds_left);
    setTracked((prev) => ({
      id: invoice.order_id,
      source: prev.source,
      invoice,
      skewMs: clockSkewMs(invoice.server_time, now),
      run: prev.run + 1,
    }));
  }, []);

  return {
    invoice: tracked.invoice,
    secondsLeft: left,
    polling,
    stale: failures >= 3,
    notFound,
    refresh,
    replace,
  };
}

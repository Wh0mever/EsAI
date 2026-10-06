"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getToken } from "@/tools/fetchData";
import { clearQrSession, readQrSession } from "@/lib/qrSession";
import { clockSkewMs, isQrInvoice, normalizeQrInvoice } from "@/lib/qrpay";
import { fetchQrInvoice } from "@/hooks/useQrInvoice";
import type { QrInvoice } from "@/types/qrpay";

/**
 * «Оплатил в приложении банка и вернулся на перезагруженную страницу».
 *
 * Пока страница жива, возврат ловит опрос в useQrInvoice. Но iOS под
 * нехваткой памяти, встроенные браузеры и человек, открывший сайт заново,
 * дают свежую страницу без окна с QR. Сервер в «незавершённых» знает только
 * НЕоплаченные счета — значит, только что заплативший не увидел бы ничего
 * (или баннер «не завершили оплату» по уже оплаченному заказу). Это и есть
 * момент, когда платят второй раз.
 *
 * Поэтому по номеру заказа из памяти браузера делаем ОДИН запрос статуса и
 * только по ответу сервера решаем, что показать. Из одной лишь подсказки
 * ничего не рисуем: она может быть про давно закрытый счёт.
 *
 * «Ждёт оплаты» в этом первом ответе — ещё не приговор: адрес статуса сам
 * GoPay не спрашивает, а только ставит перепроверку в очередь, так что только
 * что оплаченный счёт первым ответом почти всегда «ждёт». Кто показывает по
 * состоянию banner именно баннер (витрина), обязан следить за счётом дальше —
 * useQrBannerWatch. Кто сразу открывает окно QR (окно пополнения), тому
 * хватает опроса самого окна.
 */
export type QrReturn =
  | { state: "none" }
  /** оплачен или зачисляется — открыть окно QR на этом заказе */
  | { state: "open"; orderId: string }
  /**
   * ещё ждёт оплаты — баннер с НАСТОЯЩИМ сроком счёта; skewMs — насколько часы
   * сервера впереди часов браузера (отсчёт баннера идёт по часам сервера)
   */
  | { state: "banner"; invoice: QrInvoice; skewMs: number };

const NONE: QrReturn = { state: "none" };

// Один раз на загрузку страницы: потребителей хука может быть два (витрина и
// окно пополнения), и оба открыли бы по окну на один и тот же заказ.
let claimed = false;
let pending: Promise<QrReturn> | null = null;

async function resolveReturn(): Promise<QrReturn> {
  const saved = readQrSession();
  if (!saved) return NONE;
  // Гость (вышел из аккаунта, другой браузер после входа): спрашивать не от
  // чьего имени. Подсказку не трогаем — пригодится после входа.
  if (!getToken("access") && !getToken("refresh")) return NONE;

  const res = await fetchQrInvoice(saved.order_id);
  const receivedAt = Date.now();
  if (res.ok && isQrInvoice(res.data)) {
    const invoice = normalizeQrInvoice(res.data);
    if (invoice.ui_state === "paid" || invoice.ui_state === "processing") {
      return { state: "open", orderId: invoice.order_id };
    }
    if (invoice.ui_state === "awaiting_payment") {
      return { state: "banner", invoice, skewMs: clockSkewMs(invoice.server_time, receivedAt) };
    }
    // Истёк, отменён, не прошёл — возвращаться не к чему.
    clearQrSession(saved.order_id);
    return NONE;
  }
  if (res.status === 404 || res.status === 401 || res.status === 403) {
    // Счёта нет или он чужой (в браузере вошли под другим аккаунтом).
    clearQrSession(saved.order_id);
    return NONE;
  }
  // Сеть или сервер: подсказку оставляем до следующей загрузки.
  return NONE;
}

export function useQrReturn(): { ret: QrReturn; dismiss: () => void } {
  const [ret, setRet] = useState<QrReturn>(NONE);
  // Этот экземпляр забрал себе проверку. Ref переживает двойной запуск
  // эффектов в StrictMode — иначе второй запуск остался бы без ответа.
  const owner = useRef(false);
  const dismissed = useRef(false);
  // Заказ, о котором сейчас говорит хук: «скрыть» стирает подсказку именно о
  // нём, а не о новом счёте, созданном уже после возврата.
  const shownOrder = useRef<string | null>(null);

  useEffect(() => {
    if (!claimed) {
      claimed = true;
      owner.current = true;
      pending = resolveReturn().catch(() => NONE);
    }
    if (!owner.current || !pending) return;
    let alive = true;
    void pending.then((value) => {
      // Ответ мог прийти после «скрыть» — тогда он уже ничего не открывает.
      if (!alive || dismissed.current) return;
      shownOrder.current =
        value.state === "open" ? value.orderId : value.state === "banner" ? value.invoice.order_id : null;
      setRet(value);
    });
    return () => {
      alive = false;
    };
  }, []);

  const dismiss = useCallback(() => {
    dismissed.current = true;
    clearQrSession(shownOrder.current || undefined);
    shownOrder.current = null;
    setRet(NONE);
  }, []);

  return { ret, dismiss };
}

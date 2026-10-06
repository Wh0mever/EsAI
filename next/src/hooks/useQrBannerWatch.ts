"use client";

import { useEffect, useRef, useState } from "react";
import { createQrBannerWatch } from "@/lib/qrBannerWatch";
import type { QrBannerSeed } from "@/lib/qrBannerWatch";
import { fetchQrInvoice } from "@/hooks/useQrInvoice";
import type { QrInvoice } from "@/types/qrpay";

/**
 * Баннер «незавершённая оплата по QR» не должен врать оплатившему.
 *
 * Пока баннер на экране (окно QR закрыто), следим за счётом сами: первый ответ
 * статуса обычно устаревший — сервер только ставит перепроверку у GoPay в
 * очередь. Оплачен — onOpen (открыть экран QR: он покажет «Оплачено» и обновит
 * баланс); закрыт без оплаты — onClosed (убрать баннер). Расписание и правила —
 * в lib/qrBannerWatch.ts, здесь только привязка к вкладке.
 *
 * Возвращает последний ответ «ждёт оплаты» по этому заказу: из него баннер
 * берёт настоящий срок и поправку на часы сервера.
 */
type Options = {
  /** уже полученный ответ «ждёт оплаты» по этому же заказу (useQrReturn) */
  seed?: QrBannerSeed | null;
  onOpen: (invoice: QrInvoice) => void;
  onClosed: (orderId: string) => void;
};

export function useQrBannerWatch(orderId: string | null, options: Options): QrBannerSeed | null {
  const [latest, setLatest] = useState<(QrBannerSeed & { id: string }) | null>(null);

  // Свежие обработчики и подсказка без перезапуска слежения на каждый рендер.
  const optionsRef = useRef(options);
  useEffect(() => {
    optionsRef.current = options;
  });

  useEffect(() => {
    if (!orderId) return;
    const watch = createQrBannerWatch(
      orderId,
      {
        fetch: fetchQrInvoice,
        onUpdate: (invoice, skewMs) => setLatest({ id: orderId, invoice, skewMs }),
        onOpen: (invoice) => optionsRef.current.onOpen(invoice),
        onClosed: (id) => optionsRef.current.onClosed(id),
        hidden: () => document.hidden,
      },
      optionsRef.current.seed ?? null
    );
    // Вернулись из приложения банка: спрашиваем сразу, не дожидаясь таймера.
    const onVisible = () => {
      if (!document.hidden) watch.wake();
    };
    // Страницу подняли из памяти кнопкой «назад» — таймеры в ней стояли.
    const onShow = (e: PageTransitionEvent) => {
      if (e.persisted) watch.wake();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("pageshow", onShow);
    return () => {
      watch.stop();
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("pageshow", onShow);
    };
  }, [orderId]);

  return latest && latest.id === orderId ? { invoice: latest.invoice, skewMs: latest.skewMs } : null;
}

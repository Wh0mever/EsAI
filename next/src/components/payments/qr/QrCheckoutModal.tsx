"use client";

import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/dialog/Dialog";
import type { QrInvoice } from "@/types/qrpay";
import QrInvoiceView from "./QrInvoiceView";

/**
 * Окно оплаты по единому QR (GoPay).
 *
 * В отличие от карты, тут нет ухода на страницу банка: счёт создаёт тот, кто
 * нас открыл (ответ POST plans/purchase/ приходит сюда в initial), а окно
 * показывает код, таймер и следит за оплатой. Второй вход — resumeOrderId:
 * баннер «незавершённая оплата», закреплённая скидка или возврат из
 * приложения банка на перезагруженную страницу; тогда известен только номер
 * заказа, остальное спросим у сервера.
 *
 * Модалка на экране одна (две ломают друг другу Escape и блокировку
 * прокрутки) — открывающий прячет свою, как и с окном крипты.
 *
 * Закрытие окна счёт НЕ отменяет: человек мог уже платить в приложении банка.
 */
type Pkg = {
  id: number | string;
  name: string;
  tokens: number;
  bonus_tokens?: number;
};

type Props = {
  open: boolean;
  onClose: () => void;
  /** null в режиме возврата к счёту: пакет тогда известен только серверу */
  pkg?: Pkg | null;
  /** ответ POST plans/purchase/ */
  initial?: QrInvoice | null;
  /** баннер / закреплённая скидка / возврат: известен только номер заказа */
  resumeOrderId?: string | null;
  deviceKey?: string;
  returnTo?: string;
  /** «Создать новый QR-код» повторяет выбор «без скидки» открывшего */
  fullPrice?: boolean;
  onPaid?: (invoice: QrInvoice) => void;
  /** снова открыть выбор способа; нет — действие просто закрывает окно */
  onOtherMethod?: () => void;
};

export default function QrCheckoutModal({
  open,
  onClose,
  pkg = null,
  initial = null,
  resumeOrderId = null,
  deviceKey,
  returnTo,
  fullPrice = false,
  onPaid,
  onOtherMethod,
}: Props) {
  const { t } = useTranslation("qrpay", { useSuspense: false });
  const headingRef = useRef<HTMLHeadingElement>(null);

  // Фокус на заголовок: у Modal нет ловушки фокуса, и без этого клавиатура
  // остаётся на кнопке под модалкой.
  useEffect(() => {
    if (open) headingRef.current?.focus();
  }, [open]);

  const title = t("title", { defaultValue: "Оплата по QR" });
  const orderId = initial?.order_id || resumeOrderId || "";

  return (
    <Modal title={title} open={open} onClose={onClose} size="lg" mobileFull>
      <h3 ref={headingRef} tabIndex={-1} className="sr-only">
        {title}
      </h3>
      {orderId ? (
        // key: другой заказ — другой экран с чистым состоянием (таймеры, ошибки).
        <QrInvoiceView
          key={orderId}
          orderId={orderId}
          initial={initial}
          pkg={pkg}
          deviceKey={deviceKey}
          returnTo={returnTo}
          fullPrice={fullPrice}
          onPaid={onPaid}
          onOtherMethod={onOtherMethod}
          onClose={onClose}
        />
      ) : (
        <div className="flex flex-col items-center gap-4 py-8 text-center">
          <p className="max-w-md text-sm text-muted">
            {t("not_found", { defaultValue: "QR-код не найден — возможно, он уже закрыт. Создайте новый." })}
          </p>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex min-h-[44px] cursor-pointer items-center justify-center rounded-xl border border-border bg-surface-2 px-4 py-2.5 text-sm font-medium text-foreground transition-colors hover:bg-surface-3"
          >
            {t("close", { defaultValue: "Закрыть" })}
          </button>
        </div>
      )}
    </Modal>
  );
}

"use client";

import { useTranslation } from "react-i18next";
import { FiAlertTriangle, FiCheck, FiClock, FiLoader } from "react-icons/fi";
import type { CryptoUiState } from "@/types/crypto";

/**
 * Что сейчас со счётом — одной строкой.
 *
 * aria-live нужен не для красоты: человек может смотреть в кошелёк, а не в
 * браузер, и переход «ждём -> перевод найден» должен быть озвучен.
 */
type Props = {
  state: CryptoUiState;
  confirmations?: number | null;
};

export default function InvoiceStatusPill({ state, confirmations }: Props) {
  const { t } = useTranslation("common");

  const map: Record<CryptoUiState, { text: string; className: string; icon: React.ReactNode }> = {
    awaiting_payment: {
      text: t("crypto.status_waiting", { defaultValue: "Ожидаем перевод" }),
      className: "text-status-wait bg-status-wait/10 border-status-wait/30",
      icon: <span className="h-2 w-2 rounded-full bg-status-wait motion-safe:animate-pulse" />,
    },
    confirming: {
      text: t("crypto.status_confirming", { defaultValue: "Перевод найден, подтверждается" }),
      className: "text-status-progress bg-status-progress/10 border-status-progress/30",
      icon: <FiLoader className="motion-safe:animate-spin" />,
    },
    partially_paid: {
      text: t("crypto.status_partial", { defaultValue: "Получено частично" }),
      className: "text-status-wait bg-status-wait/10 border-status-wait/30",
      icon: <FiAlertTriangle />,
    },
    paid: {
      text: t("crypto.status_paid", { defaultValue: "Оплачено" }),
      className: "text-status-ok bg-status-ok/10 border-status-ok/30",
      icon: <FiCheck />,
    },
    expired: {
      text: t("crypto.status_expired", { defaultValue: "Счёт просрочен" }),
      className: "text-status-fail bg-status-fail/10 border-status-fail/30",
      icon: <FiClock />,
    },
    failed: {
      text: t("crypto.status_failed", { defaultValue: "Платёж не прошёл" }),
      className: "text-status-fail bg-status-fail/10 border-status-fail/30",
      icon: <FiAlertTriangle />,
    },
  };

  const view = map[state] || map.awaiting_payment;
  const extra =
    state === "confirming" && typeof confirmations === "number"
      ? ` · ${t("crypto.confirmations", {
          count: confirmations,
          defaultValue: "подтверждений: {{count}}",
        })}`
      : "";

  return (
    <span
      role="status"
      aria-live="polite"
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium ${view.className}`}
    >
      {view.icon}
      {view.text}
      {extra}
    </span>
  );
}

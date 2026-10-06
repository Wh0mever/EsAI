"use client";

import { useTranslation } from "react-i18next";
import { FiAlertTriangle, FiCheck, FiClock, FiLoader, FiXCircle } from "react-icons/fi";
import type { QrUiState } from "@/types/qrpay";

/**
 * Что сейчас с оплатой по QR — одной строкой.
 *
 * aria-live нужен по делу: человек смотрит в приложение банка, а не в
 * браузер, и переход «ждём → оплата получена» должен быть озвучен.
 */
type Props = {
  state: QrUiState;
};

export default function QrStatusPill({ state }: Props) {
  const { t } = useTranslation("qrpay", { useSuspense: false });

  const map: Record<QrUiState, { text: string; className: string; icon: React.ReactNode }> = {
    awaiting_payment: {
      text: t("status_waiting", { defaultValue: "Ждём оплату" }),
      className: "text-status-wait bg-status-wait/10 border-status-wait/30",
      icon: <span className="h-2 w-2 rounded-full bg-status-wait motion-safe:animate-pulse" />,
    },
    processing: {
      text: t("status_processing", { defaultValue: "Оплата получена, зачисляем" }),
      className: "text-status-progress bg-status-progress/10 border-status-progress/30",
      icon: <FiLoader className="motion-safe:animate-spin" />,
    },
    paid: {
      text: t("status_paid", { defaultValue: "Оплачено" }),
      className: "text-status-ok bg-status-ok/10 border-status-ok/30",
      icon: <FiCheck />,
    },
    expired: {
      text: t("status_expired", { defaultValue: "QR-код истёк" }),
      className: "text-status-fail bg-status-fail/10 border-status-fail/30",
      icon: <FiClock />,
    },
    cancelled: {
      text: t("status_cancelled", { defaultValue: "Оплата отменена" }),
      className: "text-status-fail bg-status-fail/10 border-status-fail/30",
      icon: <FiXCircle />,
    },
    failed: {
      text: t("status_failed", { defaultValue: "Платёж не прошёл" }),
      className: "text-status-fail bg-status-fail/10 border-status-fail/30",
      icon: <FiAlertTriangle />,
    },
  };

  const view = map[state] || map.awaiting_payment;

  return (
    <span
      role="status"
      aria-live="polite"
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium ${view.className}`}
    >
      {view.icon}
      {view.text}
    </span>
  );
}

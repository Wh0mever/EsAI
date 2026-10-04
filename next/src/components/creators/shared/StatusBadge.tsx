"use client";

import { useTranslation } from "react-i18next";
import { statusLabel, type StatusKind } from "@/lib/creators/labels";

type Props = {
  kind: StatusKind;
  /**
   * Статус, как его прислал сервер. Для комиссии сначала уточните через
   * commissionStatusKey: accrued — hold (ещё в холде) или available (уже
   * доступна), reversed — reversed (возврат платежа) или cancelled.
   */
  status: string;
  className?: string;
};

type Tone = "wait" | "ok" | "fail";

/** Цвет по смыслу: ждёт решения, всё хорошо, отказ. */
const TONE: Record<string, Tone> = {
  review: "wait",
  new: "wait",
  held: "wait",
  hold: "wait",
  approved: "ok",
  paid: "ok",
  available: "ok",
  accrued: "ok",
  rejected: "fail",
  blocked: "fail",
  reversed: "fail",
  cancelled: "fail",
  void: "fail",
};

const TONE_CLASS: Record<Tone, string> = {
  wait: "text-status-wait bg-status-wait/10 border-status-wait/30",
  ok: "text-status-ok bg-status-ok/10 border-status-ok/30",
  fail: "text-status-fail bg-status-fail/10 border-status-fail/30",
};

/** Плашка статуса заявки, публикации, вывода или комиссии. */
export default function StatusBadge({ kind, status, className = "" }: Props) {
  const { t } = useTranslation("creators", { useSuspense: false });
  const tone = TONE[status];

  return (
    <span
      className={`inline-flex max-w-full items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${
        tone ? TONE_CLASS[tone] : "border-border bg-surface-2 text-muted"
      } ${className}`}
    >
      {statusLabel(t, kind, status)}
    </span>
  );
}

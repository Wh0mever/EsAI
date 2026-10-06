"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { IoQrCodeOutline } from "react-icons/io5";
import { formatCountdown } from "@/lib/cryptoUri";
import { secondsLeft } from "@/lib/qrpay";

/**
 * «У вас есть незавершённая оплата по QR».
 *
 * Тот же вывод из разбора воронки, что и у карты с криптой: человек закрыл
 * окно, вернулся — а продолжить нечем, и он начинает заново. Здесь это ещё и
 * лишний открытый QR у банка.
 *
 * Срок — всегда настоящий, с сервера, и отсчёт идёт по часам СЕРВЕРА (как в
 * окне QR): на телефоне со сбитым временем баннер иначе пропадал бы при живом
 * коде или звал бы к уже истёкшему. Когда срок вышел, баннер исчезает сам:
 * звать человека к мёртвому коду незачем.
 */
type Props = {
  packageName: string;
  /** «392 сом» */
  amountLabel: string;
  expiresAt: string | null;
  /**
   * Насколько часы сервера впереди часов браузера (мс) — clockSkewMs от
   * server_time ответа, из которого взят срок. 0 — часы сервера неизвестны.
   */
  skewMs?: number;
  onOpen: () => void;
  onDismiss: () => void;
};

export default function QrPendingBanner({
  packageName,
  amountLabel,
  expiresAt,
  skewMs = 0,
  onOpen,
  onDismiss,
}: Props) {
  const { t } = useTranslation("qrpay", { useSuspense: false });
  const [left, setLeft] = useState<number | null>(null);

  useEffect(() => {
    if (!expiresAt || !Number.isFinite(Date.parse(expiresAt))) return;
    const tick = () => setLeft(secondsLeft(expiresAt, Date.now(), skewMs));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [expiresAt, skewMs]);

  if (left !== null && left <= 0) return null;

  const what = [packageName, amountLabel].filter(Boolean).join(" — ");

  return (
    <div className="mx-auto mb-6 flex max-w-2xl flex-col gap-3 rounded-2xl border border-accent/50 bg-accent/5 p-4 sm:flex-row sm:items-center">
      <span
        aria-hidden="true"
        className="hidden h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent/15 text-accent sm:inline-flex"
      >
        <IoQrCodeOutline className="h-5 w-5" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-foreground">
          {t("pending_title", { defaultValue: "У вас есть незавершённая оплата по QR" })}
        </p>
        <p className="mt-0.5 text-sm text-muted">
          {what}
          {left !== null && left > 0
            ? `${what ? " · " : ""}${t("pending_left", {
                time: formatCountdown(left),
                defaultValue: "осталось {{time}}",
              })}`
            : ""}
        </p>
      </div>
      <button
        type="button"
        onClick={onOpen}
        className="inline-flex shrink-0 cursor-pointer items-center justify-center rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-on-accent transition-colors hover:bg-accent-strong"
      >
        {t("pending_open", { defaultValue: "Открыть QR-код" })}
      </button>
      <button
        type="button"
        onClick={onDismiss}
        className="shrink-0 cursor-pointer text-sm text-muted transition-colors hover:text-foreground"
      >
        {t("pending_dismiss", { defaultValue: "Скрыть" })}
      </button>
    </div>
  );
}

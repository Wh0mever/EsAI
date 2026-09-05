"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { displayCoin, formatCountdown } from "@/lib/cryptoUri";
import CoinIcon from "./CoinIcon";

/**
 * «У вас есть незавершённая криптооплата».
 *
 * Тот же разбор воронки, что и у карточной оплаты: человек закрыл вкладку и
 * вернулся, а продолжить нечем. С криптой это ещё важнее — деньги он мог уже
 * отправить, и новый счёт с новым адресом ему не нужен.
 */
type Props = {
  packageName: string;
  coin?: string;
  network?: string;
  payAmount?: string;
  expiresAt?: string | null;
  onOpen: () => void;
  onDismiss: () => void;
};

export default function CryptoPendingBanner({
  packageName,
  coin,
  network,
  payAmount,
  expiresAt,
  onOpen,
  onDismiss,
}: Props) {
  const { t } = useTranslation("common");
  const [left, setLeft] = useState<number | null>(null);

  useEffect(() => {
    if (!expiresAt) return;
    const deadline = new Date(expiresAt).getTime();
    const tick = () => setLeft(Math.max(0, Math.round((deadline - Date.now()) / 1000)));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [expiresAt]);

  return (
    <div className="mx-auto mb-6 flex max-w-2xl flex-col gap-3 rounded-2xl border border-accent/50 bg-accent/5 p-4 sm:flex-row sm:items-center">
      {coin && <CoinIcon coin={coin} size={36} className="hidden sm:inline-flex" />}
      <div className="flex-1">
        <p className="text-sm font-semibold text-foreground">
          {t("crypto.pending_title", { defaultValue: "У вас есть незавершённая криптооплата" })}
        </p>
        <p className="mt-0.5 text-sm text-muted">
          {packageName}
          {payAmount && coin ? ` — ${payAmount} ${displayCoin(coin)}` : ""}
          {network ? ` (${network})` : ""}
          {left !== null && left > 0
            ? ` · ${t("crypto.pending_left", {
                time: formatCountdown(left),
                defaultValue: "осталось {{time}}",
              })}`
            : ""}
        </p>
      </div>
      <button
        type="button"
        onClick={onOpen}
        className="inline-flex shrink-0 items-center justify-center rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-on-accent transition-colors hover:bg-accent-strong cursor-pointer"
      >
        {t("crypto.pending_open", { defaultValue: "Открыть счёт" })}
      </button>
      <button
        type="button"
        onClick={onDismiss}
        className="shrink-0 text-sm text-muted transition-colors hover:text-foreground cursor-pointer"
      >
        {t("packages.pending_dismiss", { defaultValue: "Скрыть" })}
      </button>
    </div>
  );
}

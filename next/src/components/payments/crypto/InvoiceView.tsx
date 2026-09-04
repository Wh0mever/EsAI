"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiCheckCircle, FiExternalLink, FiLoader, FiRefreshCw } from "react-icons/fi";
import CopyField from "@/components/ui/CopyField";
import QrCode from "@/components/ui/QrCode";
import { buildWalletUri, formatCountdown } from "@/lib/cryptoUri";
import { useCryptoInvoice } from "@/hooks/useCryptoInvoice";
import CoinIcon from "./CoinIcon";
import InvoiceStatusPill from "./InvoiceStatusPill";
import type { CryptoInvoice } from "@/types/crypto";

/**
 * Экран оплаты: адрес, точная сумма, QR и таймер.
 *
 * Кнопки «Я оплатил» здесь нет намеренно. Она ничего не решает (сеть всё
 * равно подтвердит перевод сама), зато создаёт ложное чувство, будто без
 * нажатия деньги не зачтут, — и человек, закрывший вкладку, начинает
 * волноваться. Вместо неё сказано прямым текстом: окно можно закрыть.
 */
type Props = {
  orderId: string;
  initial?: CryptoInvoice | null;
  returnTo?: string;
  onPaid?: () => void;
  onNewInvoice?: () => void;
  onClose: () => void;
};

export default function InvoiceView({
  orderId,
  initial = null,
  returnTo,
  onPaid,
  onNewInvoice,
  onClose,
}: Props) {
  const { t } = useTranslation("common");
  const { invoice, secondsLeft, polling, stale, notFound, refresh } = useCryptoInvoice(orderId, {
    initial,
    onPaid: () => onPaid?.(),
  });
  const [redirectIn, setRedirectIn] = useState<number | null>(null);

  const state = notFound ? "failed" : invoice?.ui_state || "awaiting_payment";
  const partial = state === "partially_paid";

  // Что кодируем в QR: остаток, если часть денег уже пришла, — иначе человек
  // отправит полную сумму второй раз.
  const wallet = useMemo(() => {
    if (!invoice) return { uri: "", deepLink: false };
    return buildWalletUri({
      payCurrency: invoice.pay.currency,
      coin: invoice.pay.coin,
      network: invoice.pay.network,
      address: invoice.pay.address,
      amount: partial ? invoice.pay.amount_remaining : invoice.pay.amount,
      memo: invoice.pay.extra_id,
    });
  }, [invoice, partial]);

  // Возврат в студию после оплаты: человек пришёл платить из недоделанного
  // мультфильма и должен вернуться к нему, а не остаться на экране оплаты.
  useEffect(() => {
    if (state !== "paid" || !returnTo) return;
    setRedirectIn(3);
    const id = setInterval(() => {
      setRedirectIn((n) => {
        if (n === null) return null;
        if (n <= 1) {
          clearInterval(id);
          window.location.assign(returnTo);
          return 0;
        }
        return n - 1;
      });
    }, 1000);
    return () => clearInterval(id);
  }, [state, returnTo]);

  if (!invoice) {
    return (
      <div className="flex flex-col items-center gap-3 py-10 text-muted">
        <FiLoader className="animate-spin text-2xl" />
        {t("crypto.creating", { defaultValue: "Создаём счёт…" })}
      </div>
    );
  }

  // --- оплачено ------------------------------------------------------------
  if (state === "paid") {
    return (
      <div className="flex flex-col items-center gap-4 py-8 text-center">
        <FiCheckCircle className="text-5xl text-status-ok motion-safe:animate-[pop_.3s_ease-out]" />
        <div className="text-xl font-semibold text-foreground">
          {t("crypto.paid_title", { defaultValue: "Оплата получена" })}
        </div>
        <div className="text-sm text-muted">
          {/* count оставляем для выбора формы слова, показываем credits:
              «22000 кредитов» читается хуже, чем «22 000 кредитов». */}
          {t("crypto.credits_added", {
            count: invoice.credits.credited,
            credits: invoice.credits.credited.toLocaleString("ru-RU"),
            defaultValue: "Зачислено {{credits}} кредитов",
          })}
        </div>
        {invoice.explorer_url && (
          <a
            href={invoice.explorer_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-xs text-muted transition-colors hover:text-foreground"
          >
            <FiExternalLink /> {t("crypto.tx_link", { defaultValue: "Транзакция в обозревателе" })}
          </a>
        )}
        <button
          type="button"
          onClick={() => (returnTo ? window.location.assign(returnTo) : onClose())}
          className="mt-2 inline-flex items-center justify-center rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-on-accent transition-colors hover:bg-accent-strong cursor-pointer"
        >
          {returnTo
            ? t("crypto.back_to_project", { defaultValue: "Вернуться к работе" })
            : t("crypto.done", { defaultValue: "Готово" })}
        </button>
        {returnTo && redirectIn !== null && (
          <div className="text-xs text-muted-2">
            {t("crypto.redirecting", {
              seconds: redirectIn,
              defaultValue: "Возвращаемся через {{seconds}} с…",
            })}
          </div>
        )}
      </div>
    );
  }

  // --- счёт закрыт ---------------------------------------------------------
  if (state === "expired" || state === "failed") {
    return (
      <div className="flex flex-col items-center gap-4 py-8 text-center">
        <InvoiceStatusPill state={state} />
        <p className="max-w-md text-sm text-muted">
          {state === "expired"
            ? t("crypto.expired_note", {
                defaultValue:
                  "Курс держится только на время действия счёта. Если вы уже отправили перевод — он будет зачислен после подтверждения сети, даже сейчас.",
              })
            : t("crypto.failed_note", {
                defaultValue: "Платёж не прошёл. Создайте новый счёт или выберите другой способ оплаты.",
              })}
        </p>
        <div className="flex flex-wrap justify-center gap-2">
          {onNewInvoice && (
            <button
              type="button"
              onClick={onNewInvoice}
              className="rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-on-accent transition-colors hover:bg-accent-strong cursor-pointer"
            >
              {t("crypto.new_invoice", { defaultValue: "Создать новый счёт" })}
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-border px-5 py-2.5 text-sm text-muted transition-colors hover:text-foreground cursor-pointer"
          >
            {t("crypto.close", { defaultValue: "Закрыть" })}
          </button>
        </div>
      </div>
    );
  }

  // --- ждём перевод --------------------------------------------------------
  const amountToSend = partial ? invoice.pay.amount_remaining : invoice.pay.amount;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <InvoiceStatusPill state={state} confirmations={invoice.confirmations} />
        <div className="text-right">
          <div className="text-2xl font-semibold tabular-nums text-foreground">
            {secondsLeft > 0 ? formatCountdown(secondsLeft) : "—"}
          </div>
          <div className="text-[11px] text-muted-2">
            {secondsLeft > 0
              ? t("crypto.time_left_hint", { defaultValue: "столько держится курс" })
              : t("crypto.time_over", { defaultValue: "время истекло" })}
          </div>
        </div>
      </div>

      {partial && (
        <div className="rounded-xl border border-status-wait/40 bg-status-wait/10 px-3 py-2.5 text-sm text-foreground">
          {t("crypto.partial_paid", {
            paid: invoice.pay.amount_paid,
            total: invoice.pay.amount,
            coin: invoice.pay.coin,
            defaultValue: "Получено {{paid}} из {{total}} {{coin}}",
          })}
          {invoice.credits.credited > 0 && (
            <div className="mt-1 text-xs text-muted">
              {t("crypto.partial_credits", {
                credited: invoice.credits.credited.toLocaleString("ru-RU"),
                total: invoice.credits.total.toLocaleString("ru-RU"),
                defaultValue: "Зачислено {{credited}} из {{total}} кредитов",
              })}
            </div>
          )}
        </div>
      )}

      <div className="grid gap-5 md:grid-cols-[auto_minmax(0,1fr)]">
        <div className="flex flex-col items-center gap-2">
          <QrCode
            value={wallet.uri || invoice.pay.address}
            label={t("crypto.qr_label", {
              coin: invoice.pay.coin,
              defaultValue: "QR-код для оплаты {{coin}}",
            })}
          />
          {wallet.deepLink && (
            <a
              href={wallet.uri}
              className="inline-flex w-full items-center justify-center rounded-xl border border-border px-4 py-2 text-sm text-foreground transition-colors hover:border-accent cursor-pointer"
            >
              {t("crypto.open_wallet", { defaultValue: "Открыть в кошельке" })}
            </a>
          )}
        </div>

        <div className="flex min-w-0 flex-col gap-3">
          <CopyField
            label={
              partial
                ? t("crypto.amount_remaining_title", { defaultValue: "Доплатить" })
                : t("crypto.amount_title", { defaultValue: "Сумма к переводу" })
            }
            value={amountToSend}
            size="lg"
            display={
              <span className="inline-flex items-baseline gap-2">
                {amountToSend}
                <span className="text-base font-normal text-muted">{invoice.pay.coin}</span>
              </span>
            }
          />
          <div className="rounded-xl border border-status-wait/30 bg-status-wait/10 px-3 py-2 text-xs text-foreground">
            {t("crypto.amount_exact", {
              defaultValue:
                "Отправьте ровно эту сумму. Комиссию сети платит отправитель — если её вычесть из перевода, оплата зачтётся как частичная.",
            })}
          </div>

          <CopyField
            label={t("crypto.address_title", {
              network: invoice.pay.network,
              defaultValue: "Адрес для перевода ({{network}})",
            })}
            value={invoice.pay.address}
          />

          {invoice.pay.extra_id && (
            <CopyField
              label={t("crypto.memo_title", { defaultValue: "Memo / Tag — обязательно" })}
              value={invoice.pay.extra_id}
              tone="warning"
            />
          )}
          {invoice.pay.extra_id && (
            <div className="text-xs text-status-wait">
              {t("crypto.memo_warning", {
                defaultValue:
                  "Без memo перевод потеряется. Укажите его в поле «Комментарий / Memo» вашего кошелька.",
              })}
            </div>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">
        <div className="flex items-center gap-2 text-xs text-muted">
          <CoinIcon coin={invoice.pay.coin} size={22} />
          <span>
            {invoice.pay.label} · {invoice.credits.total.toLocaleString("ru-RU")}{" "}
            {t("topup.credits", { defaultValue: "кредитов" })} · ${invoice.price.usd}
          </span>
        </div>
        <button
          type="button"
          onClick={refresh}
          disabled={polling}
          className="inline-flex items-center gap-1.5 text-xs text-muted transition-colors hover:text-foreground disabled:opacity-60 cursor-pointer"
        >
          <FiRefreshCw className={polling ? "animate-spin" : ""} />
          {polling
            ? t("crypto.checking", { defaultValue: "Проверяем…" })
            : t("crypto.check_now", { defaultValue: "Проверить сейчас" })}
        </button>
      </div>

      <p className="text-xs text-muted-2">
        {stale
          ? t("crypto.connection_retry", { defaultValue: "Нет связи с сервером, повторяем…" })
          : t("crypto.auto_detect_note", {
              defaultValue:
                "Зачисление автоматическое: как только сеть подтвердит перевод, кредиты появятся на балансе. Окно можно закрыть — счёт сохранится.",
            })}
      </p>

      {invoice.explorer_url && (
        <a
          href={invoice.explorer_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 text-xs text-muted transition-colors hover:text-foreground"
        >
          <FiExternalLink /> {t("crypto.tx_link", { defaultValue: "Транзакция в обозревателе" })}
        </a>
      )}
    </div>
  );
}

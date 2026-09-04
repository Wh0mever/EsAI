"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiArrowLeft, FiGift, FiLoader } from "react-icons/fi";
import { Modal } from "@/components/dialog/Dialog";
import { fetchData } from "@/tools/fetchData";
import { trackFunnel } from "@/tools/funnel";
import { saveCryptoSession } from "@/lib/cryptoSession";
import type { CryptoCurrency, CryptoInvoice, CryptoPurchaseError } from "@/types/crypto";
import CoinPicker from "./CoinPicker";
import InvoiceView from "./InvoiceView";

/**
 * Оплата криптовалютой: выбор монеты -> счёт.
 *
 * Модалка здесь ровно одна. Две открытые одновременно ломают друг другу
 * Escape и блокировку прокрутки (обе вешают свои обработчики), поэтому тот,
 * кто нас открывает, обязан спрятать свою — см. TopUpModal.
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
  /** цена в валюте витрины — «1 900 сом» / «$21.66» */
  priceLabel?: string;
  currencies: CryptoCurrency[];
  /** открыть сразу счёт (незавершённая оплата) */
  resumeOrderId?: string | null;
  deviceKey?: string;
  returnTo?: string;
  onPaid?: () => void;
};

type Stage =
  | { name: "pick" }
  | { name: "creating" }
  | { name: "invoice"; orderId: string; initial: CryptoInvoice | null }
  | { name: "error"; kind: "min_amount" | "unsupported" | "auth" | "generic"; text: string };

export default function CryptoCheckoutModal({
  open,
  onClose,
  pkg = null,
  priceLabel,
  currencies,
  resumeOrderId = null,
  deviceKey,
  returnTo,
  onPaid,
}: Props) {
  const { t } = useTranslation("common");
  const [stage, setStage] = useState<Stage>(
    resumeOrderId ? { name: "invoice", orderId: resumeOrderId, initial: null } : { name: "pick" }
  );
  const [code, setCode] = useState<string | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  // Первой предлагаем ту монету, которой платят чаще всего (её процессор
  // отдаёт первой в списке популярных) — но выбор всегда за человеком.
  const defaultCode = useMemo(
    () => currencies.find((c) => c.popular)?.code || currencies[0]?.code || null,
    [currencies]
  );

  useEffect(() => {
    if (!open) return;
    setStage(resumeOrderId ? { name: "invoice", orderId: resumeOrderId, initial: null } : { name: "pick" });
    setCode(null);
  }, [open, resumeOrderId]);

  // Фокус на заголовок шага: у Modal нет ловушки фокуса, и без этого
  // клавиатура остаётся на кнопке под модалкой.
  useEffect(() => {
    headingRef.current?.focus();
  }, [stage.name]);

  const selected = currencies.find((c) => c.code === code) || null;

  const createInvoice = async (currencyCode: string) => {
    if (!pkg) return;
    setStage({ name: "creating" });
    trackFunnel("crypto_currency_pick", { package_id: pkg.id, pay_currency: currencyCode });

    const res = await fetchData<CryptoInvoice & CryptoPurchaseError>(
      "plans/purchase/",
      "POST",
      {
        package_id: pkg.id,
        pay_currency: "USD",
        crypto_currency: currencyCode,
        ...(returnTo ? { return_to: returnTo } : {}),
      },
      true,
      deviceKey ? { "X-Device-Key": deviceKey } : undefined
    );

    if (res.ok && res.data && res.data.order_id) {
      const invoice = res.data as CryptoInvoice;
      saveCryptoSession({
        order_id: invoice.order_id,
        package_name: pkg.name,
        coin: invoice.pay.coin,
        network: invoice.pay.network,
      });
      trackFunnel("crypto_invoice_created", {
        package_id: pkg.id,
        pay_currency: currencyCode,
        price_usd: invoice.price.usd,
      });
      setStage({ name: "invoice", orderId: invoice.order_id, initial: invoice });
      return;
    }

    const data = (res.data || {}) as CryptoPurchaseError;
    if (res.status === 401) {
      setStage({
        name: "error",
        kind: "auth",
        text: t("crypto.err_unauthorized", {
          defaultValue: "Сессия истекла. Войдите снова, чтобы продолжить.",
        }),
      });
      return;
    }
    if (data.detail === "crypto_amount_below_min") {
      setStage({
        name: "error",
        kind: "min_amount",
        text: t("crypto.err_min_amount", {
          coin: selected?.coin || currencyCode.toUpperCase(),
          min: data.min_usd || "",
          defaultValue:
            "Минимальная сумма для {{coin}} — ${{min}}. Выберите пакет побольше или другую сеть.",
        }),
      });
      return;
    }
    if (data.detail === "crypto_currency_not_supported" || data.detail === "crypto_disabled") {
      setStage({
        name: "error",
        kind: "unsupported",
        text: t("crypto.err_unsupported", {
          defaultValue: "Эта монета временно недоступна. Выберите другую.",
        }),
      });
      return;
    }
    setStage({
      name: "error",
      kind: "generic",
      text: t("crypto.err_generic", { defaultValue: "Не удалось создать счёт. Попробуйте ещё раз." }),
    });
  };

  const title =
    stage.name === "invoice"
      ? t("crypto.title_invoice", { defaultValue: "Оплата криптовалютой" })
      : t("crypto.title_pick", { defaultValue: "Выберите монету" });

  const bonus = Number(pkg?.bonus_tokens || 0);

  return (
    <Modal title={title} open={open} onClose={onClose} size="lg">
      <div className="flex flex-col gap-4 p-1 sm:p-2">
        <h3 ref={headingRef} tabIndex={-1} className="sr-only">
          {title}
        </h3>

        {stage.name === "pick" && (
          <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_280px]">
            <CoinPicker
              currencies={currencies}
              value={code ?? defaultCode}
              onChange={setCode}
            />

            <div className="flex flex-col gap-3 rounded-2xl border border-border bg-surface-2 p-4 md:sticky md:top-0 md:self-start">
              {pkg && (
                <>
                  <div className="text-sm font-semibold text-foreground">{pkg.name}</div>
                  <div className="flex items-baseline gap-1.5 text-sm text-muted">
                    <span className="text-lg font-bold text-foreground">
                      {pkg.tokens.toLocaleString()}
                    </span>
                    {t("topup.credits", { defaultValue: "кредитов" })}
                  </div>
                  {bonus > 0 && (
                    <div className="inline-flex items-center gap-1 text-xs text-accent">
                      <FiGift /> +{bonus.toLocaleString()} {t("topup.bonus", { defaultValue: "бонус" })}
                    </div>
                  )}
                </>
              )}
              {priceLabel && (
                <div className="text-xl font-bold text-foreground">{priceLabel}</div>
              )}
              <p className="text-xs text-muted-2">
                {t("crypto.price_usd_note", {
                  defaultValue:
                    "Точная сумма в монете зафиксируется при создании счёта и не изменится, пока он действует.",
                })}
              </p>
              <button
                type="button"
                disabled={!(code ?? defaultCode)}
                onClick={() => void createInvoice((code ?? defaultCode) as string)}
                className="mt-1 inline-flex items-center justify-center rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-on-accent transition-colors hover:bg-accent-strong disabled:opacity-60 disabled:cursor-not-allowed cursor-pointer"
              >
                {t("crypto.create_invoice", { defaultValue: "Перейти к оплате" })}
              </button>
            </div>
          </div>
        )}

        {stage.name === "creating" && (
          <div className="flex flex-col items-center gap-3 py-14 text-muted">
            <FiLoader className="animate-spin text-2xl" />
            {t("crypto.creating", { defaultValue: "Создаём счёт…" })}
          </div>
        )}

        {stage.name === "invoice" && (
          <InvoiceView
            orderId={stage.orderId}
            initial={stage.initial}
            returnTo={returnTo}
            onPaid={onPaid}
            onNewInvoice={pkg ? () => setStage({ name: "pick" }) : undefined}
            onClose={onClose}
          />
        )}

        {stage.name === "error" && (
          <div className="flex flex-col items-center gap-4 py-10 text-center">
            <p className="max-w-md text-sm text-status-fail">{stage.text}</p>
            <div className="flex flex-wrap justify-center gap-2">
              {stage.kind === "auth" ? (
                <a
                  href={`/auth/signin?next=${encodeURIComponent(returnTo || "/pricing")}`}
                  className="rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-on-accent transition-colors hover:bg-accent-strong"
                >
                  {t("crypto.sign_in", { defaultValue: "Войти" })}
                </a>
              ) : (
                <button
                  type="button"
                  onClick={() => setStage({ name: "pick" })}
                  className="rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-on-accent transition-colors hover:bg-accent-strong cursor-pointer"
                >
                  {t("crypto.change_coin", { defaultValue: "Выбрать другую монету" })}
                </button>
              )}
              <button
                type="button"
                onClick={onClose}
                className="rounded-xl border border-border px-5 py-2.5 text-sm text-muted transition-colors hover:text-foreground cursor-pointer"
              >
                {t("crypto.other_package", { defaultValue: "Другой пакет" })}
              </button>
            </div>
          </div>
        )}

        {stage.name === "invoice" && pkg && (
          <button
            type="button"
            onClick={() => setStage({ name: "pick" })}
            className="inline-flex items-center gap-1.5 self-start text-xs text-muted transition-colors hover:text-foreground cursor-pointer"
          >
            <FiArrowLeft /> {t("crypto.back_to_coins", { defaultValue: "Выбрать другую монету" })}
          </button>
        )}
      </div>
    </Modal>
  );
}

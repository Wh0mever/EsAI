"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiCreditCard, FiGift, FiShield } from "react-icons/fi";
import { Modal } from "@/components/dialog/Dialog";
import { fetchData } from "@/tools/fetchData";
import { trackFunnel } from "@/tools/funnel";
import { saveCryptoSession } from "@/lib/cryptoSession";
import { useCryptoCurrencies } from "@/hooks/useCryptoCurrencies";
import type { CryptoCurrency, CryptoInvoice, CryptoPurchaseError } from "@/types/crypto";
import CoinIcon from "./CoinIcon";
import CoinPicker from "./CoinPicker";
import InvoiceView from "./InvoiceView";

/**
 * Окно пополнения: слева — что покупаем и чем платим, справа — монеты, а
 * после клика по монете — адрес, сумма и QR.
 *
 * Устройство подсмотрено у площадок, где криптой платят каждый день: человек
 * не должен листать шаги, всё в одном окне. Способы оплаты картой стоят в той
 * же левой колонке — переключиться на карту можно, не закрывая окно.
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

type CardCurrency = "KGS" | "RUB";

type Props = {
  open: boolean;
  onClose: () => void;
  /** null в режиме возврата к счёту: пакет тогда известен только серверу */
  pkg?: Pkg | null;
  /** цена пакета в сомах — базовая валюта всех пакетов (API отдаёт строкой) */
  priceKgs?: number | string;
  /** цена в валюте витрины — «1 900 сом» / «$21.66» (подпись под долларами) */
  priceLabel?: string;
  currencies: CryptoCurrency[];
  /** открыть сразу счёт (незавершённая оплата) */
  resumeOrderId?: string | null;
  deviceKey?: string;
  returnTo?: string;
  onPaid?: () => void;
  /** переключение на карту прямо из окна; нет — строки карт не показываем */
  onCardPurchase?: (currency: CardCurrency) => void;
};

type Stage =
  | { name: "pick" }
  | { name: "invoice"; orderId: string; initial: CryptoInvoice | null };

type PickError = { kind: "auth" | "generic"; text: string } | null;

export default function CryptoCheckoutModal({
  open,
  onClose,
  pkg = null,
  priceKgs,
  priceLabel,
  currencies,
  resumeOrderId = null,
  deviceKey,
  returnTo,
  onPaid,
  onCardPurchase,
}: Props) {
  const { t } = useTranslation("common");
  // Курс и флаг комиссии приходят вместе со списком монет — из кэша, без
  // второго запроса.
  const { rateKgsToUsd, feePaidByUser } = useCryptoCurrencies();
  const [stage, setStage] = useState<Stage>(
    resumeOrderId ? { name: "invoice", orderId: resumeOrderId, initial: null } : { name: "pick" }
  );
  const [busyCode, setBusyCode] = useState<string | null>(null);
  const [pickError, setPickError] = useState<PickError>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (!open) return;
    setStage(resumeOrderId ? { name: "invoice", orderId: resumeOrderId, initial: null } : { name: "pick" });
    setBusyCode(null);
    setPickError(null);
  }, [open, resumeOrderId]);

  // Фокус на заголовок шага: у Modal нет ловушки фокуса, и без этого
  // клавиатура остаётся на кнопке под модалкой.
  useEffect(() => {
    headingRef.current?.focus();
  }, [stage.name]);

  // Цена приходит из API строкой («190.00») — считаем через Number, иначе
  // плитки с минимумом выше цены никогда не погаснут.
  const kgs = priceKgs === undefined || priceKgs === null ? NaN : Number(priceKgs);
  const priceUsd =
    Number.isFinite(kgs) && rateKgsToUsd ? Math.round(kgs * rateKgsToUsd * 100) / 100 : null;

  const createInvoice = async (currencyCode: string) => {
    if (!pkg || busyCode) return;
    setBusyCode(currencyCode);
    setPickError(null);
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
    setBusyCode(null);

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
    const coin = currencies.find((c) => c.code === currencyCode);
    if (res.status === 401) {
      setPickError({
        kind: "auth",
        text: t("crypto.err_unauthorized", {
          defaultValue: "Сессия истекла. Войдите снова, чтобы продолжить.",
        }),
      });
      return;
    }
    if (data.detail === "crypto_amount_below_min") {
      const coinName = coin?.coin || currencyCode.toUpperCase();
      setPickError({
        kind: "generic",
        // Процессор может отказать «мало», не назвав порог, — тогда без «$».
        text: data.min_usd
          ? t("crypto.err_min_amount", {
              coin: coinName,
              min: data.min_usd,
              defaultValue:
                "Минимальная сумма для {{coin}} — ${{min}}. Выберите пакет побольше или другую сеть.",
            })
          : t("crypto.err_min_amount_unknown", {
              coin: coinName,
              defaultValue:
                "Для {{coin}} эта сумма слишком мала у процессора. Выберите другую сеть или пакет побольше.",
            }),
      });
      return;
    }
    if (data.detail === "crypto_too_often") {
      setPickError({
        kind: "generic",
        text: t("crypto.err_too_often", {
          defaultValue: "Слишком много попыток — подождите минуту и попробуйте снова.",
        }),
      });
      return;
    }
    if (data.detail === "crypto_too_many_open_invoices") {
      setPickError({
        kind: "generic",
        text: t("crypto.err_too_many", {
          defaultValue:
            "У вас уже несколько открытых счетов. Оплатите один из них или подождите, пока они истекут.",
        }),
      });
      return;
    }
    if (data.detail === "crypto_currency_not_supported" || data.detail === "crypto_disabled") {
      setPickError({
        kind: "generic",
        text: t("crypto.err_unsupported", {
          defaultValue: "Эта монета временно недоступна. Выберите другую.",
        }),
      });
      return;
    }
    setPickError({
      kind: "generic",
      text: t("crypto.err_generic", { defaultValue: "Не удалось создать счёт. Попробуйте ещё раз." }),
    });
  };

  const title = t("crypto.title", { defaultValue: "Пополнение баланса" });
  const bonus = Number(pkg?.bonus_tokens || 0);
  const cryptoCount = currencies.length;

  const methodRow = (
    key: string,
    icon: React.ReactNode,
    label: string,
    hint: string,
    active: boolean,
    onClick?: () => void
  ) => (
    <button
      key={key}
      type="button"
      onClick={onClick}
      disabled={active || !onClick}
      aria-pressed={active}
      className={`flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors ${
        active
          ? "border-accent bg-accent-soft"
          : "cursor-pointer border-border bg-surface hover:border-accent/60"
      }`}
    >
      <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface-3 text-foreground">
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-foreground">{label}</span>
        <span className="block truncate text-[11px] text-muted">{hint}</span>
      </span>
    </button>
  );

  return (
    <Modal title={title} open={open} onClose={onClose} size="lg" mobileFull>
      <div className="grid gap-4 md:grid-cols-[236px_minmax(0,1fr)]">
        <h3 ref={headingRef} tabIndex={-1} className="sr-only">
          {stage.name === "invoice"
            ? t("crypto.title_invoice", { defaultValue: "Оплата криптовалютой" })
            : t("crypto.pick_title", { defaultValue: "Выберите монету для оплаты" })}
        </h3>

        {/* ------------------------------------------ телефон: сжатая шапка */}
        {/* На узком экране боковая колонка целиком заняла бы первый экран, и
            адрес оказался бы под сгибом. Поэтому тут одна строка про пакет и
            способы оплаты фишками — суть та же, места втрое меньше. */}
        <div className="flex flex-col gap-2 md:hidden">
          {pkg && (
            <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-surface-2 px-3 py-2">
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-foreground">{pkg.name}</div>
                <div className="text-[11px] text-muted">
                  {pkg.tokens.toLocaleString("ru-RU")} {t("topup.credits", { defaultValue: "кредитов" })}
                  {bonus > 0 ? ` +${bonus.toLocaleString("ru-RU")}` : ""}
                </div>
              </div>
              <div className="text-right">
                <div className="text-lg font-bold tabular-nums text-foreground">
                  {priceUsd !== null ? `$${priceUsd.toFixed(2)}` : priceLabel || ""}
                </div>
                {priceUsd !== null && Number.isFinite(kgs) && (
                  <div className="text-[10px] text-muted-2">
                    {kgs.toLocaleString("ru-RU")} {t("topup.som", { defaultValue: "сом" })}
                  </div>
                )}
              </div>
            </div>
          )}
          {stage.name === "pick" && onCardPurchase && (
            <div className="flex gap-2 overflow-x-auto pb-0.5">
              {/* Активный способ — первым: строка прокручивается, и то, что
                  выбрано сейчас, не должно прятаться за краем экрана. */}
              <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-accent bg-accent-soft px-3 py-1 text-xs font-medium text-foreground">
                <CoinIcon coin="USDT" size={14} />
                {t("crypto.method_crypto", { defaultValue: "Криптовалюта" })}
              </span>
              {(
                [
                  ["KGS", t("crypto.method_card_kgs", { defaultValue: "Карта · сом" })],
                  ["RUB", t("crypto.method_card_rub", { defaultValue: "Карта · рубли" })],
                ] as [CardCurrency, string][]
              ).map(([cur, label]) => (
                <button
                  key={cur}
                  type="button"
                  onClick={() => onCardPurchase(cur)}
                  className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-border bg-surface px-3 py-1 text-xs text-muted transition-colors hover:border-accent/60 hover:text-foreground cursor-pointer"
                >
                  <FiCreditCard /> {label}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* ---------------------------------------------------- левая колонка */}
        <aside className="hidden flex-col gap-4 rounded-2xl border border-border bg-surface-2 p-4 md:flex md:self-start">
          {pkg ? (
            <div className="flex flex-col gap-1">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">
                {t("crypto.sidebar_package", { defaultValue: "Пакет" })}
              </div>
              <div className="text-sm font-semibold text-foreground">{pkg.name}</div>
              <div className="flex items-baseline gap-1.5 text-xs text-muted">
                <span className="text-base font-bold text-foreground">
                  {pkg.tokens.toLocaleString("ru-RU")}
                </span>
                {t("topup.credits", { defaultValue: "кредитов" })}
              </div>
              {bonus > 0 && (
                <div className="inline-flex items-center gap-1 text-xs text-accent">
                  <FiGift /> +{bonus.toLocaleString("ru-RU")} {t("topup.bonus", { defaultValue: "бонус" })}
                </div>
              )}
              <div className="mt-1 text-2xl font-bold tabular-nums text-foreground">
                {priceUsd !== null ? `$${priceUsd.toFixed(2)}` : priceLabel || ""}
              </div>
              {priceUsd !== null && Number.isFinite(kgs) && (
                <div className="text-[11px] text-muted-2">
                  {kgs.toLocaleString("ru-RU")} {t("topup.som", { defaultValue: "сом" })}
                </div>
              )}
            </div>
          ) : (
            <div className="text-sm text-muted">
              {t("crypto.sidebar_resume", { defaultValue: "Возвращаемся к вашему счёту" })}
            </div>
          )}

          <div className="flex flex-col gap-2">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">
              {t("crypto.sidebar_method", { defaultValue: "Способ оплаты" })}
            </div>
            {onCardPurchase &&
              methodRow(
                "kgs",
                <FiCreditCard />,
                t("crypto.method_card_kgs", { defaultValue: "Карта · сом" }),
                t("crypto.method_card_kgs_hint", { defaultValue: "Visa, Mastercard, Элкарт" }),
                false,
                () => onCardPurchase("KGS")
              )}
            {onCardPurchase &&
              methodRow(
                "rub",
                <FiCreditCard />,
                t("crypto.method_card_rub", { defaultValue: "Карта · рубли" }),
                t("crypto.method_card_rub_hint", { defaultValue: "Российские карты" }),
                false,
                () => onCardPurchase("RUB")
              )}
            {methodRow(
              "crypto",
              <span className="flex -space-x-1.5">
                <CoinIcon coin="USDT" size={16} />
                <CoinIcon coin="BTC" size={16} />
              </span>,
              t("crypto.method_crypto", { defaultValue: "Криптовалюта" }),
              t("crypto.method_crypto_hint", {
                count: cryptoCount,
                defaultValue: "{{count}} монет",
              }),
              true
            )}
          </div>

          <p className="flex items-start gap-1.5 text-[11px] leading-snug text-muted-2">
            <FiShield className="mt-px shrink-0" />
            {t("crypto.sidebar_note", {
              defaultValue:
                "Кредиты зачисляются автоматически после подтверждения сети. Вывести их или передать другому аккаунту нельзя.",
            })}
          </p>
        </aside>

        {/* --------------------------------------------------- правая колонка */}
        <section className="flex min-w-0 flex-col gap-3">
          {stage.name === "pick" && (
            <>
              <div className="text-sm font-medium text-muted">
                {t("crypto.pick_title", { defaultValue: "Выберите монету для оплаты" })}
              </div>
              {pickError && (
                <div
                  role="alert"
                  className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-status-fail/40 bg-status-fail/10 px-3 py-2 text-sm text-foreground"
                >
                  <span>{pickError.text}</span>
                  {pickError.kind === "auth" && (
                    <a
                      href={`/auth/signin?next=${encodeURIComponent(returnTo || "/pricing")}`}
                      className="rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-on-accent transition-colors hover:bg-accent-strong"
                    >
                      {t("crypto.sign_in", { defaultValue: "Войти" })}
                    </a>
                  )}
                </div>
              )}
              <CoinPicker
                currencies={currencies}
                priceUsd={priceUsd}
                busyCode={busyCode}
                onPick={(code) => void createInvoice(code)}
              />
              {busyCode && (
                <div className="text-xs text-muted" aria-live="polite">
                  {t("crypto.creating", { defaultValue: "Создаём счёт…" })}
                </div>
              )}
            </>
          )}

          {stage.name === "invoice" && (
            <InvoiceView
              orderId={stage.orderId}
              initial={stage.initial}
              returnTo={returnTo}
              feePaidByUser={feePaidByUser}
              onPaid={onPaid}
              onBack={pkg ? () => setStage({ name: "pick" }) : undefined}
              onClose={onClose}
            />
          )}
        </section>
      </div>
    </Modal>
  );
}

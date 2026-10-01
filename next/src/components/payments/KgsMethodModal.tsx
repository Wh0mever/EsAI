"use client";

import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { FiChevronRight, FiCreditCard, FiLoader, FiShield } from "react-icons/fi";
import { IoQrCodeOutline } from "react-icons/io5";
import { Modal } from "@/components/dialog/Dialog";
import type { KgsMethod, KgsMethodKey } from "@/lib/currency";

/**
 * Окно «чем удобнее оплатить» для оплаты в сомах.
 *
 * Раньше «Пополнить» сразу уводило на страницу Freedom Pay, где способов
 * десяток: люди терялись и уходили. Теперь выбор делается здесь, в два
 * понятных шага — «через приложение банка» или «картой», — а на страницу
 * банка человек попадает уже с выбранным способом.
 *
 * Своего экрана оплаты тут нет: клик по кнопке — это сразу создание платежа и
 * уход на страницу Freedom Pay. Поэтому окно ничего не запрашивает само:
 * список способов, «кто сейчас крутится» и текст ошибки приходят от того, кто
 * его открыл (TokenPackages, TopUpModal).
 *
 * Чужих логотипов нет намеренно: нейтральная плитка с первой буквой или
 * значком — без картинок и товарных знаков.
 *
 * Как и у окна крипты, модалка должна быть одна: открывающий прячет свою.
 */
type Props = {
  open: boolean;
  onClose: () => void;
  /** способы в порядке показа — как отдал сервер (kgs_methods) */
  methods: KgsMethod[];
  /** сумма к оплате с валютой — «490 сом» */
  priceLabel: string;
  packageName?: string;
  /** способ, по которому сейчас создаётся платёж; пока он задан, все кнопки выключены */
  busyKey: KgsMethodKey | null;
  /** понятный человеку текст ошибки; пусто — ошибки нет */
  error?: string | null;
  /**
   * Скидка закреплена за оплатой, начатой другим способом: выбранный способ
   * стоил бы полную цену. Вместо молчаливой подмены суммы — выбор человеку.
   */
  held?: KgsHeldDiscount | null;
  onPick: (method: KgsMethodKey) => void;
  /** «оплатить выбранным способом без скидки» из блока held */
  onPayFull?: () => void;
};

export type KgsHeldDiscount = {
  /** способ, который человек выбрал сейчас и который стоил бы полную цену */
  method: KgsMethodKey;
  /** способ начатой оплаты со скидкой; пусто — она начата без выбора способа */
  heldMethod: string;
  /** «392 сом» — сумма начатой оплаты */
  heldPriceLabel: string;
  /** «490 сом» — цена выбранным способом */
  fullPriceLabel: string;
  /** ссылка на начатую оплату со скидкой */
  redirectUrl: string;
};

export default function KgsMethodModal({
  open,
  onClose,
  methods,
  priceLabel,
  packageName,
  busyKey,
  error,
  held,
  onPick,
  onPayFull,
}: Props) {
  const { t } = useTranslation("common");
  const headingRef = useRef<HTMLHeadingElement>(null);

  // Фокус на заголовок: у Modal нет ловушки фокуса, и без этого клавиатура
  // остаётся на кнопке «Пополнить» под модалкой.
  useEffect(() => {
    if (open) headingRef.current?.focus();
  }, [open]);

  const labels: Record<KgsMethodKey, string> = {
    elqr: t("kgspay.method_elqr", { defaultValue: "Единый QR — любой банк Кыргызстана" }),
    mbank: t("kgspay.method_mbank", { defaultValue: "MBANK" }),
    odengi: t("kgspay.method_odengi", { defaultValue: "О!Деньги" }),
    balance: t("kgspay.method_balance", { defaultValue: "Balance.kg" }),
    megapay: t("kgspay.method_megapay", { defaultValue: "MegaPay" }),
    card: t("kgspay.method_card", { defaultValue: "Картой Visa, Mastercard, Элкарт" }),
  };

  const bankMethods = methods.filter((m) => m.kind !== "card");
  const cardMethods = methods.filter((m) => m.kind === "card");
  const title = t("kgspay.title", { defaultValue: "Как вам удобнее оплатить?" });

  // На телефоне банки идут столбиком, крупными кнопками. На широком экране
  // окно не во всю высоту, и столбик из пяти кнопок уводил «картой» под
  // прокрутку — там банки встают по два в ряд. Длинная подпись единого QR и
  // оставшаяся без пары кнопка занимают ряд целиком.
  const appMethods = bankMethods.filter((m) => m.kind === "app");
  const lastOddApp = appMethods.length % 2 === 1 ? appMethods[appMethods.length - 1].key : null;

  const methodButton = (m: KgsMethod, primary: boolean) => {
    const busy = busyKey === m.key;
    const label = labels[m.key];
    const wide = m.kind !== "app" || m.key === lastOddApp;
    return (
      <button
        key={m.key}
        type="button"
        onClick={() => onPick(m.key)}
        disabled={busyKey !== null}
        aria-busy={busy}
        className={`flex w-full items-center gap-3 rounded-xl border text-left transition-colors disabled:cursor-wait ${
          wide ? "sm:col-span-2" : ""
        } ${primary ? "px-3.5 py-3 sm:py-2.5" : "px-3.5 py-2.5"} ${
          busy
            ? "border-accent bg-accent-soft"
            : "cursor-pointer border-border bg-surface-2 hover:border-accent/70 hover:bg-surface-3 disabled:opacity-60 disabled:hover:border-border disabled:hover:bg-surface-2"
        }`}
      >
        <span
          aria-hidden="true"
          className={`inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-base font-bold sm:h-9 sm:w-9 ${
            primary ? "bg-accent/15 text-accent" : "bg-surface-3 text-foreground"
          }`}
        >
          {m.kind === "qr" ? (
            <IoQrCodeOutline className="h-5 w-5" />
          ) : m.kind === "card" ? (
            <FiCreditCard className="h-5 w-5" />
          ) : (
            label.trim().charAt(0).toUpperCase()
          )}
        </span>
        <span
          className={`min-w-0 flex-1 leading-snug text-foreground ${
            primary ? "text-[15px] font-semibold" : "text-sm font-medium"
          }`}
        >
          {label}
        </span>
        {busy ? (
          <FiLoader className="shrink-0 animate-spin text-accent" />
        ) : (
          <FiChevronRight className="shrink-0 text-muted-2" aria-hidden="true" />
        )}
      </button>
    );
  };

  return (
    <Modal title={title} open={open} onClose={onClose} size="md" mobileFull>
      <div className="flex flex-col gap-5 sm:gap-4">
        <h3 ref={headingRef} tabIndex={-1} className="sr-only">
          {title}
        </h3>

        {/* Что и за сколько: человек должен видеть сумму до выбора способа. */}
        <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-surface-2 px-3.5 py-2.5">
          <span className="min-w-0 truncate text-sm text-muted">{packageName || ""}</span>
          <span className="shrink-0 text-lg font-bold tabular-nums text-foreground">{priceLabel}</span>
        </div>

        {error ? (
          <div
            role="alert"
            className="rounded-xl border border-status-fail/40 bg-status-fail/10 px-3 py-2 text-sm text-foreground"
          >
            {error}
          </div>
        ) : null}

        {held ? (
          <div
            role="alert"
            className="flex flex-col gap-2.5 rounded-xl border border-accent/50 bg-accent/5 px-3.5 py-3"
          >
            <p className="text-sm leading-snug text-foreground">
              {held.heldMethod in labels
                ? t("kgspay.held_text", {
                    method: labels[held.heldMethod as KgsMethodKey],
                    amount: held.heldPriceLabel,
                    defaultValue:
                      "Скидка уже закреплена за оплатой, которую вы начали ({{method}}, {{amount}}). Продолжите её или оплатите выбранным способом без скидки.",
                  })
                : t("kgspay.held_text_plain", {
                    amount: held.heldPriceLabel,
                    defaultValue:
                      "Скидка уже закреплена за оплатой, которую вы начали ({{amount}}). Продолжите её или оплатите выбранным способом без скидки.",
                  })}
            </p>
            <div className="flex flex-col gap-2 sm:flex-row">
              <a
                href={held.redirectUrl}
                className="inline-flex flex-1 items-center justify-center rounded-xl bg-accent px-3 py-2.5 text-center text-sm font-semibold text-on-accent transition-colors hover:bg-accent-strong"
              >
                {t("kgspay.held_continue", {
                  amount: held.heldPriceLabel,
                  defaultValue: "Продолжить со скидкой — {{amount}}",
                })}
              </a>
              <button
                type="button"
                onClick={onPayFull}
                disabled={busyKey !== null}
                className="inline-flex flex-1 cursor-pointer items-center justify-center rounded-xl border border-border bg-surface-2 px-3 py-2.5 text-center text-sm font-medium text-foreground transition-colors hover:bg-surface-3 disabled:cursor-wait disabled:opacity-60"
              >
                {t("kgspay.held_full", {
                  method: labels[held.method],
                  amount: held.fullPriceLabel,
                  defaultValue: "{{method}} без скидки — {{amount}}",
                })}
              </button>
            </div>
          </div>
        ) : null}

        {bankMethods.length > 0 && (
          <section className="flex flex-col gap-2">
            <div className="text-sm font-semibold text-foreground">
              {t("kgspay.section_app", { defaultValue: "Через приложение банка" })}
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {bankMethods.map((m) => methodButton(m, true))}
            </div>
            <p className="text-xs leading-snug text-muted">
              {t("kgspay.section_app_hint", {
                defaultValue:
                  "На странице оплаты укажите номер телефона и подтвердите платёж в приложении. Карту вводить не нужно.",
              })}
            </p>
          </section>
        )}

        {cardMethods.length > 0 && (
          <section className="flex flex-col gap-2">
            <div className="text-sm font-semibold text-muted">
              {t("kgspay.section_card", { defaultValue: "Банковской картой" })}
            </div>
            {cardMethods.map((m) => methodButton(m, false))}
            <p className="text-xs leading-snug text-muted">
              {t("kgspay.section_card_hint", {
                defaultValue: "Данные карты вводятся на защищённой странице Freedom Pay.",
              })}
            </p>
          </section>
        )}

        {/* Пока платёж не создаётся, строка скрыта, но остаётся в разметке:
            иначе экранный диктор не объявит её появление. */}
        <div className={busyKey ? "text-xs text-muted" : "sr-only"} aria-live="polite">
          {busyKey ? t("kgspay.opening", { defaultValue: "Открываем страницу оплаты…" }) : ""}
        </div>

        <p className="flex items-start gap-1.5 border-t border-border pt-3 text-[11px] leading-snug text-muted-2">
          <FiShield className="mt-px shrink-0" />
          {t("kgspay.footer", { defaultValue: "Кредиты зачислятся автоматически после оплаты." })}
        </p>
      </div>
    </Modal>
  );
}

"use client";

import clsx from "clsx";
import { useTranslation } from "react-i18next";
import type { Currency } from "@/lib/currency";

/**
 * CurrencySwitch — переключатель KGS/RUB (задача клиента: ЮKassa попросила
 * показывать цены в рублях, обязательно с ручным переключением — многие ходят
 * через VPN, авто-детект по геолокации IP может ошибиться).
 *
 * Сам компонент валютой не владеет — состояние приходит из useCurrency()
 * (next/src/hooks/useCurrency.ts), общего для всех мест, где показывается
 * цена (TokenPackages, HomePricingPreview, TopUpModal).
 *
 * Над переключателем стоит заголовок: человек видит две кнопки среди тарифов и
 * не всегда понимает, что это выбор валюты, а не что-то про сами пакеты.
 * Подписи — словами, а не значками: «₽» в мелком размере теряется, а
 * кыргызский сом собственного знака в интерфейсе не имеет. Клиент справедливо
 * заметил и раньше: «россияне даже не знают, что значит KGS».
 */
type Props = {
  value: Currency;
  onChange: (code: Currency) => void;
  className?: string;
  /**
   * Показывать ли «КРИПТА». Способ оплаты может быть выключен совсем или
   * открыт только сотрудникам (проверка боевых ключей на проде), и тогда
   * третьей кнопки быть не должно — обещать оплату, которой нет, нельзя.
   */
  cryptoEnabled?: boolean;
};

export default function CurrencySwitch({ value, onChange, className, cryptoEnabled = false }: Props) {
  const { t } = useTranslation("common");

  const currencies: { code: Currency; label: string; title: string }[] = [
    {
      code: "KGS",
      label: t("packages.currency_kgs", { defaultValue: "СОМ" }),
      title: t("packages.currency_kgs_title", { defaultValue: "Кыргызский сом" }),
    },
    {
      code: "RUB",
      label: t("packages.currency_rub", { defaultValue: "РУБЛИ" }),
      title: t("packages.currency_rub_title", { defaultValue: "Российский рубль" }),
    },
  ];

  if (cryptoEnabled) {
    currencies.push({
      code: "USD",
      label: t("packages.currency_crypto", { defaultValue: "КРИПТА" }),
      title: t("packages.currency_crypto_title", {
        defaultValue: "USDT, BTC, ETH, TON — цены в долларах",
      }),
    });
  }

  return (
    <div className={clsx("flex flex-col items-center gap-2", className)}>
      <span className="text-sm font-bold uppercase tracking-wide text-foreground">
        {t("packages.currency_title", { defaultValue: "Валюта оплаты" })}
      </span>

      <div
        className="inline-flex items-center gap-0.5 rounded-lg border border-border bg-surface-2 p-0.5"
        role="group"
        aria-label={t("packages.currency_title", { defaultValue: "Валюта оплаты" })}
      >
        {currencies.map(({ code, label, title }) => (
          <button
            key={code}
            type="button"
            onClick={() => onChange(code)}
            aria-pressed={value === code}
            title={title}
            className={clsx(
              "rounded-md px-3 py-1.5 text-sm font-semibold transition-colors cursor-pointer",
              value === code
                ? "bg-accent text-on-accent"
                : "text-muted hover:text-foreground"
            )}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}

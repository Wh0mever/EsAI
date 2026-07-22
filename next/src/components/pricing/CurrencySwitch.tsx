"use client";

import clsx from "clsx";
import type { Currency } from "@/lib/currency";

/**
 * CurrencySwitch — компактный переключатель KGS/RUB (задача клиента: ЮKassa
 * попросила показывать цены в рублях, обязательно с ручным переключением —
 * многие ходят через VPN, авто-детект по геолокации IP может ошибиться).
 * По стилю — аналог next/src/components/main/LangSwitch.tsx.
 *
 * Сам компонент валютой не владеет — состояние приходит из useCurrency()
 * (next/src/hooks/useCurrency.ts), общего для всех мест, где показывается
 * цена (TokenPackages, HomePricingPreview, TopUpModal).
 */
const CURRENCIES: { code: Currency; label: string }[] = [
  { code: "KGS", label: "KGS" },
  { code: "RUB", label: "RUB" },
];

type Props = {
  value: Currency;
  onChange: (code: Currency) => void;
  className?: string;
};

export default function CurrencySwitch({ value, onChange, className }: Props) {
  return (
    <div
      className={clsx(
        "inline-flex items-center gap-0.5 rounded-lg border border-border bg-surface-2 p-0.5",
        className
      )}
      role="group"
      aria-label="Валюта"
    >
      {CURRENCIES.map(({ code, label }) => (
        <button
          key={code}
          type="button"
          onClick={() => onChange(code)}
          aria-pressed={value === code}
          title={label}
          className={clsx(
            "rounded-md px-2.5 py-1 text-xs font-semibold transition-colors cursor-pointer",
            value === code
              ? "bg-accent text-on-accent"
              : "text-muted hover:text-foreground"
          )}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

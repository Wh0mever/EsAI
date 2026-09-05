"use client";

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { FiLoader } from "react-icons/fi";
import CoinIcon from "./CoinIcon";
import type { CryptoCurrency } from "@/types/crypto";

/**
 * Плитки монет — как на витринах пополнения у игровых площадок: каждая сеть
 * отдельной плиткой, под названием сразу минимум («от $12»).
 *
 * Клик по плитке — это уже создание счёта, отдельной кнопки «дальше» нет:
 * человек выбрал, чем платит, и сразу видит адрес. Плитки, которыми этот
 * пакет оплатить нельзя (минимум процессора выше цены), не прячутся, а
 * гаснут с объяснением: спрятанная монета читается как «у них нет TON»,
 * погашенная — как «TON есть, но не на такую сумму».
 */
type Props = {
  currencies: CryptoCurrency[];
  /** цена пакета в долларах — чтобы погасить монеты с минимумом выше неё */
  priceUsd: number | null;
  /** код монеты, по которой сейчас создаётся счёт */
  busyCode: string | null;
  onPick: (code: string) => void;
};

// Цвет уровня комиссии: дешёвая сеть — спокойный зелёный, дорогая — тот же
// янтарный, что и у остальных предупреждений про деньги.
const FEE_CLASS: Record<string, string> = {
  low: "text-status-ok",
  medium: "text-muted",
  high: "text-status-wait",
};

function tileTitle(row: CryptoCurrency): string {
  // У стейблкоинов сеть — часть имени («USDT (TRC-20)»): монета одна, а
  // адреса в разных сетях несовместимы. У остальных сеть и так одна.
  if (row.coin === "USDT" || row.coin === "USDC") return `${row.coin} (${row.network})`;
  return row.label || row.coin;
}

function money(value: string | null): string | null {
  if (!value) return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  // Минимум показываем с запасом вверх: «от $11.36» при пороге 11.3634 —
  // честнее, чем «от $11.36», за которым прячется отказ на $11.36 ровно.
  return (Math.ceil(n * 100) / 100).toFixed(2);
}

export default function CoinPicker({ currencies, priceUsd, busyCode, onPick }: Props) {
  const { t } = useTranslation("common");

  const rows = useMemo(() => {
    // Популярные — первыми, но порядок внутри групп оставляем серверный:
    // там он выстроен по тому, чем реально платят в наших краях.
    const popular = currencies.filter((c) => c.popular);
    const rest = currencies.filter((c) => !c.popular);
    return [...popular, ...rest];
  }, [currencies]);

  if (rows.length === 0) {
    return (
      <div className="rounded-xl border border-border bg-surface-2 px-4 py-6 text-center text-sm text-muted">
        {t("crypto.no_coins", { defaultValue: "Монеты пока недоступны. Попробуйте позже." })}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
      {rows.map((row) => {
        const min = money(row.min_usd);
        const tooSmall =
          priceUsd !== null && min !== null && Number(min) > priceUsd;
        const busy = busyCode === row.code;
        const disabled = tooSmall || busyCode !== null;

        return (
          <button
            key={row.code}
            type="button"
            onClick={() => !disabled && onPick(row.code)}
            disabled={disabled}
            aria-disabled={disabled}
            title={
              tooSmall
                ? t("crypto.tile_below_min_hint", {
                    min,
                    defaultValue: "Процессор не принимает этой монетой меньше ${{min}}",
                  })
                : undefined
            }
            className={`group flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors ${
              tooSmall
                ? "cursor-not-allowed border-border bg-surface-2 opacity-45"
                : busy
                ? "border-accent bg-accent-soft"
                : "cursor-pointer border-border bg-surface-2 hover:border-accent/70 hover:bg-surface-3 disabled:cursor-wait"
            }`}
          >
            <CoinIcon coin={row.coin} size={30} />
            <span className="min-w-0 flex-1">
              <span className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
                <span className="text-sm font-semibold leading-tight text-foreground">
                  {tileTitle(row)}
                </span>
                {row.extra_id_required && (
                  <span className="shrink-0 rounded-full bg-status-wait/15 px-1.5 py-px text-[10px] font-medium uppercase tracking-wide text-status-wait">
                    memo
                  </span>
                )}
              </span>
              {/* Вторая строка: минимум процессора и уровень комиссии сети.
                  Цифра подписана как минимум, а не «от», — иначе при
                  фиксированной цене пакета она читается как комиссия. */}
              <span
                className={`block text-xs leading-snug ${
                  tooSmall ? "text-status-wait" : "text-muted"
                }`}
              >
                {tooSmall ? (
                  t("crypto.tile_below_min", {
                    min,
                    defaultValue: "минимум ${{min}} — больше цены пакета",
                  })
                ) : (
                  <>
                    {min
                      ? t("crypto.tile_min", { min, defaultValue: "мин. ${{min}}" })
                      : t("crypto.tile_min_unknown", { defaultValue: "минимум уточняется" })}
                    {" · "}
                    <span className={FEE_CLASS[row.network_cost] || FEE_CLASS.medium}>
                      {row.network_cost === "high"
                        ? t("crypto.fee_high", { defaultValue: "комиссия сети высокая" })
                        : row.network_cost === "low"
                        ? t("crypto.fee_low", { defaultValue: "комиссия сети низкая" })
                        : t("crypto.fee_medium", { defaultValue: "комиссия сети средняя" })}
                    </span>
                  </>
                )}
              </span>
            </span>
            {busy && <FiLoader className="shrink-0 animate-spin text-accent" />}
          </button>
        );
      })}
    </div>
  );
}

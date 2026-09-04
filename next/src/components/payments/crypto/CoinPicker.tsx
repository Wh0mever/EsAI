"use client";

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiChevronDown } from "react-icons/fi";
import CoinIcon from "./CoinIcon";
import type { CryptoCurrency } from "@/types/crypto";

/**
 * Выбор монеты и сети.
 *
 * Монеты сгруппированы: у USDT четыре сети, и показывать их четырьмя
 * равноправными строками — верный способ получить перевод в Ethereum за
 * двадцать долларов комиссии. Поэтому сначала монета, потом сеть, и рядом с
 * сетью честно написано, дорогая она или дешёвая.
 */
type Props = {
  currencies: CryptoCurrency[];
  value: string | null;
  onChange: (code: string) => void;
};

type Group = { coin: string; networks: CryptoCurrency[]; popular: boolean };

function groupByCoin(currencies: CryptoCurrency[]): Group[] {
  const map = new Map<string, Group>();
  for (const row of currencies) {
    const key = row.coin || row.code.toUpperCase();
    const group = map.get(key) || { coin: key, networks: [], popular: false };
    group.networks.push(row);
    group.popular = group.popular || row.popular;
    map.set(key, group);
  }
  return [...map.values()];
}

export default function CoinPicker({ currencies, value, onChange }: Props) {
  const { t } = useTranslation("common");
  const groups = useMemo(() => groupByCoin(currencies), [currencies]);
  const selectedCoin = currencies.find((c) => c.code === value)?.coin || null;
  const [openCoin, setOpenCoin] = useState<string | null>(selectedCoin);

  const popular = groups.filter((g) => g.popular);
  const rest = groups.filter((g) => !g.popular);

  const pickCoin = (group: Group) => {
    if (group.networks.length === 1) {
      setOpenCoin(group.coin);
      onChange(group.networks[0].code);
      return;
    }
    setOpenCoin((prev) => (prev === group.coin ? null : group.coin));
  };

  const renderGroup = (group: Group) => {
    const expanded = openCoin === group.coin && group.networks.length > 1;
    const active = group.coin === selectedCoin;
    const single = group.networks[0];

    return (
      <div key={group.coin} className="flex flex-col gap-1.5">
        <button
          type="button"
          onClick={() => pickCoin(group)}
          aria-pressed={active}
          className={`flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors cursor-pointer ${
            active
              ? "border-accent bg-accent-soft"
              : "border-border bg-surface-2 hover:border-accent/60"
          }`}
        >
          <CoinIcon coin={group.coin} size={36} />
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-semibold text-foreground">{group.coin}</span>
            <span className="block truncate text-xs text-muted">
              {group.networks.length > 1
                ? t("crypto.networks_count", {
                    count: group.networks.length,
                    defaultValue: "{{count}} сети на выбор",
                  })
                : single.label}
            </span>
          </span>
          {group.networks.length > 1 ? (
            <FiChevronDown
              className={`shrink-0 text-muted transition-transform ${expanded ? "rotate-180" : ""}`}
            />
          ) : (
            <span className="shrink-0 rounded-full bg-surface-3 px-2 py-0.5 text-[11px] text-muted">
              {single.network}
            </span>
          )}
        </button>

        {expanded && (
          <div className="flex flex-col gap-1.5 pl-3">
            {group.networks.map((row) => (
              <button
                key={row.code}
                type="button"
                onClick={() => onChange(row.code)}
                aria-pressed={row.code === value}
                className={`flex w-full items-center justify-between gap-3 rounded-lg border px-3 py-2 text-left transition-colors cursor-pointer ${
                  row.code === value
                    ? "border-accent bg-accent-soft"
                    : "border-border bg-surface hover:border-accent/60"
                }`}
              >
                <span className="min-w-0">
                  <span className="block text-sm text-foreground">{row.network}</span>
                  <span className="block text-[11px] text-muted-2">
                    {row.network_cost === "high"
                      ? t("crypto.network_high_fee", { defaultValue: "Высокая комиссия сети" })
                      : row.network_cost === "low"
                      ? t("crypto.network_cheap", { defaultValue: "Низкая комиссия сети" })
                      : ""}
                    {row.min_usd
                      ? `${row.network_cost !== "medium" ? " · " : ""}${t("crypto.min_amount", {
                          min: row.min_usd,
                          defaultValue: "минимум ${{min}}",
                        })}`
                      : ""}
                  </span>
                </span>
                {row.extra_id_required && (
                  <span className="shrink-0 rounded-full bg-status-wait/15 px-2 py-0.5 text-[10px] text-status-wait">
                    memo
                  </span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="flex flex-col gap-4">
      {popular.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted">
            {t("crypto.popular", { defaultValue: "Популярные" })}
          </div>
          {popular.map(renderGroup)}
        </div>
      )}
      {rest.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted">
            {t("crypto.all_coins", { defaultValue: "Все монеты" })}
          </div>
          {rest.map(renderGroup)}
        </div>
      )}
    </div>
  );
}

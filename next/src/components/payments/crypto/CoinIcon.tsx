"use client";

import type { IconType } from "react-icons";
import {
  SiBitcoin,
  SiBnbchain,
  SiDogecoin,
  SiEthereum,
  SiLitecoin,
  SiMonero,
  SiSolana,
  SiTether,
  SiTon,
  SiXrp,
} from "react-icons/si";

/**
 * Значок монеты: белый глиф на брендовом кружке.
 *
 * Цвета монет одинаковы в обеих темах — их узнают именно по цвету, и
 * «подгонять под тему» тут нечего. Для TRON готового значка в наборе нет,
 * поэтому кружок с тикером: лучше честная заглушка, чем чужой логотип.
 */
const COINS: Record<string, { icon?: IconType; color: string }> = {
  USDT: { icon: SiTether, color: "#26A17B" },
  USDC: { color: "#2775CA" },
  BTC: { icon: SiBitcoin, color: "#F7931A" },
  ETH: { icon: SiEthereum, color: "#627EEA" },
  TON: { icon: SiTon, color: "#0098EA" },
  LTC: { icon: SiLitecoin, color: "#345D9D" },
  BNB: { icon: SiBnbchain, color: "#F3BA2F" },
  SOL: { icon: SiSolana, color: "#9945FF" },
  DOGE: { icon: SiDogecoin, color: "#C2A633" },
  XRP: { icon: SiXrp, color: "#23292F" },
  XMR: { icon: SiMonero, color: "#FF6600" },
  TRX: { color: "#EF0027" },
};

type Props = {
  coin: string;
  size?: number;
  className?: string;
};

export default function CoinIcon({ coin, size = 40, className = "" }: Props) {
  const key = String(coin || "").toUpperCase();
  const entry = COINS[key];
  const Icon = entry?.icon;
  const color = entry?.color || "var(--surface-3)";

  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center rounded-full text-white ${className}`}
      style={{ width: size, height: size, backgroundColor: color }}
      aria-hidden="true"
    >
      {Icon ? (
        <Icon style={{ fontSize: Math.round(size * 0.52) }} />
      ) : (
        <span
          className="font-bold leading-none"
          style={{ fontSize: Math.max(9, Math.round(size * 0.3)) }}
        >
          {key.slice(0, 3)}
        </span>
      )}
    </span>
  );
}

"use client";

/**
 * Видеостудия, композер: честная раскладка цены (§5.4).
 *
 *   Видео 10 с · 720p · 9:16 — 150 кр
 *   Фото-референсы ×2 — +14 кр
 *   Итого 164 кр. Спишется только за готовый результат
 *   На балансе 1 200 кр (из них 120 кр ждут результата) → останется 916 кр
 *
 * Строки приходят из quote (breakdown: ключ + параметры), цену считает
 * только сервер. Пропорция «auto» показывается словом «Авто».
 */
import { useTranslation } from "react-i18next";
import type { PriceLine, QuoteJSON } from "@/lib/vstudio/types";
import { fmtNum } from "./composerLogic";
import { ct } from "./composerText";

type T = ReturnType<typeof useTranslation>["t"];

export function priceLineText(t: T, line: PriceLine): string {
  const p = line.params || {};
  const credits = fmtNum(line.credits);
  switch (line.key) {
    case "price.video": {
      const ar = p.ar === "auto" || !p.ar ? ct(t, "imagegen.aspectAuto") : String(p.ar);
      if (p.s == null && !p.res) return ct(t, "price.videoShort", { credits });
      return ct(t, "price.video", { s: p.s ?? "", res: p.res ?? "", ar, credits });
    }
    case "price.refs":
      return ct(t, "price.refs", { n: p.n ?? "", credits });
    case "price.image": {
      const n = Number(p.n) || 1;
      return n > 1 ? ct(t, "price.images", { n, credits }) : ct(t, "price.image", { credits });
    }
    default: {
      // Новая строка с сервера, которой фронт ещё не знает: ключ как есть, цена — числом.
      const fn = t as (key: string, options?: Record<string, unknown>) => unknown;
      const out = fn(line.key, { ns: "vstudio", defaultValue: `${line.key} — {{credits}} кр`, ...p, credits });
      return typeof out === "string" ? out : `${credits} кр`;
    }
  }
}

export type PriceBreakdownProps = {
  quote: Pick<QuoteJSON, "credits" | "breakdown" | "balance">;
};

export default function PriceBreakdown({ quote }: PriceBreakdownProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const lines = quote.breakdown || [];
  const b = quote.balance;
  const credits = quote.credits ?? 0;
  const missing = b && b.available < credits ? Math.ceil(credits - b.available) : 0;
  return (
    <div className="flex w-[min(20rem,calc(100vw-2rem))] flex-col gap-2 p-3 text-sm">
      {lines.length > 0 && (
        <ul className="flex flex-col gap-1">
          {lines.map((line, i) => (
            <li key={`${line.key}:${i}`} className="text-foreground">
              {priceLineText(t, line)}
            </li>
          ))}
        </ul>
      )}
      <div className="border-t border-border pt-2">
        <div className="font-semibold text-foreground">{ct(t, "price.total", { credits: fmtNum(credits) })}</div>
        <div className="text-xs text-muted">{ct(t, "price.note")}</div>
      </div>
      {b && (
        <div className="text-xs leading-snug text-muted">
          {ct(t, "price.balance", { balance: fmtNum(b.balance) })}
          {b.reserved > 0 && ` (${ct(t, "price.reserved", { reserved: fmtNum(b.reserved) })})`}
          {typeof b.after === "number" && b.after >= 0 && ` → ${ct(t, "price.after", { after: fmtNum(b.after) })}`}
          {missing > 0 && <div className="mt-1 font-semibold text-status-fail">{ct(t, "price.missing", { n: fmtNum(missing) })}</div>}
        </div>
      )}
    </div>
  );
}

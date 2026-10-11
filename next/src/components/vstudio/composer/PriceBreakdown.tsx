"use client";

/**
 * Видеостудия, композер: честная раскладка цены (§5.4).
 *
 *   Видео 10 с · 720p · 9:16 — 150 кр
 *   Фото-референсы ×2 — +14 кр
 *   Итого 164 кр. Спишется только за готовый результат
 *   Свободно 1 080 кр → останется 916 кр
 *   Ещё 120 кр в резерве, пока идёт генерация. Всего на балансе 1 200 кр.
 *
 * Строки приходят из quote (breakdown: ключ + параметры), цену считает
 * только сервер. Пропорция «auto» показывается словом «Авто». Что сказать о
 * балансе (с резервом и без), решает priceText.balanceLines.
 */
import { useTranslation } from "react-i18next";
import type { PriceLine, QuoteJSON } from "@/lib/vstudio/types";
import { fmtNum } from "./composerLogic";
import { ct } from "./composerText";
import { balanceLines, type BalanceText } from "./priceText";

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
  const credits = quote.credits ?? 0;
  const bal = balanceLines(quote.balance, credits);
  const say = (line: BalanceText) =>
    ct(t, line.key, Object.fromEntries(Object.entries(line.params).map(([k, v]) => [k, fmtNum(v)])));
  return (
    <div className="flex w-[min(20rem,calc(100vw-2rem))] flex-col gap-2.5 p-4 text-sm">
      {lines.length > 0 && (
        <ul className="flex flex-col gap-1.5">
          {lines.map((line, i) => (
            <li key={`${line.key}:${i}`} className="leading-snug text-foreground/85 tabular-nums">
              {priceLineText(t, line)}
            </li>
          ))}
        </ul>
      )}
      <div className={lines.length > 0 ? "border-t border-vs-ink/10 pt-2.5" : ""}>
        <div className="text-[15px] font-semibold text-foreground tabular-nums">{ct(t, "price.total", { credits: fmtNum(credits) })}</div>
        <div className="mt-0.5 text-xs text-vs-accent">{ct(t, "price.note")}</div>
      </div>
      {bal && (
        <div className="text-xs leading-snug text-muted tabular-nums">
          {say(bal.head)}
          {bal.after && ` → ${say(bal.after)}`}
          {/* Резерв — тише и отдельной строкой: в первой остаётся только то, из чего вычитается цена. */}
          {bal.held && <div className="mt-1 text-[11px] text-muted-2">{say(bal.held)}</div>}
          {bal.missing > 0 && (
            <div className="mt-1 font-semibold text-status-fail">{ct(t, "price.missing", { n: fmtNum(bal.missing) })}</div>
          )}
        </div>
      )}
    </div>
  );
}

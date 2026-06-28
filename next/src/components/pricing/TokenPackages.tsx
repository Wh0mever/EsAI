"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchData } from "@/tools/fetchData";
import { FiZap, FiGift } from "react-icons/fi";
import Cookies from "js-cookie";

type Pkg = {
  id: number | string;
  name: string;
  tokens: number;
  bonus_tokens?: number;
  price: number;
  currency: string;
};

/**
 * TokenPackages — full-page token top-up packages for the /pricing route.
 * Shares the same backend contract as the chat TopUpModal:
 *  - GET  /api/plans/packages/  (public)  -> Pkg[]
 *  - POST /api/plans/purchase/  (auth)    -> { redirect_url, order_id, amount, currency }
 *
 * Guests are routed to /auth/signin (with ?next=/pricing) instead of purchasing.
 * Pay-as-you-go tokens, KGS pricing — no subscriptions, no music.
 */
export default function TokenPackages() {
  const { t } = useTranslation("common");
  const [packages, setPackages] = useState<Pkg[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [buyingId, setBuyingId] = useState<string | number | null>(null);
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    setAuthed(Boolean(Cookies.get("access")));
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    (async () => {
      try {
        const res = await fetchData<Pkg[]>("plans/packages/", "GET", null, false);
        if (cancelled) return;
        if (res?.ok && Array.isArray(res.data)) setPackages(res.data);
        else setError(t("topup.load_error", { defaultValue: "Не удалось загрузить пакеты" }));
      } catch {
        if (!cancelled) setError(t("topup.load_error", { defaultValue: "Не удалось загрузить пакеты" }));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [t]);

  const onBuy = async (pkg: Pkg) => {
    // Guests must authenticate before topping up.
    if (!authed) {
      const next = encodeURIComponent("/pricing");
      window.location.href = `/auth/signin?next=${next}`;
      return;
    }
    if (buyingId != null) return;
    setBuyingId(pkg.id);
    setError("");
    try {
      const res = await fetchData<any>("plans/purchase/", "POST", { package_id: pkg.id }, true);
      if (!res?.ok) {
        setError(res?.error || t("topup.purchase_error", { defaultValue: "Не удалось начать оплату" }));
        return;
      }
      const d = res.data || {};
      const url = d.redirect_url || d.payment_url || d.url || d.checkout_url;
      if (url && typeof url === "string") {
        window.location.href = url;
        return;
      }
      // No payment URL (e.g. instant credit / sandbox) — nudge balance listeners.
      try {
        window.dispatchEvent(new CustomEvent("balance:refresh"));
      } catch {}
    } catch {
      setError(t("topup.purchase_error", { defaultValue: "Не удалось начать оплату" }));
    } finally {
      setBuyingId(null);
    }
  };

  return (
    <div className="w-full px-4 sm:px-8 lg:px-16 xl:px-24 2xl:px-40 py-10">
      {loading && (
        <div className="py-10 text-center text-muted">{t("common.loading", { defaultValue: "Загрузка..." })}</div>
      )}

      {error && (
        <div className="mx-auto mb-6 max-w-md rounded-lg border border-rose-500/40 bg-rose-500/10 text-rose-300 text-sm px-3 py-2 text-center">
          {error}
        </div>
      )}

      {!loading && packages.length === 0 && !error && (
        <div className="py-10 text-center text-muted">
          {t("topup.empty", { defaultValue: "Пакеты пока недоступны" })}
        </div>
      )}

      {!loading && packages.length > 0 && (
        <div className="grid gap-5 w-full justify-center [grid-template-columns:repeat(auto-fit,minmax(260px,340px))]">
          {packages.map((p) => (
            <div
              key={p.id}
              className="rounded-3xl border border-border bg-surface hover:border-accent/60 transition-colors p-6 sm:p-8 flex flex-col gap-5"
            >
              <div className="text-center text-foreground text-lg font-semibold">{p.name}</div>

              <div className="flex flex-col items-center gap-1">
                <div className="flex items-baseline gap-2">
                  <span className="text-4xl font-bold text-foreground">{p.tokens.toLocaleString()}</span>
                  <span className="text-sm text-muted">{t("topup.tokens", { defaultValue: "токенов" })}</span>
                </div>
                {!!p.bonus_tokens && p.bonus_tokens > 0 && (
                  <div className="inline-flex items-center gap-1 text-sm text-accent">
                    <FiGift /> +{p.bonus_tokens.toLocaleString()} {t("topup.bonus", { defaultValue: "бонус" })}
                  </div>
                )}
              </div>

              <div className="text-center">
                <span className="text-2xl font-bold text-foreground">{p.price.toLocaleString()}</span>{" "}
                <span className="text-base text-muted">{p.currency}</span>
              </div>

              <button
                type="button"
                onClick={() => onBuy(p)}
                disabled={buyingId != null}
                className="mt-1 inline-flex items-center justify-center gap-2 rounded-xl bg-accent text-on-accent font-semibold text-sm py-3 hover:bg-accent-strong transition-colors cursor-pointer disabled:opacity-60"
              >
                <FiZap />
                {!authed
                  ? t("packages.login_to_topup", { defaultValue: "Войдите, чтобы пополнить" })
                  : buyingId === p.id
                  ? t("common.processing", { defaultValue: "Обработка..." })
                  : t("packages.topup", { defaultValue: "Пополнить" })}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

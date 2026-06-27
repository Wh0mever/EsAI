"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/dialog/Dialog";
import { fetchData } from "@/tools/fetchData";
import { FiZap, FiGift } from "react-icons/fi";

type Pkg = {
  id: number | string;
  name: string;
  tokens: number;
  bonus_tokens?: number;
  price: number;
  currency: string;
};

type Props = {
  open: boolean;
  onClose: () => void;
};

/**
 * TopUpModal — lists token packages (GET /api/plans/packages/) and starts a
 * purchase (POST /api/plans/purchase/). Purchase response is expected to carry
 * a payment URL/params (FreedomPay); we redirect to it when present and degrade
 * gracefully otherwise.
 */
export default function TopUpModal({ open, onClose }: Props) {
  const { t } = useTranslation("common");
  const [packages, setPackages] = useState<Pkg[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [buyingId, setBuyingId] = useState<string | number | null>(null);

  useEffect(() => {
    if (!open) return;
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
    return () => { cancelled = true; };
  }, [open, t]);

  const purchase = async (pkg: Pkg) => {
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
      const url = d.payment_url || d.redirect_url || d.url || d.checkout_url;
      if (url && typeof url === "string") {
        window.location.href = url;
        return;
      }
      // No URL returned (e.g. instant credit / sandbox) — refresh balance and close.
      try { window.dispatchEvent(new CustomEvent("balance:refresh")); } catch {}
      onClose();
    } catch {
      setError(t("topup.purchase_error", { defaultValue: "Не удалось начать оплату" }));
    } finally {
      setBuyingId(null);
    }
  };

  return (
    <Modal title={t("topup.title", { defaultValue: "Пополнить баланс" })} open={open} onClose={onClose} size="lg">
      <div className="p-1 sm:p-2">
        {loading && (
          <div className="py-10 text-center text-muted">{t("common.loading", { defaultValue: "Загрузка..." })}</div>
        )}
        {error && (
          <div className="mb-3 rounded-lg border border-rose-500/40 bg-rose-500/10 text-rose-300 text-sm px-3 py-2">
            {error}
          </div>
        )}
        {!loading && packages.length === 0 && !error && (
          <div className="py-10 text-center text-muted">{t("topup.empty", { defaultValue: "Пакеты пока недоступны" })}</div>
        )}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {packages.map((p) => (
            <div
              key={p.id}
              className="rounded-2xl border border-border bg-surface hover:border-accent/60 transition-colors p-4 flex flex-col"
            >
              <div className="text-sm font-semibold text-foreground">{p.name}</div>
              <div className="mt-2 flex items-baseline gap-1">
                <span className="text-2xl font-bold text-foreground">{p.tokens.toLocaleString()}</span>
                <span className="text-xs text-muted">{t("topup.tokens", { defaultValue: "токенов" })}</span>
              </div>
              {!!p.bonus_tokens && p.bonus_tokens > 0 && (
                <div className="mt-1 inline-flex items-center gap-1 text-xs text-accent">
                  <FiGift /> +{p.bonus_tokens.toLocaleString()} {t("topup.bonus", { defaultValue: "бонус" })}
                </div>
              )}
              <div className="mt-3 text-lg font-semibold text-foreground">
                {p.price.toLocaleString()} {p.currency}
              </div>
              <button
                type="button"
                onClick={() => purchase(p)}
                disabled={buyingId != null}
                className="mt-4 inline-flex items-center justify-center gap-2 rounded-xl bg-accent text-on-accent font-semibold text-sm py-2.5 hover:bg-accent-strong transition-colors cursor-pointer disabled:opacity-60"
              >
                <FiZap />
                {buyingId === p.id
                  ? t("common.processing", { defaultValue: "Обработка..." })
                  : t("topup.buy", { defaultValue: "Купить" })}
              </button>
            </div>
          ))}
        </div>
      </div>
    </Modal>
  );
}

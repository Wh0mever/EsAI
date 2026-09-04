"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import dynamic from "next/dynamic";
import { Modal } from "@/components/dialog/Dialog";
import { fetchData } from "@/tools/fetchData";
import { FiZap, FiGift } from "react-icons/fi";
import { usePackagesValue } from "@/hooks/usePackagesValue";
import { useCurrency } from "@/hooks/useCurrency";
import type { PackageValue } from "@/types/pricing";
import CurrencySwitch from "@/components/pricing/CurrencySwitch";
import PayAsYouGoBanner from "@/components/pricing/PayAsYouGoBanner";
import { apiLang } from "@/lib/apiLang";
import { useCryptoCurrencies } from "@/hooks/useCryptoCurrencies";

// Значки монет и QR нужны только тому, кто выбрал крипту, — в общий бандл
// чата они не попадают.
const CryptoCheckoutModal = dynamic(
  () => import("@/components/payments/crypto/CryptoCheckoutModal"),
  { ssr: false }
);

type Pkg = {
  id: number | string;
  name: string;
  tokens: number;
  bonus_tokens?: number;
  price: number;
  currency: string;
  sort_order?: number;
  badge?: string;
  featured?: boolean;
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
 *
 * Additionally shows a compact "Примерно хватит на" block per card, backed
 * by the shared usePackagesValue() hook (public GET /api/plans/packages/value/,
 * same contract/wording as TokenPackages on /pricing and HomePricingPreview).
 * This is purely additive/informational — merged by id, never gates or
 * touches the purchase flow (price/tokens/buy button) above. TopUpModal is
 * mounted permanently in ChatWorkspace (Modal just renders null while
 * closed), so the hook is gated with usePackagesValue(open) to avoid
 * hitting the endpoint on every chat load — the fetch fires once, the
 * first time the modal is opened.
 */
export default function TopUpModal({ open, onClose }: Props) {
  const { t, i18n } = useTranslation("common");
  const [packages, setPackages] = useState<Pkg[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [buyingId, setBuyingId] = useState<string | number | null>(null);
  const { data: valuePackages } = usePackagesValue(open);
  // Валюта — общее состояние с /pricing и главной (localStorage/cookie, см.
  // useCurrency.ts); переключатель отрисовывается и здесь тоже (жалоба
  // клиента: при клике на баланс в чате открывалось без рублей — раньше
  // тут читалась только уже выбранная валюта, сменить её можно было лишь
  // на /pricing).
  const { currency, setCurrency, cryptoEnabled, format } = useCurrency();
  const crypto = useCryptoCurrencies(open);
  const [checkout, setCheckout] = useState<Pkg | null>(null);
  const valueById = useMemo(() => {
    const map: Record<string, PackageValue> = {};
    for (const item of valuePackages) {
      if (item && item.value) map[String(item.id)] = item.value;
    }
    return map;
  }, [valuePackages]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    (async () => {
      try {
        const res = await fetchData<Pkg[]>(`plans/packages/?lang=${apiLang(i18n.language)}`, "GET", null, false);
        if (cancelled) return;
        if (res?.ok && Array.isArray(res.data)) {
          setPackages([...res.data].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0)));
        } else setError(t("topup.load_error", { defaultValue: "Не удалось загрузить пакеты" }));
      } catch {
        if (!cancelled) setError(t("topup.load_error", { defaultValue: "Не удалось загрузить пакеты" }));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [open, t, i18n.language]);

  const purchase = async (pkg: Pkg) => {
    // Крипта: свой экран оплаты вместо ухода на страницу банка.
    if (currency === "USD" && crypto.enabled) {
      setCheckout(pkg);
      return;
    }
    if (buyingId != null) return;
    setBuyingId(pkg.id);
    setError("");
    try {
      const res = await fetchData<any>("plans/purchase/", "POST", { package_id: pkg.id, pay_currency: currency }, true);
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

  if (checkout) {
    // Две модалки одновременно ломают друг другу Escape и блокировку
    // прокрутки — свою прячем, пока открыт экран оплаты.
    return (
      <CryptoCheckoutModal
        open
        pkg={checkout}
        priceLabel={format(checkout.price, t("topup.som", { defaultValue: "сом" }))}
        currencies={crypto.currencies}
        onPaid={() => {
          setCheckout(null);
          onClose();
        }}
        onClose={() => setCheckout(null)}
      />
    );
  }

  return (
    <Modal title={t("topup.title", { defaultValue: "Выберите пакет кредитов" })} open={open} onClose={onClose} size="lg">
      <div className="p-1 sm:p-2">
        <div className="text-center mb-3">
          <PayAsYouGoBanner compact />
        </div>

        <div className="flex justify-center mb-3">
          <CurrencySwitch value={currency} onChange={setCurrency} cryptoEnabled={cryptoEnabled} />
        </div>

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
          {packages.map((p) => {
            const v = valueById[String(p.id)] || {};
            const valueRows: { key: string; node: string }[] = [];
            if (v.text) {
              valueRows.push({
                key: "text",
                node: t("packages.value_text", {
                  count: v.text.count,
                  defaultValue: "💬 До {{count}} обычных запросов",
                }),
              });
            }
            if (v.image) {
              valueRows.push({
                key: "image",
                node: t("packages.value_image", {
                  count: v.image.count,
                  defaultValue: "🎨 До {{count}} изображений",
                }),
              });
            }
            if (v.video) {
              valueRows.push({
                key: "video",
                node: t("packages.value_video", {
                  count: v.video.count,
                  defaultValue: "🎬 До {{count}} видео",
                }),
              });
            }
            if (v.document) {
              valueRows.push({
                key: "document",
                node: t("packages.value_document", {
                  count: v.document.count,
                  defaultValue: "📄 До {{count}} страниц перевода",
                }),
              });
            }
            return (
              <div
                key={p.id}
                className={`rounded-2xl bg-surface transition-colors p-4 flex flex-col ${
                  p.featured
                    ? "border-2 border-accent shadow-md shadow-accent/10"
                    : "border border-border hover:border-accent/60"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-foreground">{p.name}</span>
                  {p.badge && p.badge.trim() && (
                    <span className="shrink-0 rounded-full bg-accent/15 text-accent-strong text-[11px] font-medium px-2 py-0.5 whitespace-nowrap">
                      {p.badge}
                    </span>
                  )}
                </div>
                <div className="mt-2 flex items-baseline gap-1">
                  <span className="text-2xl font-bold text-foreground">{p.tokens.toLocaleString()}</span>
                  <span className="text-xs text-muted">{t("topup.credits", { defaultValue: "кредитов" })}</span>
                </div>
                {!!p.bonus_tokens && p.bonus_tokens > 0 && (
                  <div className="mt-1 inline-flex items-center gap-1 text-xs text-accent">
                    <FiGift /> +{p.bonus_tokens.toLocaleString()} {t("topup.bonus", { defaultValue: "бонус" })}
                  </div>
                )}
                <div className="mt-3 text-lg font-semibold text-foreground">
                  {format(p.price, t("topup.som", { defaultValue: "сом" }))}
                </div>
                {valueRows.length > 0 && (
                  <div className="mt-3 rounded-xl bg-surface-2 border border-border px-3 py-2.5 flex flex-col gap-1">
                    <div className="text-[11px] font-semibold text-muted uppercase tracking-wide">
                      {t("packages.value_title", { defaultValue: "Примерно хватит на" })}
                    </div>
                    <ul className="flex flex-col gap-0.5 text-xs text-foreground">
                      {valueRows.map((r) => (
                        <li key={r.key}>{r.node}</li>
                      ))}
                    </ul>
                  </div>
                )}
                <button
                  type="button"
                  onClick={() => purchase(p)}
                  disabled={buyingId != null}
                  className="mt-4 inline-flex items-center justify-center gap-2 rounded-xl bg-accent text-on-accent font-semibold text-sm py-2.5 hover:bg-accent-strong transition-colors cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
                >
                  <FiZap />
                  {buyingId === p.id
                    ? t("common.processing", { defaultValue: "Обработка..." })
                    : t("topup.buy", { defaultValue: "Купить" })}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </Modal>
  );
}

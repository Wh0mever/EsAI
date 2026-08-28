"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchData } from "@/tools/fetchData";
import { FiZap, FiGift } from "react-icons/fi";
import Cookies from "js-cookie";
import type { Currency } from "@/lib/currency";
import { apiLang } from "@/lib/apiLang";

type Pkg = {
  id: number | string;
  name: string;
  tokens: number;
  bonus_tokens?: number;
  price: number;
  currency: string;
  sort_order?: number;
  description?: string;
  /** маркетинговая плашка над пакетом (из админки), напр. «⭐ Популярный» */
  badge?: string;
  /** визуально выделить пакет как рекомендованный (из админки) */
  featured?: boolean;
};

/**
 * "Сколько хватит" — приходит отдельным публичным эндпоинтом
 * (GET /api/plans/packages/value/, core/plans/credit_value.py), НЕ связан
 * с денежным GET /api/plans/packages/ и НЕ влияет на него. Категория может
 * отсутствовать (нет эталонной модели) — рендерим только то, что пришло.
 * Музыка сознательно не подключена (решено с клиентом).
 */
type ValueCategory = {
  count: number;
  unit_model_name?: string;
};

type PackageValue = {
  text?: ValueCategory;
  image?: ValueCategory;
  video?: ValueCategory;
  document?: ValueCategory;
};

type PkgWithValue = {
  id: number | string;
  value?: PackageValue;
};

type TokenPackagesProps = {
  /** активный процент exit-discount (useExitDiscount().active), если скидка подтверждена claim-ом */
  discountPercent?: number | null;
  /** заголовок X-Device-Key — прокидывается в purchase/, чтобы бэк мог смёрджить гостевой claim */
  deviceKey?: string;
  /**
   * Отображаемая валюта (переключатель KGS/RUB на /pricing, см.
   * next/src/hooks/useCurrency.ts) — ТОЛЬКО для показа цены, TokenPackage.price
   * на бэкенде всегда в сомах. По умолчанию "KGS" (без пересчёта), если
   * родитель не подключил переключатель валют.
   */
  currency?: Currency;
  /** Пересчёт цены из сомов в currency по курсу с бэкенда — identity по умолчанию. */
  convert?: (priceKgs: number) => number;
  /** вызывается сразу при клике "Купить", до похода на бэк — сигнал для useExitDiscount не показывать попап во время оплаты */
  onPurchaseStart?: () => void;
  /** вызывается после ответа/редиректа покупки (успех или ошибка) */
  onPurchaseEnd?: () => void;
  /**
   * Куда вернуть человека после оплаты и после входа. По умолчанию профиль и
   * /pricing. Студия ставит сюда «/studio»: тот, кто пошёл платить из
   * недоделанного мультфильма, должен вернуться к нему, а не в профиль.
   */
  returnTo?: string;
  /**
   * Чем заменить блок «Примерно хватит на». Нужно витрине студии: там
   * считают не запросы и картинки, а сцены и мультфильмы.
   */
  valueOverride?: (pkg: Pkg) => { title: string; rows: string[] } | null;
};

/**
 * TokenPackages — full-page token top-up packages for the /pricing route.
 * Shares the same backend contract as the chat TopUpModal:
 *  - GET  /api/plans/packages/  (public)  -> Pkg[]
 *  - POST /api/plans/purchase/  (auth)    -> { redirect_url, order_id, amount, currency }
 *
 * Guests are routed to /auth/signin (with ?next=/pricing) instead of purchasing.
 * Pay-as-you-go tokens, KGS pricing — no subscriptions, no music.
 *
 * Additionally fetches GET /api/plans/packages/value/ (public, independent
 * request) to render a "Примерно хватит на" block per card — merged by id.
 * This second fetch is purely additive: it never gates loading/error state
 * and never touches price/discount/purchase logic above.
 */
export default function TokenPackages({
  discountPercent = null,
  deviceKey,
  currency = "KGS",
  convert = (priceKgs: number) => priceKgs,
  onPurchaseStart,
  onPurchaseEnd,
  returnTo,
  valueOverride,
}: TokenPackagesProps = {}) {
  const { t, i18n } = useTranslation("common");
  // Названия и подписи пакетов лежат в базе на трёх языках (админка),
  // поэтому язык уезжает на сервер вместе с запросом.
  const lang = apiLang(i18n.language);
  const [packages, setPackages] = useState<Pkg[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [buyingId, setBuyingId] = useState<string | number | null>(null);
  const [authed, setAuthed] = useState(false);
  // "Хватит на" — второй, независимый fetch. Намеренно НЕ участвует в
  // loading/error денежного состояния выше: если он упадёт или придёт
  // пустым, просто не рендерим доп.блок — покупка (цена/кнопка) должна
  // работать в любом случае.
  const [valueById, setValueById] = useState<Record<string, PackageValue>>({});

  useEffect(() => {
    setAuthed(Boolean(Cookies.get("access")));
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetchData<{ packages: PkgWithValue[] }>(
          `plans/packages/value/?lang=${lang}`,
          "GET",
          null,
          false
        );
        if (cancelled) return;
        const list = Array.isArray(res?.data?.packages) ? res.data!.packages : [];
        if (res?.ok && list.length) {
          const map: Record<string, PackageValue> = {};
          for (const item of list) {
            if (item && item.value) map[String(item.id)] = item.value;
          }
          setValueById(map);
        }
      } catch {
        // тихо игнорируем — доп.блок просто не покажется
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [lang]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    (async () => {
      try {
        const res = await fetchData<Pkg[]>(`plans/packages/?lang=${lang}`, "GET", null, false);
        if (cancelled) return;
        if (res?.ok && Array.isArray(res.data)) {
          const list = [...res.data].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));
          setPackages(list);
        } else setError(t("topup.load_error", { defaultValue: "Не удалось загрузить пакеты" }));
      } catch {
        if (!cancelled) setError(t("topup.load_error", { defaultValue: "Не удалось загрузить пакеты" }));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [t, lang]);

  const onBuy = async (pkg: Pkg) => {
    // Guests must authenticate before topping up.
    if (!authed) {
      const next = encodeURIComponent(returnTo || "/pricing");
      window.location.href = `/auth/signin?next=${next}`;
      return;
    }
    if (buyingId != null) return;
    setBuyingId(pkg.id);
    setError("");
    onPurchaseStart?.();
    try {
      const res = await fetchData<any>(
        "plans/purchase/",
        "POST",
        // Валюта решает платёжный путь: RUB -> ЮKassa, KGS -> FreedomPay.
        { package_id: pkg.id, pay_currency: currency, ...(returnTo ? { return_to: returnTo } : {}) },
        true,
        deviceKey ? { "X-Device-Key": deviceKey } : undefined
      );
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
      onPurchaseEnd?.();
    }
  };

  /**
   * Бейдж и выделение приходят из данных (TokenPackage.badge / .featured,
   * правятся в админке). Текущий состав: Старт / Про (выделен) / Премиум /
   * Максимум. Если ни у кого нет featured (старые данные) — фолбэк на
   * совпадение по имени ("про"/"pro"), чтобы выделение не пропало.
   */
  // Выделенный пакет приходит из данных (TokenPackage.featured, правится в
  // админке). Фолбэк на совпадение по имени («про»/«pro») — для старых данных.
  const anyFeatured = packages.some((p) => p.featured);
  const featuredFallbackIndex = (() => {
    if (anyFeatured) return -1;
    const byName = packages.findIndex((p) => /про|pro/i.test(p.name || ""));
    if (byName !== -1) return byName;
    return packages.length >= 3 ? 1 : -1;
  })();

  const tagline = (p: Pkg, idx: number): string => {
    if (p.description && p.description.trim()) return p.description;
    const defaults = [
      t("packages.tagline_start", { defaultValue: "Для студентов и быстрых задач" }),
      t("packages.tagline_pro", { defaultValue: "Для копирайтеров, SMM, маркетологов, юристов" }),
      t("packages.tagline_business", { defaultValue: "Программисты, команда, тяжёлые PDF/Excel" }),
    ];
    return defaults[idx] || "";
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
        <div className="grid gap-5 w-full justify-center items-stretch [grid-template-columns:repeat(auto-fit,minmax(260px,340px))]">
          {packages.map((p, idx) => {
            const featured = Boolean(p.featured) || idx === featuredFallbackIndex;
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
            const custom = valueOverride ? valueOverride(p) : null;
            return (
              <div
                key={p.id}
                className={`relative rounded-2xl bg-surface transition-colors p-6 sm:p-8 flex flex-col gap-5 ${
                  featured
                    ? "border-2 border-accent shadow-lg shadow-accent/10 sm:scale-[1.03]"
                    : "border border-border hover:border-accent/60"
                }`}
              >
                {p.badge && p.badge.trim() && (
                  <span
                    className={`absolute -top-3 left-1/2 -translate-x-1/2 inline-flex items-center gap-1 rounded-full text-xs font-bold tracking-wide px-3 py-1 shadow whitespace-nowrap ${
                      featured
                        ? "bg-accent text-on-accent"
                        : "bg-surface-2 border border-border text-foreground"
                    }`}
                  >
                    {p.badge}
                  </span>
                )}

                <div className="text-center text-foreground text-lg font-semibold">{p.name}</div>

                <div className="text-center">
                  {discountPercent ? (
                    <>
                      <span className="text-base text-muted line-through mr-2">
                        {convert(p.price).toLocaleString()}
                      </span>
                      <span className="text-2xl font-bold text-accent">
                        {convert(Math.round(p.price * (1 - discountPercent / 100) * 100) / 100).toLocaleString()}
                      </span>
                    </>
                  ) : (
                    <span className="text-2xl font-bold text-foreground">{convert(p.price).toLocaleString()}</span>
                  )}{" "}
                  <span className="text-base text-muted">
                    {currency === "RUB" ? "₽" : p.currency === "KGS" ? t("topup.som", { defaultValue: "сом" }) : p.currency}
                  </span>
                </div>

                {/* Сырой счётчик кредитов — вторично, мелким текстом (п.8 ТЗ:
                    продаём возможности, а не кредиты). Денежная логика не
                    затронута — это чисто отображение существующих полей. */}
                <div className="flex flex-col items-center gap-0.5">
                  <div className="flex items-baseline gap-1.5 text-xs text-muted">
                    <span>{p.tokens.toLocaleString()}</span>
                    <span>{t("topup.credits", { defaultValue: "кредитов" })}</span>
                  </div>
                  {!!p.bonus_tokens && p.bonus_tokens > 0 && (
                    <div className="inline-flex items-center gap-1 text-xs text-accent">
                      <FiGift /> +{p.bonus_tokens.toLocaleString()} {t("topup.bonus", { defaultValue: "бонус" })}
                    </div>
                  )}
                </div>

                {custom ? (
                  <div className="rounded-xl bg-surface-2 border border-border px-3.5 py-3 flex flex-col gap-1.5">
                    <div className="text-xs font-semibold text-muted uppercase tracking-wide">{custom.title}</div>
                    <ul className="flex flex-col gap-1 text-sm text-foreground">
                      {custom.rows.map((r) => (
                        <li key={r}>{r}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {!custom && valueRows.length > 0 && (
                  <div className="rounded-xl bg-surface-2 border border-border px-3.5 py-3 flex flex-col gap-1.5">
                    <div className="text-xs font-semibold text-muted uppercase tracking-wide">
                      {t("packages.value_title", { defaultValue: "Примерно хватит на" })}
                    </div>
                    <ul className="flex flex-col gap-1 text-sm text-foreground">
                      {valueRows.map((r) => (
                        <li key={r.key}>{r.node}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {tagline(p, idx) && (
                  <p className="text-center text-sm text-muted min-h-[2.5rem]">{tagline(p, idx)}</p>
                )}

                <button
                  type="button"
                  onClick={() => onBuy(p)}
                  disabled={buyingId != null}
                  className={`mt-auto inline-flex items-center justify-center gap-2 rounded-xl font-semibold text-sm py-3 transition-colors cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed ${
                    featured
                      ? "bg-accent text-on-accent hover:bg-accent-strong"
                      : "bg-accent/90 text-on-accent hover:bg-accent-strong"
                  }`}
                >
                  <FiZap />
                  {!authed
                    ? t("packages.login_to_topup", { defaultValue: "Войдите, чтобы пополнить" })
                    : buyingId === p.id
                    ? t("common.processing", { defaultValue: "Обработка..." })
                    : t("packages.topup", { defaultValue: "Пополнить" })}
                </button>

              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

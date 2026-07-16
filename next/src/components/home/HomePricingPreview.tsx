"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import Link from "next/link";
import { FiArrowRight } from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";

/**
 * HomePricingPreview — компактное превью тарифов для главной страницы
 * (блок 5 из ТЗ «На что хватит»). НЕ дублирует полную /pricing — это
 * лёгкая витрина, которая тянет живой публичный расчёт "ценности" пакета
 * (GET /api/plans/packages/value/, без авторизации) и ведёт на /pricing.
 *
 * Бэкенд-контракт (core/plans/views.py TokenPackageValueListView,
 * core/plans/credit_value.py compute_all_packages_value):
 *   GET /api/plans/packages/value/ -> { packages: PkgWithValue[] }
 * Каждая категория ("text"/"image"/"video"/"document") в поле value МОЖЕТ
 * отсутствовать (если для неё не настроена эталонная модель) — рендерим
 * только те строки, что реально пришли, без падения.
 *
 * Категория "music" сознательно не подключена (решение с клиентом) — не
 * показываем её ни как активную, ни как "скоро".
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
  name: string;
  tokens: number;
  bonus_tokens?: number;
  price: number | string;
  currency: string;
  badge?: string;
  featured?: boolean;
  sort_order?: number;
  value?: PackageValue;
};

export default function HomePricingPreview() {
  const { t } = useTranslation("common");
  const [packages, setPackages] = useState<PkgWithValue[]>([]);
  const [loading, setLoading] = useState(true);
  const [errored, setErrored] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErrored(false);
    (async () => {
      try {
        const res = await fetchData<{ packages: PkgWithValue[] }>(
          "plans/packages/value/",
          "GET",
          null,
          false
        );
        if (cancelled) return;
        const list = Array.isArray(res?.data?.packages) ? res.data!.packages : [];
        if (res?.ok && list.length) {
          const sorted = [...list].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));
          setPackages(sorted);
        } else {
          setErrored(true);
        }
      } catch {
        if (!cancelled) setErrored(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Ничего не показываем без падения страницы, если данных нет (сеть/ошибка/пустой каталог).
  const nothingToShow = !loading && (errored || packages.length === 0);

  return (
    <section className="w-full px-4 sm:px-8 lg:px-16 xl:px-24 2xl:px-40 py-6">
      <div className="flex flex-col items-center gap-2 text-center mb-3">
        <h2 className="text-2xl sm:text-3xl font-semibold text-foreground">
          {t("home.pricingPreview.title", { defaultValue: "На что хватит пакета" })}
        </h2>
        <p className="text-muted max-w-xl">
          {t("home.pricingPreview.subtitle", {
            defaultValue: "Один баланс — и запросы, и изображения, и видео, и переводы документов.",
          })}
        </p>
      </div>

      {loading && (
        <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="rounded-2xl border border-border bg-surface-2 p-3.5 flex flex-col gap-2 animate-pulse"
            >
              <div className="h-4 w-2/3 rounded bg-surface-3" />
              <div className="h-6 w-1/2 rounded bg-surface-3" />
              <div className="mt-2 flex flex-col gap-2">
                <div className="h-3.5 w-full rounded bg-surface-3" />
                <div className="h-3.5 w-5/6 rounded bg-surface-3" />
                <div className="h-3.5 w-4/6 rounded bg-surface-3" />
                <div className="h-3.5 w-3/6 rounded bg-surface-3" />
              </div>
            </div>
          ))}
        </div>
      )}

      {!loading && !nothingToShow && (
        <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
          {packages.map((p) => {
            const v = p.value || {};
            const rows: { key: string; node: string }[] = [];
            if (v.text) {
              rows.push({
                key: "text",
                node: t("home.pricingPreview.stat_text", {
                  count: v.text.count,
                  defaultValue: "💬 До {{count}} обычных запросов",
                }),
              });
            }
            if (v.image) {
              rows.push({
                key: "image",
                node: t("home.pricingPreview.stat_image", {
                  count: v.image.count,
                  defaultValue: "🎨 До {{count}} изображений",
                }),
              });
            }
            if (v.video) {
              rows.push({
                key: "video",
                node: t("home.pricingPreview.stat_video", {
                  count: v.video.count,
                  defaultValue: "🎬 До {{count}} видео",
                }),
              });
            }
            if (v.document) {
              rows.push({
                key: "document",
                node: t("home.pricingPreview.stat_document", {
                  count: v.document.count,
                  defaultValue: "📄 До {{count}} страниц перевода",
                }),
              });
            }

            return (
              <div
                key={p.id}
                className={`rounded-2xl bg-surface-2 p-3.5 flex flex-col gap-2 transition-colors ${
                  p.featured ? "border-2 border-accent shadow-lg shadow-accent/10" : "border border-border"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-foreground truncate">{p.name}</span>
                  {p.badge && p.badge.trim() && (
                    <span className="shrink-0 rounded-full bg-accent/15 px-2 py-0.5 text-[11px] font-medium text-accent-strong">
                      {p.badge}
                    </span>
                  )}
                </div>

                <div className="text-lg font-bold text-foreground">
                  {Number(p.price).toLocaleString()}{" "}
                  <span className="text-sm font-normal text-muted">
                    {p.currency === "KGS" ? t("topup.som", { defaultValue: "сом" }) : p.currency}
                  </span>
                </div>

                {rows.length > 0 && (
                  <ul className="flex flex-col gap-1 text-sm text-muted">
                    {rows.map((r) => (
                      <li key={r.key}>{r.node}</li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      )}

      <div className="mt-6 flex justify-center">
        <Link
          href="/pricing"
          className="inline-flex items-center gap-2 rounded-xl border border-border px-5 py-2.5 text-sm font-semibold text-foreground hover:border-accent hover:text-accent transition-colors"
        >
          {t("home.pricingPreview.cta", { defaultValue: "Смотреть все тарифы" })}
          <FiArrowRight />
        </Link>
      </div>
    </section>
  );
}

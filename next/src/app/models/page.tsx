"use client";

/**
 * /models — «Каталог AI-моделей» (Этап 4, п.15 ТЗ). Публичная страница,
 * собирающая ВСЕ активные модели EsAI (тот же публичный список, что уже
 * использует chat/ModelSelector.tsx и pricing/CreditsExplainer.tsx —
 * GET ai/models/, без auth: анонимный посетитель должен видеть каталог до
 * регистрации, это отдельная SEO-страница).
 *
 * Категории-фильтры строятся ДИНАМИЧЕСКИ из реального поля category (см.
 * RAW_TO_GROUP ниже) — если для группы на бэке нет ни одной активной модели
 * (например "Музыка" — Suno не подключён), фильтр просто не появляется, без
 * заглушек и хардкода списка категорий.
 *
 * "Попробовать" ведёт либо на готовую SEO-статью /model/<slug> (если модель
 * есть в lib/seo/models.ts — сматчено по openrouter_id), либо прямо в чат с
 * предвыбранной моделью (/?model=<openrouter_id> — тот же паттерн, что уже
 * использует /model/[slug]/page.tsx), чтобы не дублировать SEO-контент.
 *
 * Логотипы — круглые бейджи "инициал вендора + брендовый цвет"
 * (lib/vendorColors.ts), без скачивания картинок (запрещено политикой
 * безопасности без явного разрешения).
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { FiSearch, FiEye, FiCpu, FiGlobe, FiStar, FiArrowRight } from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";
import type { AiModel } from "@/components/chat/ModelSelector";
import { SEO_MODELS } from "@/lib/seo/models";
import { vendorColorByOpenRouterId, vendorInitialByOpenRouterId } from "@/lib/vendorColors";

type EstimatedUsage = { count: number; unit_label: string; package_name: string } | null;

// Расширяем базовый AiModel (chat/ModelSelector.tsx) полем estimated_usage —
// добавлено в AiModelSerializer специально для каталога, оба места
// используют один и тот же ответ ai/models/, дублировать тип не нужно.
type CatalogModel = AiModel & { estimated_usage?: EstimatedUsage };

// Технический category (из админки GPTModels.category) → укрупнённая группа
// каталога. Ровно 9 реальных значений на проде (budget/chat/reasoning/writing/
// search/coding/fast/video/image) — сведены в 4 витринные группы по
// рекомендации разведки. Неизвестное/пустое значение → "text" (безопасный
// дефолт: на проде такого не встречается, но так каталог не падает на новых
// значениях category).
const RAW_TO_GROUP: Record<string, "text" | "code" | "image" | "video"> = {
  chat: "text",
  writing: "text",
  reasoning: "text",
  fast: "text",
  budget: "text",
  search: "text",
  coding: "code",
  image: "image",
  video: "video",
};

const GROUP_ORDER: Array<"text" | "code" | "image" | "video"> = ["text", "code", "image", "video"];

function groupOf(m: CatalogModel): "text" | "code" | "image" | "video" {
  return RAW_TO_GROUP[(m.category || "").toLowerCase()] || "text";
}

// Те же простые эвристики по openrouter_id, что уже использует
// chat/ModelSelector.tsx (isReasoning/isWeb) — там не экспортированы,
// поэтому продублированы локально как маленькие чистые функции.
function isReasoning(m: CatalogModel): boolean {
  const id = (m.openrouter_id || "").toLowerCase();
  return /(^|\/|-)r1(\b|$)|reason|(^|\/)o[13]\b/.test(id);
}
function isWeb(m: CatalogModel): boolean {
  const id = (m.openrouter_id || "").toLowerCase();
  return id.includes("perplexity") || id.includes("sonar");
}

function modelKey(m: CatalogModel): string {
  return String(m.openrouter_id || m.id);
}

/** SEO-статья есть → её slug; иначе прямая ссылка в чат с предвыбранной моделью. */
function tryHref(m: CatalogModel): string {
  const seo = SEO_MODELS.find((s) => s.openrouter_id === m.openrouter_id);
  if (seo) return `/model/${seo.slug}`;
  return `/?model=${encodeURIComponent(m.openrouter_id || String(m.id))}`;
}

function SkeletonCard() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-4 animate-pulse">
      <div className="flex items-center gap-3">
        <div className="h-10 w-10 rounded-full bg-surface-2 shrink-0" />
        <div className="flex-1 min-w-0 flex flex-col gap-2">
          <div className="h-3.5 w-2/3 rounded bg-surface-2" />
          <div className="h-2.5 w-1/3 rounded bg-surface-2" />
        </div>
      </div>
      <div className="mt-3 h-3 w-full rounded bg-surface-2" />
      <div className="mt-1.5 h-3 w-4/5 rounded bg-surface-2" />
      <div className="mt-3.5 h-8 w-full rounded-lg bg-surface-2" />
    </div>
  );
}

export default function ModelsCatalogPage() {
  const { t } = useTranslation("common");
  const [models, setModels] = useState<CatalogModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [query, setQuery] = useState("");
  const [activeGroup, setActiveGroup] = useState<string>("all");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetchData<CatalogModel[]>("ai/models/", "GET", null, false);
        if (cancelled) return;
        const list = Array.isArray(res?.data) ? res.data : [];
        if (!list.length) {
          setLoadError(true);
          return;
        }
        list.sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));
        setModels(list);
      } catch {
        if (!cancelled) setLoadError(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Категории-чипы строятся из того, что реально есть в данных — пустая
  // группа (например "Музыка"/"Документы", которых на проде нет вообще)
  // никогда не попадёт в этот список.
  const groupLabels: Record<string, string> = {
    text: t("models_catalog.category.text", { defaultValue: "Текст" }),
    code: t("models_catalog.category.code", { defaultValue: "Код" }),
    image: t("models_catalog.category.image", { defaultValue: "Изображения" }),
    video: t("models_catalog.category.video", { defaultValue: "Видео" }),
  };

  const availableGroups = useMemo(() => {
    const present = new Set(models.map((m) => groupOf(m)));
    return GROUP_ORDER.filter((g) => present.has(g));
  }, [models]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return models.filter((m) => {
      if (activeGroup !== "all" && groupOf(m) !== activeGroup) return false;
      if (!q) return true;
      return (
        (m.name || "").toLowerCase().includes(q) ||
        (m.description || "").toLowerCase().includes(q)
      );
    });
  }, [models, query, activeGroup]);

  const showSkeleton = loading && models.length === 0;
  const showQuietFallback = !loading && loadError && models.length === 0;

  return (
    <main className="w-full pt-24 sm:pt-28 pb-16">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <header className="mb-5 sm:mb-6 max-w-2xl">
          <h1 className="text-2xl sm:text-3xl font-bold text-foreground leading-tight">
            {t("models_catalog.title", { defaultValue: "Каталог AI-моделей" })}
          </h1>
          <p className="mt-2 text-sm sm:text-base text-muted leading-relaxed">
            {t("models_catalog.subtitle", {
              defaultValue:
                "Все нейросети EsAI в одном месте — сравните возможности и выберите подходящую для своей задачи.",
            })}
          </p>
        </header>

        {/* Поиск + категории */}
        <div className="mb-5 flex flex-col gap-3">
          <div className="flex items-center gap-2 rounded-xl border border-border bg-surface-2 px-3.5 h-11 max-w-md">
            <FiSearch className="text-muted shrink-0" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("models_catalog.search_placeholder", { defaultValue: "Поиск моделей..." })}
              className="flex-1 bg-transparent outline-none text-sm text-foreground placeholder:text-muted-2"
              autoComplete="off"
              spellCheck={false}
            />
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setActiveGroup("all")}
              className={`rounded-full border px-3.5 py-1.5 text-sm font-medium transition-colors cursor-pointer ${
                activeGroup === "all"
                  ? "border-accent bg-accent-soft text-accent-strong"
                  : "border-border text-muted hover:text-foreground hover:border-accent/60"
              }`}
            >
              {t("models_catalog.category_all", { defaultValue: "Все" })}
            </button>
            {availableGroups.map((g) => (
              <button
                key={g}
                type="button"
                onClick={() => setActiveGroup(g)}
                className={`rounded-full border px-3.5 py-1.5 text-sm font-medium transition-colors cursor-pointer ${
                  activeGroup === g
                    ? "border-accent bg-accent-soft text-accent-strong"
                    : "border-border text-muted hover:text-foreground hover:border-accent/60"
                }`}
              >
                {groupLabels[g]}
              </button>
            ))}
          </div>
        </div>

        {/* Результаты */}
        {showSkeleton ? (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3.5">
            {Array.from({ length: 6 }).map((_, i) => (
              <SkeletonCard key={i} />
            ))}
          </div>
        ) : showQuietFallback ? (
          <div className="rounded-2xl border border-border bg-surface-2 p-8 text-center text-muted text-sm">
            {t("models_catalog.load_error", {
              defaultValue: "Не удалось загрузить каталог моделей. Попробуйте обновить страницу.",
            })}
          </div>
        ) : filtered.length === 0 ? (
          <div className="rounded-2xl border border-border bg-surface-2 p-8 text-center text-muted text-sm">
            {t("models_catalog.empty_hint", {
              defaultValue: "Ничего не найдено. Попробуйте изменить запрос или категорию.",
            })}
          </div>
        ) : (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3.5">
            {filtered.map((m) => {
              const color = vendorColorByOpenRouterId(m.openrouter_id);
              const initial = vendorInitialByOpenRouterId(m.openrouter_id);
              const desc = (m.description || "").trim();
              const usage = m.estimated_usage;
              return (
                <div
                  key={modelKey(m)}
                  className="rounded-2xl border border-border bg-surface p-4 flex flex-col gap-3"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <span
                      aria-hidden
                      className="h-10 w-10 rounded-full grid place-items-center font-bold text-base shrink-0"
                      style={{ background: `${color}22`, color }}
                    >
                      {initial}
                    </span>
                    <div className="min-w-0 flex-1">
                      <span className="flex items-center gap-1.5 min-w-0">
                        <span className="truncate font-semibold text-foreground">{m.name}</span>
                        {m.recommended && (
                          <FiStar
                            className="text-amber-400 shrink-0"
                            size={14}
                            title={t("models_catalog.badge_recommended", { defaultValue: "Рекомендуемая" })}
                          />
                        )}
                      </span>
                      <span className="block text-xs text-muted-2 truncate">{groupLabels[groupOf(m)]}</span>
                    </div>
                  </div>

                  {desc && <p className="text-sm text-muted leading-relaxed line-clamp-2">{desc}</p>}

                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="inline-flex items-center rounded-md bg-surface-2 px-2 py-0.5 text-[11px] font-medium text-muted">
                      {groupLabels[groupOf(m)]}
                    </span>
                    {m.supports_vision && (
                      <span
                        className="inline-flex items-center gap-1 rounded-md bg-blue-400/10 px-2 py-0.5 text-[11px] font-medium text-blue-400"
                        title={t("models_catalog.cap_vision", { defaultValue: "Понимает изображения" })}
                      >
                        <FiEye size={11} /> {t("models_catalog.cap_vision", { defaultValue: "Понимает изображения" })}
                      </span>
                    )}
                    {isReasoning(m) && (
                      <span
                        className="inline-flex items-center gap-1 rounded-md bg-purple-400/10 px-2 py-0.5 text-[11px] font-medium text-purple-400"
                        title={t("models_catalog.cap_reasoning", { defaultValue: "Рассуждающая модель" })}
                      >
                        <FiCpu size={11} /> {t("models_catalog.cap_reasoning", { defaultValue: "Рассуждающая модель" })}
                      </span>
                    )}
                    {isWeb(m) && (
                      <span
                        className="inline-flex items-center gap-1 rounded-md bg-amber-400/10 px-2 py-0.5 text-[11px] font-medium text-amber-400"
                        title={t("models_catalog.cap_web", { defaultValue: "Поиск в интернете" })}
                      >
                        <FiGlobe size={11} /> {t("models_catalog.cap_web", { defaultValue: "Поиск в интернете" })}
                      </span>
                    )}
                    {m.is_free && (
                      <span className="inline-flex items-center rounded-md bg-accent/15 px-2 py-0.5 text-[11px] font-medium text-accent-strong">
                        {t("models_catalog.badge_free", { defaultValue: "Бесплатная" })}
                      </span>
                    )}
                  </div>

                  <div className="mt-auto flex items-center justify-between gap-3 pt-1">
                    {usage ? (
                      <span
                        className="text-xs text-muted-2 truncate"
                        title={
                          usage.package_name
                            ? t("models_catalog.cost_from_package", {
                                defaultValue: "На тарифе «{{name}}»",
                                name: usage.package_name,
                              })
                            : undefined
                        }
                      >
                        {t("models_catalog.cost_from", {
                          defaultValue: "Примерно от {{count}} {{unit}}",
                          count: usage.count,
                          unit: usage.unit_label,
                        })}
                      </span>
                    ) : (
                      <span />
                    )}
                    <Link
                      href={tryHref(m)}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-accent text-on-accent text-xs font-semibold px-3 py-2 hover:bg-accent-strong transition-colors shrink-0"
                    >
                      {t("models_catalog.try_button", { defaultValue: "Попробовать" })}
                      <FiArrowRight size={12} />
                    </Link>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </main>
  );
}

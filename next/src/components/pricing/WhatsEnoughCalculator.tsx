"use client";

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { usePackagesValue } from "@/hooks/usePackagesValue";

/**
 * WhatsEnoughCalculator — блок «На что хватит?» (ТЗ Этап 3, п.14).
 *
 * Пользователь выбирает ОДИН сценарий использования (общение с AI /
 * изображения / видео / документы — без музыки, решение согласовано с
 * клиентом ранее) и видит, на что хватит каждого активного пакета именно
 * для этого сценария, плюс какой пакет рекомендован (флаг с бэка).
 *
 * Бэкенд-контракт (core/plans/views.py TokenPackageValueListView,
 * core/plans/credit_value.py compute_all_packages_value):
 *   GET /api/plans/packages/value/ -> { packages: PkgWithValue[] }
 * value.<category> = { count, unit_model_name, recommended } — recommended
 * простановка полностью серверная (см. _mark_recommended), фронт её не
 * пересчитывает, только отображает. Категория может отсутствовать у
 * конкретного пакета (эталонная модель не настроена) — такой пакет просто
 * не показываем в списке для этого сценария, без падения вёрстки.
 *
 * Один fetch при монтировании — переключение сценария дальше работает по
 * уже загруженным данным, без повторных запросов к бэку.
 */

type ScenarioKey = "text" | "image" | "video" | "document";

const SCENARIOS: { key: ScenarioKey; emoji: string }[] = [
  { key: "text", emoji: "💬" },
  { key: "image", emoji: "🎨" },
  { key: "video", emoji: "🎬" },
  { key: "document", emoji: "📄" },
];

export default function WhatsEnoughCalculator() {
  const { t } = useTranslation("common");
  const { data: packages, loading, error: errored } = usePackagesValue();
  const [scenario, setScenario] = useState<ScenarioKey>("text");

  const scenarioLabels: Record<ScenarioKey, string> = {
    text: t("pricing.whatsEnough.scenario_text", { defaultValue: "Общение с AI" }),
    image: t("pricing.whatsEnough.scenario_image", { defaultValue: "Генерация изображений" }),
    video: t("pricing.whatsEnough.scenario_video", { defaultValue: "Генерация видео" }),
    document: t("pricing.whatsEnough.scenario_document", { defaultValue: "Работа с документами" }),
  };

  const rowTemplate = (category: ScenarioKey, count: number, model: string): string => {
    switch (category) {
      case "text":
        return t("pricing.whatsEnough.row_text", {
          count,
          model,
          defaultValue: "До {{count}} запросов к {{model}}",
        });
      case "image":
        return t("pricing.whatsEnough.row_image", {
          count,
          model,
          defaultValue: "До {{count}} изображений {{model}}",
        });
      case "video":
        return t("pricing.whatsEnough.row_video", {
          count,
          model,
          defaultValue: "До {{count}} видео {{model}}",
        });
      case "document":
        return t("pricing.whatsEnough.row_document", {
          count,
          model,
          defaultValue: "До {{count}} страниц перевода {{model}}",
        });
    }
  };

  // Только пакеты, у которых для выбранного сценария реально есть данные
  // (эталонная модель настроена) — остальные тихо не показываем.
  const visiblePackages = useMemo(
    () => packages.filter((p) => p.value?.[scenario] != null),
    [packages, scenario]
  );

  const nothingToShow = !loading && (errored || packages.length === 0);
  const emptyForScenario = !loading && !nothingToShow && visiblePackages.length === 0;

  return (
    <div className="lg:px-40 px-6 w-full">
      <div className="mt-4 rounded-2xl border border-border bg-surface-2 p-6 md:p-8 flex flex-col gap-5">
        <div className="flex flex-col gap-1.5">
          <h3 className="text-2xl font-semibold text-foreground">
            {t("pricing.whatsEnough.title", { defaultValue: "На что хватит?" })}
          </h3>
          <p className="text-muted text-sm">
            {t("pricing.whatsEnough.subtitle", {
              defaultValue: "Выберите, чем планируете пользоваться чаще всего — покажем реальные цифры по каждому пакету.",
            })}
          </p>
        </div>

        {/* Выбор сценария */}
        <div className="flex flex-wrap gap-2">
          {SCENARIOS.map((s) => {
            const active = scenario === s.key;
            return (
              <button
                key={s.key}
                type="button"
                onClick={() => setScenario(s.key)}
                className={`inline-flex items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-semibold transition-colors cursor-pointer ${
                  active
                    ? "bg-accent text-on-accent"
                    : "bg-surface border border-border text-foreground hover:border-accent/60"
                }`}
              >
                <span aria-hidden="true">{s.emoji}</span>
                {scenarioLabels[s.key]}
              </button>
            );
          })}
        </div>

        {/* Результат по выбранному сценарию */}
        {loading && (
          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className="rounded-xl border border-border bg-surface p-3.5 flex flex-col gap-2 animate-pulse"
              >
                <div className="h-4 w-2/3 rounded bg-surface-3" />
                <div className="h-3.5 w-full rounded bg-surface-3" />
              </div>
            ))}
          </div>
        )}

        {nothingToShow && (
          <p className="text-sm text-muted">
            {t("pricing.whatsEnough.load_error", { defaultValue: "Не удалось загрузить расчёт. Попробуйте обновить страницу." })}
          </p>
        )}

        {emptyForScenario && (
          <p className="text-sm text-muted">
            {t("pricing.whatsEnough.no_data", { defaultValue: "Для этого сценария пока нет данных." })}
          </p>
        )}

        {!loading && visiblePackages.length > 0 && (
          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
            {visiblePackages.map((p) => {
              const v = p.value![scenario]!;
              const recommended = Boolean(v.recommended);
              const model = v.unit_model_name || "";
              return (
                <div
                  key={p.id}
                  className={`relative rounded-xl p-3.5 flex flex-col gap-1.5 transition-colors ${
                    recommended
                      ? "border-2 border-accent bg-surface shadow-lg shadow-accent/10"
                      : "border border-border bg-surface"
                  }`}
                >
                  {recommended && (
                    <span className="absolute -top-2.5 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full bg-accent px-2.5 py-0.5 text-[11px] font-bold text-on-accent shadow">
                      {t("pricing.whatsEnough.recommended_badge", { defaultValue: "Рекомендуем для этой задачи" })}
                    </span>
                  )}

                  <div className="flex items-center justify-between gap-2 mt-1">
                    <span className="text-lg font-semibold text-foreground truncate">{p.name}</span>
                  </div>

                  <p className="text-sm text-muted leading-snug">{rowTemplate(scenario, v.count, model)}</p>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

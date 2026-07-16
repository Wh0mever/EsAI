"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchData } from "@/tools/fetchData";
import { vendorColorByOpenRouterId } from "@/lib/vendorColors";

/**
 * CreditsExplainer — блок «Как списываются кредиты?» для страницы тарифов.
 * Текст — дословно от владельца продукта. Тариф-таблица тянется из ai/models/
 * (markup_coefficient = кредитов за 1000 токенов), с фолбэком на анонсированные
 * ставки, чтобы прайс показывался даже при сбое сети.
 */

type ModelRow = {
  name: string;
  openrouter_id?: string;
  markup_coefficient?: number;
  is_free?: boolean;
  sort_order?: number;
};

// Фолбэк = ставки, анонсированные клиентом (кредитов за 1000 токенов).
const FALLBACK: ModelRow[] = [
  { name: "DeepSeek V3", openrouter_id: "deepseek/deepseek-chat", markup_coefficient: 1, is_free: true, sort_order: 10 },
  { name: "Gemini Flash", openrouter_id: "google/gemini-2.5-flash", markup_coefficient: 11, is_free: true, sort_order: 20 },
  { name: "DeepSeek R1", openrouter_id: "deepseek/deepseek-r1", markup_coefficient: 7, is_free: false, sort_order: 30 },
  { name: "ChatGPT", openrouter_id: "openai/gpt-4o", markup_coefficient: 17, is_free: false, sort_order: 40 },
  { name: "Claude Sonnet", openrouter_id: "anthropic/claude-sonnet-4.5", markup_coefficient: 17, is_free: false, sort_order: 50 },
  { name: "Grok", openrouter_id: "x-ai/grok-4.3", markup_coefficient: 4, is_free: false, sort_order: 60 },
  { name: "Perplexity", openrouter_id: "perplexity/sonar", markup_coefficient: 17, is_free: false, sort_order: 70 },
];

// Цвета вендоров вынесены в общий next/src/lib/vendorColors.ts — единый
// источник палитры, которым также пользуются home/HomeHero.tsx и
// home/PopularModels.tsx (чтобы FLUX/Kling и остальные вендоры совпадали
// цветом во всех блоках сайта).

export default function CreditsExplainer() {
  const { t } = useTranslation("common");
  const [rows, setRows] = useState<ModelRow[]>(FALLBACK);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetchData<ModelRow[]>("ai/models/", "GET", null, false);
        if (cancelled) return;
        const list = Array.isArray(res?.data) ? res.data : [];
        const usable = list
          .filter((m) => typeof m.markup_coefficient === "number")
          .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));
        if (usable.length) setRows(usable);
      } catch {
        /* оставляем фолбэк */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="lg:px-40 px-6 w-full">
      <div className="mt-4 rounded-2xl border border-border bg-surface-2 p-6 md:p-8 flex flex-col gap-4">
        <h3 className="text-2xl font-semibold text-foreground">
          {t("packages.credits_explainer_title", { defaultValue: "Как списываются кредиты?" })}
        </h3>

        <div className="text-muted flex flex-col gap-3 max-w-2xl leading-relaxed">
          <p>
            {t("packages.credits_explainer_p1", {
              defaultValue:
                "Каждая нейросеть расходует кредиты по-разному. Чем мощнее модель, тем больше кредитов расходуется за один и тот же объём текста.",
            })}
          </p>
          <p>
            {t("packages.credits_explainer_p2", {
              defaultValue:
                "Например, если задать один и тот же вопрос разным нейросетям, расход кредитов будет отличаться.",
            })}
          </p>
          <p>
            {t("packages.credits_explainer_p3", {
              defaultValue: "Точное количество списанных кредитов зависит от длины вашего запроса и ответа нейросети.",
            })}
          </p>
          <p>
            {t("packages.credits_explainer_p4", {
              defaultValue: "После каждого ответа вы сразу видите, сколько кредитов было списано именно за этот запрос.",
            })}
          </p>
        </div>

        {/* Тариф по моделям */}
        <div className="mt-2 overflow-hidden rounded-xl border border-border">
          <div className="grid grid-cols-[1fr_auto] items-center gap-2 bg-surface px-4 py-2.5 text-xs uppercase tracking-wide text-muted-2">
            <span>{t("packages.credits_table_model", { defaultValue: "Модель" })}</span>
            <span className="text-right">
              {t("packages.credits_table_rate", { defaultValue: "Кредитов за 1000 токенов" })}
            </span>
          </div>
          <ul className="divide-y divide-border">
            {rows.map((m) => (
              <li
                key={m.openrouter_id || m.name}
                className="grid grid-cols-[1fr_auto] items-center gap-2 px-4 py-3"
              >
                <span className="flex items-center gap-2.5 min-w-0">
                  <span
                    className="h-2.5 w-2.5 rounded-full shrink-0"
                    style={{ background: vendorColorByOpenRouterId(m.openrouter_id) }}
                  />
                  <span className="truncate text-foreground">{m.name}</span>
                  {m.is_free && (
                    <span className="shrink-0 rounded-md bg-accent/15 px-1.5 py-0.5 text-[11px] font-medium text-accent-strong">
                      {t("packages.credits_free_badge", { defaultValue: "бесплатная" })}
                    </span>
                  )}
                </span>
                <span className="text-right tabular-nums font-semibold text-foreground">
                  {Number(m.markup_coefficient)}
                </span>
              </li>
            ))}
          </ul>
        </div>

        <p className="text-xs text-muted-2">
          {t("packages.credits_free_note", {
            defaultValue:
              "«Бесплатная» — модель доступна без оплаты на стартовом балансе; кредиты за ответ всё равно списываются по её тарифу. Премиум-модели доступны после пополнения баланса.",
          })}
        </p>
      </div>
    </div>
  );
}

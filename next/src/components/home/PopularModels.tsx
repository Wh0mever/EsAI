"use client";

import Link from "next/link";
import { useTranslation } from "react-i18next";
import { FiArrowRight, FiHelpCircle } from "react-icons/fi";
import { vendorColor } from "@/lib/vendorColors";

/**
 * PopularModels — секция «Популярные модели» для главной страницы (блок 3 из
 * 8 в новой структуре лендинга). Показывает самые узнаваемые модели как
 * текстовые wordmark-чипы в брендовых цветах вендора — никаких скачанных
 * логотипов-картинок (запрещено политикой безопасности без явного разрешения).
 *
 * Цвета берутся из общего next/src/lib/vendorColors.ts — единого источника
 * палитры вендоров в этом проекте (тот же модуль импортирует HomeHero.tsx и
 * pricing/CreditsExplainer.tsx). Veo и Sora — продукты тех же вендоров
 * (Google и OpenAI соответственно), поэтому взяли тот же акцент, что и их
 * родительская модель. FLUX и Kling не входят в вендорский список ai/models/
 * (это отдельные image/video-провайдеры), поэтому у них свои ключи в общей
 * карте, но цвет совпадает с тем, что использует HomeHero.
 *
 * Статична (кроме i18n), поэтому не тянет данные с бэка — но помечена
 * "use client", потому что useTranslation требует клиентского рендера
 * (см. Footer.tsx / WhyEsAI.tsx — тот же паттерн в этом кодбейзе).
 *
 * Ссылка "Смотреть все модели" ведёт на /models — публичная страница
 * появится на следующем этапе; до неё короткое окно 404 ожидаемо и
 * приемлемо (согласовано с клиентом).
 */

type ModelChip = {
  key: string;
  name: string;
  color: string;
};

const MODELS: ModelChip[] = [
  { key: "gpt", name: "GPT", color: vendorColor("openai") },
  { key: "claude", name: "Claude", color: vendorColor("anthropic") },
  { key: "gemini", name: "Gemini", color: vendorColor("google") },
  { key: "grok", name: "Grok", color: vendorColor("x-ai") },
  { key: "deepseek", name: "DeepSeek", color: vendorColor("deepseek") },
  { key: "veo", name: "Veo", color: vendorColor("google") },
  { key: "flux", name: "FLUX", color: vendorColor("flux") },
  { key: "kling", name: "Kling", color: vendorColor("kling") },
  { key: "sora", name: "Sora", color: vendorColor("openai") },
];

export default function PopularModels() {
  const { t } = useTranslation("common");

  return (
    <section
      aria-label={t("home.popularModels.title", { defaultValue: "Популярные модели" })}
      className="w-full py-5 sm:py-6"
    >
      <div className="mx-auto max-w-4xl px-4 sm:px-6 lg:px-8 flex flex-col items-center">
        <h2 className="text-2xl sm:text-3xl font-bold text-foreground text-center mb-3">
          {t("home.popularModels.title", { defaultValue: "Популярные модели" })}
        </h2>
        <p className="text-muted text-center max-w-xl mb-4 sm:mb-5">
          {t("home.popularModels.subtitle", {
            defaultValue: "Каждая нейросеть хороша в своём — весь список в каталоге моделей.",
          })}
        </p>

        {/* Wordmark-чипы моделей — текст + брендовый цвет, без картинок-логотипов */}
        <ul className="flex flex-wrap items-center justify-center gap-2 max-w-2xl">
          {MODELS.map((m) => (
            <li key={m.key}>
              <span
                className="inline-flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-sm font-semibold"
                style={{
                  color: m.color,
                  borderColor: `${m.color}40`,
                  background: `${m.color}14`,
                }}
              >
                <span aria-hidden className="h-2 w-2 rounded-full shrink-0" style={{ background: m.color }} />
                {m.name}
              </span>
            </li>
          ))}
        </ul>

        {/* Дружелюбный inline-callout — снимает страх "слишком много моделей" у новичка */}
        <div className="mt-3 inline-flex items-center gap-2.5 rounded-xl border border-border bg-surface-2 px-4 py-2.5 text-sm max-w-xl">
          <FiHelpCircle aria-hidden className="text-accent-strong shrink-0" size={18} />
          <p className="text-left text-muted">
            <span className="text-foreground font-medium">
              {t("home.popularModels.callout_q", { defaultValue: "Не знаете, какую модель выбрать?" })}
            </span>{" "}
            {t("home.popularModels.callout_a", { defaultValue: "EsAI подскажет наиболее подходящую." })}
          </p>
        </div>

        <Link
          href="/models"
          className="mt-3 inline-flex items-center gap-2 rounded-xl border border-border px-5 py-2.5 text-sm font-semibold text-foreground hover:border-accent hover:text-accent transition-colors"
        >
          {t("home.popularModels.cta", { defaultValue: "Смотреть все модели" })}
          <FiArrowRight aria-hidden />
        </Link>
      </div>
    </section>
  );
}

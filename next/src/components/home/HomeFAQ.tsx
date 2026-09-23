"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { FiChevronDown } from "react-icons/fi";

/**
 * HomeFAQ — компактный FAQ-блок для главной страницы (блок 7 из ТЗ клиента).
 *
 * Показывает 4 самых общих вопроса, переиспользуя РЕАЛЬНЫЙ контент полной
 * страницы /faq (ключи common.json → faq.questions.0..3), а не выдуманные
 * заново формулировки — единый источник правды для текста ответов, который
 * автоматически подхватывает переводы en/kg наравне с /faq.
 *
 * Простой аккордеон (один открытый вопрос за раз), тот же визуальный язык,
 * что и в next/src/app/faq/page.tsx (rounded-xl border border-border
 * bg-surface-2, FiChevronDown с поворотом).
 */

// Самые общие вопросы для компактного превью — подмножество faq.questions.
const PREVIEW_KEYS = ["0", "1", "2", "3"] as const;

// Дословный контент этих вопросов на момент разведки (см. common.json →
// faq.questions.0..3) — используется только как defaultValue-фолбэк, если
// перевод для текущего языка ещё не подтянулся.
const FALLBACK_QA: Record<string, { q: string; a: string[] }> = {
  "0": {
    q: "Что такое EsAI?",
    a: [
      "EsAI — это единая платформа, где собраны самые популярные нейросети.",
      "В одном месте можно пользоваться ChatGPT, Claude, Gemini, DeepSeek, DeepSeek R1, Grok и Perplexity — без необходимости переходить между разными сервисами.",
    ],
  },
  "1": {
    q: "Как начать пользоваться?",
    a: [
      "Выберите нужную нейросеть, задайте вопрос и получите ответ за несколько секунд.",
      "Сразу после регистрации на баланс поступают бесплатные кредиты, а пока вы не покупали пакет, баланс каждый день бесплатно пополняется до дневной нормы.",
    ],
  },
  "2": {
    q: "Нужно ли оформлять подписку?",
    a: [
      "Нет. В EsAI нет обязательной подписки.",
      "Вы самостоятельно пополняете баланс кредитами и используете их тогда, когда это действительно нужно.",
    ],
  },
  "3": {
    q: "Что такое кредиты?",
    a: [
      "Кредиты — это внутренняя валюта EsAI.",
      "Они расходуются при каждом запросе к нейросети.",
      "Чем мощнее выбранная модель и длиннее запрос с ответом, тем больше кредитов потребуется.",
    ],
  },
};

export default function HomeFAQ() {
  const { t } = useTranslation("common");
  const [openKey, setOpenKey] = useState<string | null>(null);

  return (
    <section aria-label="Частые вопросы" className="border-t border-border bg-background">
      <div className="mx-auto max-w-3xl px-4 py-5 sm:py-6">
        <div className="text-center mb-4 sm:mb-5">
          <h2 className="text-2xl sm:text-3xl font-bold">
            {t("home.faq.title", { defaultValue: "Частые вопросы" })}
          </h2>
          <p className="text-muted mt-2 max-w-xl mx-auto">
            {t("home.faq.subtitle", {
              defaultValue: "Коротко о главном. Остальные вопросы — в полном FAQ.",
            })}
          </p>
        </div>

        {/* Аккордеон: один открытый вопрос за раз, тот же паттерн, что на /faq */}
        <div className="space-y-2">
          {PREVIEW_KEYS.map((key) => {
            const fallback = FALLBACK_QA[key];
            const question = t(`faq.questions.${key}.q`, { defaultValue: fallback.q });
            const rawAnswer = t(`faq.questions.${key}.a`, {
              returnObjects: true,
              defaultValue: fallback.a,
            });
            const answerItems = Array.isArray(rawAnswer) ? rawAnswer : [String(rawAnswer)];
            const isOpen = openKey === key;

            return (
              <div
                key={key}
                className="rounded-xl border border-border bg-surface-2 overflow-hidden transition-colors"
              >
                <button
                  type="button"
                  onClick={() => setOpenKey(isOpen ? null : key)}
                  aria-expanded={isOpen}
                  className="w-full flex items-center justify-between gap-4 px-4 py-2.5 text-left cursor-pointer hover:bg-surface transition-colors"
                >
                  <span className="font-medium text-foreground">{question}</span>
                  <FiChevronDown
                    aria-hidden
                    className={`shrink-0 text-muted transition-transform duration-200 ${
                      isOpen ? "rotate-180 text-accent" : ""
                    }`}
                  />
                </button>
                <div
                  className={`grid transition-all duration-200 ${
                    isOpen ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
                  }`}
                >
                  <div className="overflow-hidden">
                    <div className="px-5 pb-3 space-y-1.5 text-sm text-muted leading-snug">
                      {answerItems.map((line, i) => (
                        <p key={i}>{line}</p>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <div className="mt-6 sm:mt-8 text-center">
          <Link
            href="/faq"
            className="inline-flex items-center gap-1.5 rounded-full border border-border px-6 py-2.5 font-semibold text-foreground hover:border-accent/60 hover:text-accent-strong transition-colors"
          >
            {t("home.faq.cta", { defaultValue: "Смотреть все вопросы" })}
          </Link>
        </div>
      </div>
    </section>
  );
}

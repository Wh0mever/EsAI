"use client";

import { useTranslation } from "react-i18next";
import { FiCheck, FiX } from "react-icons/fi";

/**
 * ChatGPTComparison — секция «Сравнение EsAI и ChatGPT» для главной страницы
 * (блок 4 из 8 в новой структуре лендинга). 4 пункта сравнения, текст
 * ДОСЛОВНО из ТЗ клиента (кроме esai-значения строки 2 — намеренно сокращено,
 * см. комментарий у ROWS). Наглядно в пользу EsAI: в каждой плитке сверху
 * приглушённое зачёркнутое значение ChatGPT с крестиком, снизу акцентное
 * значение EsAI с чекмарком.
 *
 * Статична (кроме i18n), поэтому не тянет данные с бэка — но помечена
 * "use client", потому что useTranslation требует клиентского рендера
 * (см. Footer.tsx / WhyEsAI.tsx — тот же паттерн в этом кодбейзе).
 *
 * Плотность по референсу клиента (старый грид быстрых действий чата):
 * ровно 2 колонки даже на узком мобильном (375px), компактный p-3,
 * умеренный gap. Раньше это была таблица из 2 колонок с общим заголовком
 * ("ChatGPT" / "EsAI"), которая на мобиле разваливалась в 8 стековых блоков
 * подряд — клиент попросил собрать всё в квадратики.
 *
 * Визуальный язык — как в pricing/CreditsExplainer.tsx и home/WhyEsAI.tsx:
 * rounded-2xl, border-border, bg-surface-2, text-muted, text-accent-strong.
 */

type Row = {
  chatgptKey: string;
  chatgptDefault: string;
  esaiKey: string;
  esaiDefault: string;
};

const ROWS: Row[] = [
  {
    chatgptKey: "home.comparison.rows.1.chatgpt",
    chatgptDefault: "Одна модель",
    esaiKey: "home.comparison.rows.1.esai",
    esaiDefault: "50+ моделей",
  },
  {
    chatgptKey: "home.comparison.rows.2.chatgpt",
    chatgptDefault: "Только GPT",
    esaiKey: "home.comparison.rows.2.esai",
    // Сокращено с полного списка ("...Gemini, Grok, DeepSeek, Veo, FLUX,
    // Kling и другие") — в узкой плитке 2-колоночной сетки (375px, колонка
    // ~167px) даже "GPT, Claude, Gemini и другие" уже давал 3 строки в
    // строке EsAI (префикс "EsAI: " + font-semibold text-sm). Смысл ("много
    // моделей от разных провайдеров") сохранён.
    esaiDefault: "GPT, Claude и другие",
  },
  {
    chatgptKey: "home.comparison.rows.3.chatgpt",
    chatgptDefault: "Одна подписка",
    esaiKey: "home.comparison.rows.3.esai",
    esaiDefault: "Один баланс на всё",
  },
  {
    chatgptKey: "home.comparison.rows.4.chatgpt",
    chatgptDefault: "Нужно выбирать сервис",
    esaiKey: "home.comparison.rows.4.esai",
    esaiDefault: "Всё в одном месте",
  },
];

export default function ChatGPTComparison() {
  const { t } = useTranslation("common");

  const labelChatgpt = t("home.comparison.col_chatgpt", { defaultValue: "ChatGPT" });
  const labelEsai = t("home.comparison.col_esai", { defaultValue: "EsAI" });

  return (
    <section
      aria-label={t("home.comparison.title", { defaultValue: "Сравнение EsAI и ChatGPT" })}
      className="w-full py-5 sm:py-6"
    >
      <div className="mx-auto max-w-4xl px-4 sm:px-6 lg:px-8">
        <h2 className="text-2xl sm:text-3xl font-bold text-foreground text-center mb-4 sm:mb-5">
          {t("home.comparison.title", { defaultValue: "Сравнение EsAI и ChatGPT" })}
        </h2>

        <div className="grid grid-cols-2 gap-2 sm:gap-3">
          {ROWS.map((row) => (
            <div
              key={row.chatgptKey}
              className="rounded-2xl border border-border bg-surface-2 p-3 flex flex-col gap-1.5"
            >
              {/* ChatGPT — приглушённо, зачёркнуто. */}
              <div className="flex items-start gap-1.5">
                <FiX className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-2" aria-hidden />
                <span className="text-xs text-muted line-through decoration-muted-2/60 leading-snug">
                  {labelChatgpt}: {t(row.chatgptKey, { defaultValue: row.chatgptDefault })}
                </span>
              </div>

              {/* EsAI — акцентно, крупнее и жирнее ChatGPT-строки. */}
              <div className="flex items-start gap-1.5">
                <FiCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent-strong" aria-hidden />
                <span className="text-sm font-semibold text-accent-strong leading-snug">
                  {labelEsai}: {t(row.esaiKey, { defaultValue: row.esaiDefault })}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

"use client";

import { useTranslation } from "react-i18next";
import { FiCheck, FiX } from "react-icons/fi";

/**
 * ChatGPTComparison — секция «Сравнение EsAI и ChatGPT» для главной страницы
 * (блок 4 из 8 в новой структуре лендинга). 4 строки, текст ДОСЛОВНО из ТЗ
 * клиента. Наглядно в пользу EsAI: колонка ChatGPT — приглушённая, с крестиком;
 * колонка EsAI — акцентная, с чекмарком.
 *
 * Статична (кроме i18n), поэтому не тянет данные с бэка — но помечена
 * "use client", потому что useTranslation требует клиентского рендера
 * (см. Footer.tsx / WhyEsAI.tsx — тот же паттерн в этом кодбейзе).
 *
 * Адаптив: на sm+ — классическая двухколоночная таблица с общим заголовком
 * колонок сверху. На мобиле заголовок колонок скрывается, каждая строка
 * превращается в карточку, где ячейки ChatGPT/EsAI стоят друг под другом со
 * своей мини-подписью (grid-cols-1 sm:grid-cols-2 на каждой строке).
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
    esaiDefault: "Более 50 моделей",
  },
  {
    chatgptKey: "home.comparison.rows.2.chatgpt",
    chatgptDefault: "Только GPT",
    esaiKey: "home.comparison.rows.2.esai",
    esaiDefault: "GPT, Claude, Gemini, Grok, DeepSeek, Veo, FLUX, Kling и другие",
  },
  {
    chatgptKey: "home.comparison.rows.3.chatgpt",
    chatgptDefault: "Одна подписка",
    esaiKey: "home.comparison.rows.3.esai",
    esaiDefault: "Один баланс для всех моделей",
  },
  {
    chatgptKey: "home.comparison.rows.4.chatgpt",
    chatgptDefault: "Нужно выбирать сервис",
    esaiKey: "home.comparison.rows.4.esai",
    esaiDefault: "Всё собрано в одном месте",
  },
];

export default function ChatGPTComparison() {
  const { t } = useTranslation("common");

  const colChatgpt = t("home.comparison.col_chatgpt", { defaultValue: "ChatGPT" });
  const colEsai = t("home.comparison.col_esai", { defaultValue: "EsAI" });

  return (
    <section
      aria-label={t("home.comparison.title", { defaultValue: "Сравнение EsAI и ChatGPT" })}
      className="w-full py-5 sm:py-6"
    >
      <div className="mx-auto max-w-4xl px-4 sm:px-6 lg:px-8">
        <h2 className="text-2xl sm:text-3xl font-bold text-foreground text-center mb-4 sm:mb-5">
          {t("home.comparison.title", { defaultValue: "Сравнение EsAI и ChatGPT" })}
        </h2>

        <div className="rounded-2xl border border-border bg-surface-2 overflow-hidden">
          {/* Column headers — visible from sm up, each row repeats them inline on mobile. */}
          <div className="hidden sm:grid grid-cols-2 border-b border-border">
            <div className="px-4 py-2 text-center text-sm font-semibold uppercase tracking-wide text-muted-2">
              {colChatgpt}
            </div>
            <div className="px-4 py-2 text-center text-sm font-semibold uppercase tracking-wide text-accent-strong bg-accent/10">
              {colEsai}
            </div>
          </div>

          <ul className="divide-y divide-border">
            {ROWS.map((row) => (
              <li key={row.chatgptKey} className="grid grid-cols-1 sm:grid-cols-2">
                {/* ChatGPT cell — muted, crossed out. */}
                <div className="flex items-start gap-3 px-4 py-2 sm:border-r border-border">
                  <FiX className="mt-0.5 h-4 w-4 shrink-0 text-muted-2" aria-hidden />
                  <div className="min-w-0">
                    <span className="sm:hidden block text-xs font-semibold uppercase tracking-wide text-muted-2 mb-1">
                      {colChatgpt}
                    </span>
                    <span className="text-muted line-through decoration-muted-2/60">
                      {t(row.chatgptKey, { defaultValue: row.chatgptDefault })}
                    </span>
                  </div>
                </div>

                {/* EsAI cell — accented, checked. */}
                <div className="flex items-start gap-3 px-4 py-2 bg-accent/[0.06]">
                  <FiCheck className="mt-0.5 h-4 w-4 shrink-0 text-accent-strong" aria-hidden />
                  <div className="min-w-0">
                    <span className="sm:hidden block text-xs font-semibold uppercase tracking-wide text-accent-strong mb-1">
                      {colEsai}
                    </span>
                    <span className="text-foreground font-medium">
                      {t(row.esaiKey, { defaultValue: row.esaiDefault })}
                    </span>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

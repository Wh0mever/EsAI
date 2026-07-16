"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { FiChevronDown } from "react-icons/fi";
import CreditsExplainer from "@/components/pricing/CreditsExplainer";
import { useCollapsibleHeight } from "@/hooks/useCollapsibleHeight";

/**
 * HomeCreditsExplainer — компактный блок «Как работают кредиты» для главной
 * страницы (блок 6 из ТЗ по 8 секциям). Текст — дословно от клиента.
 *
 * Детальная таблица стоимости моделей скрыта за раскрывающейся ссылкой
 * «Показать стоимость всех моделей» и переиспользует уже существующий
 * next/src/components/pricing/CreditsExplainer.tsx (та же таблица, что и на
 * /pricing) вместо дублирования fetch-логики. Компонент всегда смонтирован —
 * раскрытие/сворачивание чисто визуальное, поэтому данные успевают
 * подгрузиться из ai/models/ ещё до первого клика.
 *
 * Раскрытие анимируется через измеренный max-height (ref.scrollHeight), а не
 * через CSS-грид-трюк grid-template-rows: 0fr↔1fr. Тот трюк не раскрывал блок
 * визуально (computed height оставался 0 независимо от заданного значения),
 * хотя aria-expanded/JS-состояние переключались верно — воспроизведено и
 * подтверждено в браузере. Корень проблемы — сам элемент был flex-item
 * внутри родителя с display:flex (см. ниже, обёртка раньше была
 * "flex flex-col gap-6"): вложенность overflow-hidden-контейнера с
 * анимируемым размером в такой родитель ломала расчёт intrinsic-высоты.
 * Обёртку сменили на space-y-6 (обычный block-поток, без flex) — это убирает
 * первопричину; измеренный max-height оставлен как более надёжный способ
 * анимации раскрытия сам по себе (не зависит от grid/flex-контекста).
 * ResizeObserver подстраивает высоту, если таблица дозагрузится/изменится
 * уже после раскрытия (данные из ai/models/ приходят асинхронно).
 *
 * Сама логика измерения (scrollHeight + ResizeObserver) вынесена в общий
 * хук useCollapsibleHeight — им же пользуется /pricing
 * (CollapsibleCreditsExplainer), чтобы не держать две копии одного и того
 * же проверенного механизма.
 */
export default function HomeCreditsExplainer() {
  const { t } = useTranslation("common");
  const [open, setOpen] = useState(false);
  const { contentRef, maxHeight } = useCollapsibleHeight(open);

  return (
    <section aria-labelledby="home-credits-title" className="w-full">
      <div className="mx-auto max-w-4xl px-4 sm:px-6 py-5 sm:py-6 space-y-3">
        <div className="rounded-2xl border border-border bg-surface-2 p-4 md:p-5 flex flex-col gap-2.5">
          <h2 id="home-credits-title" className="text-2xl sm:text-3xl font-semibold text-foreground">
            {t("home.credits.title", { defaultValue: "Как работают кредиты" })}
          </h2>

          <p className="text-muted leading-relaxed max-w-2xl">
            {t("home.credits.body", {
              defaultValue:
                "Кредиты — это единая внутренняя валюта EsAI. Разные модели расходуют разное количество кредитов. После каждого запроса вы всегда видите, сколько кредитов было использовано.",
            })}
          </p>

          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            className="self-start inline-flex items-center gap-1.5 text-accent-strong hover:text-accent font-medium transition-colors cursor-pointer"
          >
            {open
              ? t("home.credits.hide", { defaultValue: "Скрыть стоимость всех моделей" })
              : t("home.credits.show", { defaultValue: "Показать стоимость всех моделей" })}
            <FiChevronDown
              aria-hidden
              className={`transition-transform duration-200 ${open ? "rotate-180" : ""}`}
            />
          </button>
        </div>

        {/* Раскрывающаяся детальная таблица — переиспользует CreditsExplainer напрямую. */}
        <div
          className="overflow-hidden transition-[max-height] duration-300 ease-in-out"
          style={{ maxHeight }}
        >
          <div ref={contentRef}>
            <CreditsExplainer />
          </div>
        </div>
      </div>
    </section>
  );
}

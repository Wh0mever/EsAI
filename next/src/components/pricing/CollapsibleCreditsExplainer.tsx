"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { FiChevronDown } from "react-icons/fi";
import CreditsExplainer from "@/components/pricing/CreditsExplainer";
import { useCollapsibleHeight } from "@/hooks/useCollapsibleHeight";

/**
 * CollapsibleCreditsExplainer — обёртка для /pricing по принципу ТЗ (не
 * выводить большую таблицу по умолчанию: короткое объяснение + ссылка
 * «Показать стоимость всех моделей», раскрывается по желанию). Раскрывает
 * существующий CreditsExplainer (та же таблица со всеми ~46 моделями, что
 * тянется из ai/models/), а не дублирует его разметку или fetch-логику.
 *
 * Использует тот же измеренный max-height механизм (scrollHeight +
 * ResizeObserver), что уже проверен в бою на главной странице
 * (home/HomeCreditsExplainer.tsx) — вынесен в общий хук
 * useCollapsibleHeight, никаких новых Tailwind-JIT рисков.
 *
 * Важно: внешний контейнер — обычный block-поток (space-y-3), НЕ
 * display:flex. Раскрывающийся overflow-hidden-блок как flex-item внутри
 * flex-родителя ломает расчёт intrinsic-высоты (max-height остаётся 0px
 * даже после раскрытия) — та же причина, из-за которой в
 * HomeCreditsExplainer.tsx обёртку в своё время сменили с "flex flex-col"
 * на space-y-6. Проверено вручную в браузере при разработке этого файла.
 */
export default function CollapsibleCreditsExplainer() {
  const { t } = useTranslation("common");
  const [open, setOpen] = useState(false);
  const { contentRef, maxHeight } = useCollapsibleHeight(open);

  return (
    <div className="lg:px-40 px-6 w-full space-y-3">
      <p className="text-muted max-w-2xl leading-relaxed">
        {t("packages.credits_teaser", {
          defaultValue:
            "Стоимость запроса зависит от модели: одни экономичнее, другие мощнее и расходуют больше кредитов за тот же объём текста.",
        })}
      </p>

      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 text-accent-strong hover:text-accent font-medium transition-colors cursor-pointer"
      >
        {open
          ? t("packages.credits_hide", { defaultValue: "Скрыть стоимость всех моделей" })
          : t("packages.credits_show", { defaultValue: "Показать стоимость всех моделей" })}
        <FiChevronDown
          aria-hidden
          className={`transition-transform duration-200 ${open ? "rotate-180" : ""}`}
        />
      </button>

      <div
        className="overflow-hidden transition-[max-height] duration-300 ease-in-out"
        style={{ maxHeight }}
      >
        <div ref={contentRef}>
          <CreditsExplainer />
        </div>
      </div>
    </div>
  );
}

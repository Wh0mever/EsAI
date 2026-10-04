"use client";

import { useTranslation } from "react-i18next";
import { FiBarChart2, FiDollarSign, FiGift, FiLink, FiPercent, FiTag, FiTrendingUp } from "react-icons/fi";

/** Преимущества программы (ТЗ п.2): семь карточек. */
export default function Benefits({ max }: { max: string }) {
  const { t } = useTranslation("creators", { useSuspense: false });

  const items = [
    {
      icon: FiPercent,
      text: t("public.benefits.commission", { defaultValue: "До {{max}}% постоянной комиссии", max }),
    },
    { icon: FiGift, text: t("public.benefits.credits", { defaultValue: "Creator Credits для создания контента" }) },
    { icon: FiLink, text: t("public.benefits.link", { defaultValue: "Персональная ссылка" }) },
    { icon: FiTag, text: t("public.benefits.promo", { defaultValue: "Персональный промокод" }) },
    { icon: FiBarChart2, text: t("public.benefits.stats", { defaultValue: "Подробная статистика" }) },
    { icon: FiDollarSign, text: t("public.benefits.usdt", { defaultValue: "Выплаты в USDT TRC20" }) },
    { icon: FiTrendingUp, text: t("public.benefits.level", { defaultValue: "Повышение уровня" }) },
  ];

  return (
    <section className="mx-auto max-w-5xl px-4 py-6 sm:py-8">
      <h2 className="sr-only">{t("public.benefits.title", { defaultValue: "Преимущества" })}</h2>
      {/* Первая карточка — главный довод — шире остальных: семь карточек ложатся ровно и в две, и в четыре колонки. */}
      <ul className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {items.map(({ icon: Icon, text }, i) => (
          <li
            key={i}
            className={`flex min-w-0 items-center gap-3 rounded-2xl border border-border bg-surface p-4 ${
              i === 0 ? "col-span-2" : "flex-col items-start sm:flex-row sm:items-center"
            }`}
          >
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-accent-soft">
              <Icon aria-hidden className="text-lg text-accent" />
            </span>
            <span className={`min-w-0 break-words font-semibold text-foreground ${i === 0 ? "text-base sm:text-lg" : "text-sm"}`}>
              {text}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

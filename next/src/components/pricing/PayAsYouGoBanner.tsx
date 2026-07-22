"use client";

import { useTranslation } from "react-i18next";
import { FiCheck } from "react-icons/fi";

/**
 * PAY-AS-YOU-GO banner — клиентский референс (скрин с другого сайта),
 * адаптированный под тёмную палитру EsAI. Ставится в самом начале /pricing,
 * ДО карточек пакетов (TokenPackages) — так просил клиент.
 *
 * Это единственный <h1> страницы /pricing — старую отдельную плашку
 * packages.subtitle/title/lead убрали из page.tsx как дублирующую по смыслу.
 */
export default function PayAsYouGoBanner() {
  const { t } = useTranslation("common");

  const checks = [
    t("packages.payg_check_no_subscription", { defaultValue: "Без подписок" }),
    t("packages.payg_check_no_hidden_fees", { defaultValue: "Без скрытых платежей" }),
    t("packages.payg_check_starts_from", { defaultValue: "Старт от 190 сом" }),
  ];

  return (
    <div className="flex flex-col items-center gap-2 text-center px-4 pb-2">
      <span className="px-3 py-1 rounded-full bg-accent/15 border border-accent/30 text-[11px] font-bold tracking-wider text-accent-strong uppercase">
        {t("packages.payg_badge", { defaultValue: "PAY-AS-YOU-GO" })}
      </span>

      <h1 className="text-2xl sm:text-3xl font-bold max-w-2xl">
        {t("packages.payg_title", {
          defaultValue: "Никаких подписок. Платите только за то, что используете.",
        })}
      </h1>

      <p className="text-muted text-sm sm:text-base max-w-xl">
        {t("packages.payg_subtitle", {
          defaultValue:
            "Пополняете баланс — и тратите его только на реальное использование нейросетей. Не пользуетесь — ничего не списываем.",
        })}
      </p>

      <div className="flex flex-wrap items-center justify-center gap-2 mt-1">
        {checks.map((label) => (
          <span
            key={label}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-surface-2 border border-border text-xs sm:text-sm font-medium text-foreground"
          >
            <FiCheck className="text-accent-strong shrink-0" size={14} />
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}

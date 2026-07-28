"use client";

import { useTranslation } from "react-i18next";
import type { IconType } from "react-icons";
import { FiGrid, FiUser, FiCreditCard, FiTarget, FiZap, FiSmartphone } from "react-icons/fi";

/**
 * WhyEsAI — секция «Почему EsAI» для главной страницы (блок 2 из 8 в новой
 * структуре лендинга). 6 карточек, текст ДОСЛОВНО из ТЗ клиента.
 *
 * Статична (кроме i18n), поэтому не тянет данные с бэка — но помечена
 * "use client", потому что useTranslation требует клиентского рендера
 * (см. Footer.tsx / TokenPackages.tsx — тот же паттерн в этом кодбейзе).
 *
 * Визуальный язык — как в pricing/CreditsExplainer.tsx и pricing/TokenPackages.tsx:
 * rounded-2xl, border-border, bg-surface/bg-surface-2, text-muted, bg-accent/15.
 */

type WhyCard = {
  icon: IconType;
  titleKey: string;
  titleDefault: string;
  descKey: string;
  descDefault: string;
};

const CARDS: WhyCard[] = [
  {
    icon: FiGrid,
    titleKey: "home.why.items.1.title",
    titleDefault: "50+ AI-моделей",
    descKey: "home.why.items.1.desc",
    descDefault: "Без ограничений одной нейросетью",
  },
  {
    icon: FiUser,
    titleKey: "home.why.items.2.title",
    titleDefault: "Один аккаунт",
    descKey: "home.why.items.2.desc",
    descDefault: "Один интерфейс для всех",
  },
  {
    icon: FiCreditCard,
    titleKey: "home.why.items.3.title",
    titleDefault: "Один баланс",
    descKey: "home.why.items.3.desc",
    descDefault: "Не платите за каждый сервис отдельно",
  },
  {
    icon: FiTarget,
    titleKey: "home.why.items.4.title",
    titleDefault: "Модель под задачу",
    descKey: "home.why.items.4.desc",
    descDefault: "Мы подскажем, какую выбрать",
  },
  {
    icon: FiZap,
    titleKey: "home.why.items.5.title",
    titleDefault: "Новинки сразу",
    descKey: "home.why.items.5.desc",
    descDefault: "Без ожидания и обновлений",
  },
  {
    icon: FiSmartphone,
    titleKey: "home.why.items.6.title",
    titleDefault: "Удобная оплата",
    descKey: "home.why.items.6.desc",
    descDefault: "Visa, Mastercard и кошельки Кыргызстана",
  },
];

export default function WhyEsAI() {
  const { t } = useTranslation("common");

  return (
    <section aria-label={t("home.why.title", { defaultValue: "Почему EsAI" })} className="w-full py-5 sm:py-6">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <h2 className="text-2xl sm:text-3xl font-bold text-foreground text-center mb-4 sm:mb-5">
          {t("home.why.title", { defaultValue: "Почему EsAI" })}
        </h2>

        <div className="grid grid-cols-2 lg:grid-cols-3 gap-2 sm:gap-3">
          {CARDS.map((card) => {
            const Icon = card.icon;
            return (
              <div
                key={card.titleKey}
                className="rounded-2xl border border-border bg-surface-2 p-3 flex flex-col gap-1.5"
              >
                <div className="h-8 w-8 sm:h-9 sm:w-9 rounded-xl bg-accent/15 text-accent-strong flex items-center justify-center">
                  <Icon size={16} aria-hidden />
                </div>
                <h3 className="text-sm sm:text-base font-bold text-foreground leading-snug">
                  {t(card.titleKey, { defaultValue: card.titleDefault })}
                </h3>
                <p className="text-xs sm:text-sm text-muted leading-snug">
                  {t(card.descKey, { defaultValue: card.descDefault })}
                </p>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

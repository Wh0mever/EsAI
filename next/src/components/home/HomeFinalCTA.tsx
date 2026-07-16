"use client";

import Link from "next/link";
import { useTranslation } from "react-i18next";
import { FiArrowRight } from "react-icons/fi";

/**
 * HomeFinalCTA — блок 8 ("Регистрация / начало работы") — последний акцентный
 * блок на главной странице, перед существующей SEO-статьёй (HomeArticleSection)
 * и Footer (их не трогаем).
 *
 * Простой, сильный призыв к действию в духе Hero-блока: тот же текст кнопки
 * ("Начать бесплатно") и тот же href. В EsAI нет отдельной формы регистрации —
 * аккаунт создаётся автоматически при первом входе через email-OTP или
 * соц-кнопки на /auth/signin (next/src/app/auth/signup/page.tsx лишь
 * редиректит туда же, см. next/src/components/chat/ChatWorkspace.tsx, где
 * гостевая ссылка "Войти" ведёт туда же).
 */
export default function HomeFinalCTA() {
  const { t } = useTranslation("common");

  return (
    <section
      aria-label={t("home.finalCta.aria", { defaultValue: "Начать работу с EsAI" })}
      className="border-t border-border bg-background"
    >
      <div className="mx-auto max-w-5xl px-4 py-5 sm:py-6">
        <div className="relative overflow-hidden rounded-3xl border border-border bg-surface-2 px-6 py-5 sm:px-8 sm:py-6 text-center">
          {/* Декоративное свечение брендовым акцентом — без новых цветовых токенов. */}
          <div
            aria-hidden
            className="pointer-events-none absolute -top-16 left-1/2 h-48 w-[28rem] -translate-x-1/2 rounded-full bg-accent/20 blur-3xl"
          />

          <div className="relative flex flex-col items-center gap-3 sm:gap-4">
            <div className="flex w-full flex-col items-center gap-2 text-center sm:flex-row sm:items-center sm:justify-between sm:gap-6 sm:text-left">
              <h2 className="max-w-2xl text-xl font-bold leading-tight text-foreground sm:text-2xl md:text-3xl">
                {t("home.finalCta.title", { defaultValue: "Начните бесплатно, прямо сейчас" })}
              </h2>

              <p className="max-w-xl text-base text-muted sm:text-lg">
                {t("home.finalCta.subtitle", {
                  defaultValue:
                    "Один аккаунт, один баланс — и десятки лучших нейросетей мира. Без переключений между сервисами.",
                })}
              </p>
            </div>

            <Link
              href="/auth/signin"
              className="mt-1 inline-flex items-center gap-2 rounded-full bg-accent px-7 py-3 text-base font-semibold text-on-accent transition-colors hover:bg-accent-strong sm:text-lg"
            >
              {t("home.finalCta.cta", { defaultValue: "Начать бесплатно" })}
              <FiArrowRight aria-hidden />
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

"use client";

import { useTranslation } from "react-i18next";

/** «Как это работает» (ТЗ п.3): шесть шагов от заявки до заработка. */
export default function HowItWorks() {
  const { t } = useTranslation("creators", { useSuspense: false });

  const steps = [
    {
      title: t("public.how.step1_title", { defaultValue: "Подайте заявку" }),
      text: t("public.how.step1_text", { defaultValue: "Расскажите о себе и укажите свои соцсети." }),
    },
    {
      title: t("public.how.step2_title", { defaultValue: "Мы рассмотрим заявку" }),
      text: t("public.how.step2_text", { defaultValue: "Все участники проходят ручную проверку." }),
    },
    {
      title: t("public.how.step3_title", { defaultValue: "Получите уровень и партнёрскую ссылку" }),
      text: t("public.how.step3_text", { defaultValue: "После одобрения вы получаете персональный кабинет." }),
    },
    {
      title: t("public.how.step4_title", { defaultValue: "Создавайте контент" }),
      text: t("public.how.step4_text", {
        defaultValue: "Используйте EsAI для создания видео, мультфильмов и другого контента.",
      }),
    },
    {
      title: t("public.how.step5_title", { defaultValue: "Приводите аудиторию" }),
      text: t("public.how.step5_text", { defaultValue: "Используйте свою персональную ссылку или промокод." }),
    },
    {
      title: t("public.how.step6_title", { defaultValue: "Зарабатывайте" }),
      text: t("public.how.step6_text", {
        defaultValue: "Получайте постоянную комиссию с платежей пользователей, которых вы привели.",
      }),
    },
  ];

  return (
    <section className="mx-auto max-w-5xl px-4 py-8 sm:py-10">
      <h2 className="text-center text-2xl font-bold text-foreground sm:text-3xl">
        {t("public.how.title", { defaultValue: "Как это работает" })}
      </h2>
      <ol className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {steps.map((step, i) => (
          <li key={i} className="flex min-w-0 gap-3 rounded-2xl border border-border bg-surface p-4 sm:p-5">
            <span
              aria-hidden
              className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-accent text-sm font-bold tabular-nums text-on-accent"
            >
              {i + 1}
            </span>
            <div className="min-w-0">
              <h3 className="break-words font-semibold text-foreground">{step.title}</h3>
              <p className="mt-1 break-words text-sm text-muted">{step.text}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

"use client";

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

type Props = {
  /** Наибольший процент комиссии среди уровней — «до {{max}}%». */
  max: string;
  /** Главное действие: кнопка или карточка статуса (ApplyCta). */
  children: ReactNode;
};

/** Первый экран страницы программы (ТЗ п.2): заголовок, подзаголовок и главное действие. */
export default function Hero({ max, children }: Props) {
  const { t } = useTranslation("creators", { useSuspense: false });

  return (
    <section className="relative isolate px-4 pb-10 pt-28 sm:pb-14 sm:pt-36">
      {/* Мягкое свечение фирменного цвета: без картинок, одинаково уместно в обеих темах. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[26rem] bg-[radial-gradient(60%_60%_at_50%_0%,var(--accent-soft),transparent_70%)]"
      />
      <div className="mx-auto flex max-w-3xl flex-col items-center text-center">
        <span className="rounded-full border border-border bg-surface px-3 py-1 text-xs font-semibold uppercase tracking-wider text-accent">
          EsAI Creators
        </span>
        <h1 className="mt-4 text-balance break-words text-3xl font-bold leading-tight text-foreground sm:text-5xl">
          {t("public.hero.title", { defaultValue: "Создавайте с EsAI. Зарабатывайте на своей аудитории." })}
        </h1>
        <p className="mt-4 max-w-2xl text-balance text-base text-muted sm:text-lg">
          {t("public.hero.sub", {
            defaultValue: "Получайте до {{max}}% с каждого платежа привлечённых пользователей — постоянно.",
            max,
          })}
        </p>
        <div className="mt-7 flex w-full justify-center">{children}</div>
      </div>
    </section>
  );
}

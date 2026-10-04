"use client";

import Link from "next/link";
import { useTranslation } from "react-i18next";
import { errorText } from "@/lib/creators/errors";

/**
 * Программа выключена для этого человека (API ответил 404 disabled): вместо
 * страницы — короткая карточка со ссылкой на главную. Причину не уточняем:
 * в режиме «только сотрудники» посетителю незачем знать, что раздел есть.
 */
export default function CreatorsUnavailable({ className = "" }: { className?: string }) {
  const { t } = useTranslation("creators", { useSuspense: false });

  return (
    <section className={`mx-auto flex min-h-[70dvh] w-full max-w-md items-center px-4 pb-16 pt-28 ${className}`}>
      <div className="w-full rounded-2xl border border-border bg-surface p-6 text-center">
        <h1 className="text-xl font-bold text-foreground">EsAI Creators</h1>
        <p className="mt-2 text-sm text-muted">{errorText(t, { code: "disabled" })}</p>
        <Link
          href="/"
          className="mt-5 inline-flex items-center justify-center rounded-xl bg-accent px-5 py-2.5 text-sm font-semibold text-on-accent transition-colors hover:bg-accent-strong"
        >
          {t("common.home", { defaultValue: "На главную" })}
        </Link>
      </div>
    </section>
  );
}

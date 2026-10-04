"use client";

import { useTranslation } from "react-i18next";
import { errorText } from "@/lib/creators/errors";
import type { CrError } from "@/lib/creators/types";

type Props = {
  error: CrError;
  /** Есть — рядом с текстом кнопка «Повторить». */
  onRetry?: () => void;
  /** Подстановки для текста (например min для amount_below_min). */
  params?: Record<string, string | number>;
  className?: string;
};

/**
 * Ошибка API на языке интерфейса: текст берётся по коду (errors.ts), а не из
 * ответа сервера — тот только русский.
 */
export default function ErrorNote({ error, onRetry, params, className = "" }: Props) {
  const { t } = useTranslation("creators", { useSuspense: false });

  return (
    <div
      role="alert"
      className={`flex flex-wrap items-center justify-between gap-2 rounded-xl border border-status-fail/40 bg-status-fail/10 px-3 py-2 text-sm text-foreground ${className}`}
    >
      <span className="min-w-0 break-words">{errorText(t, error, params)}</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 cursor-pointer rounded-lg border border-border bg-surface px-3 py-1.5 text-xs font-semibold text-foreground transition-colors hover:border-accent"
        >
          {t("common.retry", { defaultValue: "Повторить" })}
        </button>
      )}
    </div>
  );
}

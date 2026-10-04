/**
 * EsAI Creators, публичная страница: общие классы кнопок и адреса.
 * Цвета — только токены темы, поэтому страница читается и в светлой, и в тёмной.
 */

/** Главная кнопка страницы (жёлтая). */
export const BTN_PRIMARY =
  "inline-flex min-h-12 cursor-pointer items-center justify-center gap-2 rounded-xl bg-accent px-6 py-3 text-center text-sm font-bold tracking-wide text-on-accent transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-60";

/** Второстепенная кнопка (контур). */
export const BTN_SECONDARY =
  "inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-xl border border-border bg-surface px-5 py-2.5 text-center text-sm font-semibold text-foreground transition-colors hover:border-accent disabled:cursor-not-allowed disabled:opacity-60";

/** Карточка раздела. */
export const CARD = "rounded-2xl border border-border bg-surface p-4 sm:p-6";

/** Гостя ведём на вход с возвратом прямо в форму заявки. */
export const SIGNIN_TO_APPLY = "/auth/signin?next=%2Fcreators%3Fapply%3D1";

export const DASHBOARD_URL = "/creators/dashboard";

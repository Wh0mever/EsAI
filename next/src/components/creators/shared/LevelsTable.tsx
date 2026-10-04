"use client";

import { useTranslation } from "react-i18next";
import { fmtInt, fmtPercent } from "@/lib/creators/format";
import type { LevelRow } from "@/lib/creators/types";

type Props = {
  levels: LevelRow[];
  /** Уровень самого креатора — его строка подсвечена и подписана «Ваш уровень». */
  currentKey?: string | null;
};

/**
 * Уровни программы: комиссия и пороги (ТЗ п.4–5). Названия уровней приходят с
 * сервера и не переводятся. Порог 0 — условия нет, показываем «—».
 *
 * Пороги — только ориентир: уровень повышает администратор, не система.
 * На телефоне каждая строка — карточка: таблица из пяти колонок в 360 px не
 * помещается, а горизонтальной прокрутки на страницах программы быть не должно.
 */
export default function LevelsTable({ levels, currentKey }: Props) {
  const { t, i18n } = useTranslation("creators", { useSuspense: false });
  const rows = [...levels].sort((a, b) => a.sort - b.sort);
  const need = (n: number) => (n > 0 ? fmtInt(n, i18n.language) : "—");

  const head = {
    level: t("levels.col_level", { defaultValue: "Уровень" }),
    percent: t("levels.col_percent", { defaultValue: "Комиссия" }),
    publications: t("levels.col_publications", { defaultValue: "Публикации" }),
    registrations: t("levels.col_registrations", { defaultValue: "Регистрации" }),
    paying: t("levels.col_paying", { defaultValue: "Платящие пользователи" }),
  };
  const yours = t("levels.current", { defaultValue: "Ваш уровень" });

  const badge = (
    <span className="inline-flex items-center rounded-full bg-accent px-2 py-0.5 text-[11px] font-semibold text-on-accent">
      {yours}
    </span>
  );

  return (
    <div>
      {/* Телефон: карточки */}
      <ul className="flex flex-col gap-2 sm:hidden">
        {rows.map((level) => {
          const current = level.key === currentKey;
          return (
            <li
              key={level.key}
              aria-current={current ? "true" : undefined}
              className={`rounded-2xl border p-4 ${current ? "border-accent bg-accent-soft" : "border-border bg-surface"}`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="break-words font-semibold text-foreground">{level.title}</div>
                  {current && <div className="mt-1">{badge}</div>}
                </div>
                <div className="shrink-0 text-right">
                  <div className="text-xl font-bold tabular-nums text-foreground">{fmtPercent(level.percent)}%</div>
                  <div className="text-[11px] text-muted">{head.percent}</div>
                </div>
              </div>
              <dl className="mt-3 grid grid-cols-3 gap-2 border-t border-border pt-3">
                {(
                  [
                    [head.publications, level.min_publications],
                    [head.registrations, level.min_registrations],
                    [head.paying, level.min_paying],
                  ] as const
                ).map(([label, value]) => (
                  // В разметке подпись идёт первой (так положено в dl), на экране — число сверху.
                  <div key={label} className="flex min-w-0 flex-col-reverse justify-end">
                    <dt className="break-words text-[11px] leading-tight text-muted">{label}</dt>
                    <dd className="text-sm font-semibold tabular-nums text-foreground">{need(value)}</dd>
                  </div>
                ))}
              </dl>
            </li>
          );
        })}
      </ul>

      {/* Планшет и шире: таблица */}
      <div className="hidden overflow-hidden rounded-2xl border border-border bg-surface sm:block">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted">
              <th scope="col" className="px-4 py-3 font-medium">{head.level}</th>
              <th scope="col" className="px-4 py-3 text-right font-medium">{head.percent}</th>
              <th scope="col" className="px-4 py-3 text-right font-medium">{head.publications}</th>
              <th scope="col" className="px-4 py-3 text-right font-medium">{head.registrations}</th>
              <th scope="col" className="px-4 py-3 text-right font-medium">{head.paying}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((level) => {
              const current = level.key === currentKey;
              return (
                <tr
                  key={level.key}
                  aria-current={current ? "true" : undefined}
                  className={`border-b border-border last:border-b-0 ${current ? "bg-accent-soft" : ""}`}
                >
                  <th scope="row" className="px-4 py-3 text-left font-semibold text-foreground">
                    <span className="flex flex-wrap items-center gap-2">
                      {level.title}
                      {current && badge}
                    </span>
                  </th>
                  <td className="px-4 py-3 text-right font-semibold tabular-nums text-foreground">
                    {fmtPercent(level.percent)}%
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-foreground">{need(level.min_publications)}</td>
                  <td className="px-4 py-3 text-right tabular-nums text-foreground">{need(level.min_registrations)}</td>
                  <td className="px-4 py-3 text-right tabular-nums text-foreground">{need(level.min_paying)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

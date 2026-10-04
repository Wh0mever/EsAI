"use client";

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import Money from "@/components/creators/shared/Money";
import { fmtInt, fmtPercent, fmtUsdt } from "@/lib/creators/format";
import type { CodeCreated, Me, Part } from "@/lib/creators/types";
import CodeLink from "./CodeLink";
import CreateCode from "./CreateCode";

type Props = {
  me: Me;
  /** Креатор заблокирован: всё видно, но ничего нельзя создать. */
  blocked: boolean;
  justCreated: boolean;
  onCodeCreated: (created: CodeCreated) => void;
  onReload: () => void;
};

/**
 * Первый экран кабинета (ТЗ п.13–15, 37–38). На телефоне 360 × 640 без
 * прокрутки видны все десять пунктов п.37: уровень, процент, заработок,
 * доступно к выводу, переходы, регистрации, платящие, прогресс, промокод и
 * ссылка. Поэтому блоки плотные, с заданной высотой строк, без обложки.
 *
 * Все цифры — как их прислал сервер: страница ничего не считает и уровень не
 * меняет. Кнопки «повысить уровень» нет — решение принимает администратор.
 */
export default function FirstScreen({ me, blocked, justCreated, onCodeCreated, onReload }: Props) {
  const { t, i18n } = useTranslation("creators", { useSuspense: false });
  const lang = i18n.language;
  const { money, counters, progress, level } = me;

  return (
    <div className="flex flex-col gap-1.5">
      {/* A. Уровень и процент комиссии */}
      <div className="flex flex-wrap items-baseline justify-between gap-x-2 rounded-xl border border-accent/40 bg-accent-soft px-2.5 py-1 text-[11px] leading-5 text-foreground sm:px-3.5 sm:py-2 sm:text-sm">
        <span>
          {t("dash.level.yours", { defaultValue: "Ваш уровень" })}:{" "}
          <b className="text-[13px] font-bold sm:text-base">{level.title}</b>
        </span>
        <span>
          {t("dash.level.commission", { defaultValue: "Ваша комиссия" })}:{" "}
          <b className="text-[13px] font-bold tabular-nums sm:text-base">{fmtPercent(level.percent)}%</b>
        </span>
      </div>

      {/* B. Промокод и ссылка — или форма создания промокода */}
      {me.code && me.link ? (
        <CodeLink code={me.code} link={me.link} justCreated={justCreated} />
      ) : blocked ? (
        <div className="rounded-2xl border border-border bg-surface px-3 py-2 text-sm text-muted">
          {t("dash.code.none", { defaultValue: "Промокод не создан." })}
        </div>
      ) : (
        <CreateCode onCreated={onCodeCreated} onReload={onReload} />
      )}

      {/*
        C. Заработок. На телефоне крупно — два числа из п.37, остальные два —
        строкой под плитками (иначе десять пунктов не поместятся на первый
        экран; крупно они стоят в «Обзоре»). С ширины sm все счётчики п.14 —
        плитками, строка скрыта.
      */}
      <div>
        <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4 sm:gap-2">
          <Tile label={t("dash.money.earned", { defaultValue: "Заработано всего" })}>
            <Usdt value={money.earned} />
          </Tile>
          <Tile label={t("dash.money.available", { defaultValue: "Доступно к выводу" })} accent>
            <Usdt value={money.available} />
          </Tile>
          <Tile label={t("dash.money.pending", { defaultValue: "Ожидает выплаты" })} wideOnly>
            <Usdt value={money.pending} />
          </Tile>
          <Tile label={t("dash.money.paid", { defaultValue: "Выплачено" })} wideOnly>
            <Usdt value={money.paid} />
          </Tile>
        </div>
        <p className="mt-1 px-0.5 text-[10.5px] leading-[14px] text-muted sm:hidden">
          {t("dash.money.line", {
            defaultValue: "Ожидает выплаты {{pending}} USDT · Выплачено {{paid}} USDT",
            pending: fmtUsdt(money.pending),
            paid: fmtUsdt(money.paid),
          })}
        </p>
      </div>

      {/* D. Результаты: то же самое — «Продажи» и «Заказы» плитками с ширины sm. */}
      <div>
        <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-[1fr_1fr_1fr_1.6fr_1fr] sm:gap-2">
          <Tile label={t("dash.results.clicks", { defaultValue: "Переходы" })} valueFirst>
            {fmtInt(counters.clicks, lang)}
          </Tile>
          <Tile label={t("dash.results.registrations", { defaultValue: "Регистрации" })} valueFirst>
            {fmtInt(counters.registrations, lang)}
          </Tile>
          <Tile label={t("dash.results.paying", { defaultValue: "Платящие пользователи" })} valueFirst>
            {fmtInt(counters.paying, lang)}
          </Tile>
          <Tile label={t("dash.results.sales", { defaultValue: "Продажи" })} valueFirst wideOnly>
            <Usdt value={counters.sales_usdt} />
          </Tile>
          <Tile label={t("dash.results.orders", { defaultValue: "Заказы" })} valueFirst wideOnly>
            {fmtInt(counters.orders, lang)}
          </Tile>
        </div>
        <p className="mt-1 px-0.5 text-[10.5px] leading-[14px] text-muted sm:hidden">
          {t("dash.results.line", {
            defaultValue: "Продажи {{sales}} USDT · Заказы {{orders}}",
            sales: fmtUsdt(counters.sales_usdt),
            orders: fmtInt(counters.orders, lang),
          })}
        </p>
      </div>

      {/* E. Прогресс до следующего уровня */}
      <section className="rounded-2xl border border-border bg-surface px-2.5 py-1.5">
        {progress.next_level ? (
          <>
            <div className="text-[12.5px] leading-[18px] text-foreground">
              {t("dash.progress.to", { defaultValue: "До" })}:{" "}
              <b className="font-bold">
                {progress.next_level.title} — {fmtPercent(progress.next_level.percent)}%
              </b>
            </div>
            <div className="mt-1 grid grid-cols-3 gap-1.5">
              <Chip
                label={t("dash.progress.publications", { defaultValue: "Публикации" })}
                part={progress.publications}
                lang={lang}
              />
              <Chip
                label={t("dash.progress.registrations", { defaultValue: "Регистрации" })}
                part={progress.registrations}
                lang={lang}
              />
              <Chip
                label={t("dash.progress.paying", { defaultValue: "Платящие пользователи" })}
                part={progress.paying}
                lang={lang}
              />
            </div>
            {progress.conditions_met && (
              <p className="mt-1 text-[11.5px] font-medium leading-4 text-status-ok">
                {t("dash.progress.met", { defaultValue: "Условия выполнены. Ожидает подтверждения EsAI." })}
              </p>
            )}
          </>
        ) : (
          <p className="text-[12.5px] leading-[18px] text-foreground">
            {t("dash.progress.max", { defaultValue: "У вас максимальный уровень." })}
          </p>
        )}
      </section>
    </div>
  );
}

/**
 * Плитка счётчика: подпись и крупное число. valueFirst — число сверху (узкие
 * плитки). wideOnly — плитка только с ширины sm: на телефоне этот счётчик
 * стоит в строке под плитками.
 */
export function Tile({
  label,
  children,
  accent = false,
  valueFirst = false,
  wideOnly = false,
}: {
  label: string;
  children: ReactNode;
  accent?: boolean;
  valueFirst?: boolean;
  wideOnly?: boolean;
}) {
  return (
    <div
      className={`${wideOnly ? "hidden sm:flex" : "flex"} min-w-0 rounded-xl border bg-surface px-2.5 py-1.5 sm:px-3 sm:py-2.5 ${
        accent ? "border-accent/50" : "border-border"
      } ${valueFirst ? "flex-col-reverse justify-end" : "flex-col"}`}
    >
      {/* В разметке подпись первой, на экране в узких плитках — число сверху. */}
      <div
        className={`break-words text-[10.5px] text-muted sm:text-xs sm:leading-4 ${
          valueFirst ? "leading-[13px]" : "leading-[14px]"
        }`}
      >
        {label}
      </div>
      <div className="break-words text-[17px] font-bold leading-6 tabular-nums text-foreground sm:text-lg sm:leading-7 lg:text-xl">
        {children}
      </div>
    </div>
  );
}

/** Сумма в плитке: число крупно, «USDT» мелко — иначе длинная сумма не влезет в 360 px. */
export function Usdt({ value }: { value: string }) {
  return (
    <>
      <Money value={value} unit={false} /> <span className="text-[10.5px] font-medium text-muted">USDT</span>
    </>
  );
}

/** Условие уровня: «Публикации 17 / 25», галочка, когда выполнено, и тонкая полоса. */
function Chip({ label, part, lang }: { label: string; part: Part; lang: string }) {
  const { t } = useTranslation("creators", { useSuspense: false });
  // Доля для полосы — счётчики, не деньги; больше 100 % не рисуем.
  const share = part.need > 0 ? Math.min(100, Math.max(0, (part.have / part.need) * 100)) : 100;

  return (
    <div className="flex min-w-0 flex-col">
      <div className="flex min-h-[26px] items-end break-words text-[10.5px] leading-[13px] text-muted">{label}</div>
      <div className="text-[13px] font-semibold leading-[18px] tabular-nums text-foreground">
        {fmtInt(part.have, lang)} / {fmtInt(part.need, lang)}
        {part.done && (
          <span className="ml-1 text-status-ok" role="img" aria-label={t("dash.progress.done", { defaultValue: "выполнено" })}>
            ✓
          </span>
        )}
      </div>
      <div className="mt-1 h-[3px] overflow-hidden rounded-full bg-surface-3">
        <div
          className={`h-full rounded-full ${part.done ? "bg-status-ok" : "bg-accent"}`}
          style={{ width: `${share}%` }}
        />
      </div>
    </div>
  );
}

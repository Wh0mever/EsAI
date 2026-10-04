"use client";

import { useTranslation } from "react-i18next";
import LevelsTable from "@/components/creators/shared/LevelsTable";
import { fmtPercent, fmtUsdt } from "@/lib/creators/format";
import type { LevelRow, Program } from "@/lib/creators/types";
import { CARD } from "./ui";

const SECTION = "mx-auto max-w-5xl px-4 py-8 sm:py-10";
const TITLE = "text-center text-2xl font-bold text-foreground sm:text-3xl";
const TEXT = "mx-auto mt-5 max-w-3xl break-words text-sm leading-relaxed text-muted sm:text-base";

/**
 * «Комиссия» (ТЗ п.4): четыре уровня и процент каждого. Названия уровней и
 * проценты приходят с сервера — администратор может их менять.
 */
export function CommissionSection({ levels }: { levels: LevelRow[] }) {
  const { t } = useTranslation("creators", { useSuspense: false });
  const rows = [...levels].sort((a, b) => a.sort - b.sort);

  return (
    <section className={SECTION}>
      <h2 className={TITLE}>{t("public.commission.title", { defaultValue: "Комиссия" })}</h2>
      {rows.length > 0 && (
        <ul className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
          {rows.map((level) => (
            <li key={level.key} className="flex min-w-0 flex-col gap-1 rounded-2xl border border-border bg-surface p-4">
              <span className="text-3xl font-bold tabular-nums text-accent">{fmtPercent(level.percent)}%</span>
              <span className="break-words text-xs font-semibold uppercase tracking-wide text-foreground sm:text-sm">
                {level.title}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className={TEXT}>
        {t("public.commission.text", {
          defaultValue:
            "Комиссия постоянная: вы получаете свой процент не только с первой покупки, но и со всех последующих оплаченных заказов привлечённого пользователя. Комиссия действует, пока существует реферальная связь и аккаунт креатора не заблокирован.",
        })}
      </p>
    </section>
  );
}

/**
 * «Условия повышения уровня» (ТЗ п.5): пороги по публикациям, регистрациям и
 * платящим. Пороги — только ориентир: уровень повышает администратор.
 */
export function LevelConditionsSection({ levels }: { levels: LevelRow[] }) {
  const { t } = useTranslation("creators", { useSuspense: false });

  return (
    <section className={SECTION}>
      <h2 className={TITLE}>{t("public.levels.title", { defaultValue: "Условия повышения уровня" })}</h2>
      {levels.length > 0 && (
        <div className="mt-6">
          <LevelsTable levels={levels} />
        </div>
      )}
      <p className={TEXT}>
        {t("public.levels.text", {
          defaultValue:
            "Показатели считаются за весь срок работы, а не за месяц. Когда показатели достигнуты, в кабинете появляется отметка «Условия уровня выполнены». Повышение не автоматическое — окончательное решение принимает администратор EsAI.",
        })}
      </p>
    </section>
  );
}

/** Русский текст о сроке холда: «через 1 день», «через 3 дня», «через 14 дней». */
function holdRu(days: number): string {
  const form = new Intl.PluralRules("ru").select(days);
  const word = form === "one" ? "день" : form === "many" ? "дней" : "дня";
  return `Комиссия становится доступной к выводу через {{count}} ${word} после начисления.`;
}

/** «Выплаты» (ТЗ п.23–27): только USDT TRC20, минимум, без комиссии с креатора, холд. */
export function PayoutsSection({ program }: { program: Pick<Program, "network" | "min_payout_usdt" | "hold_days"> }) {
  const { t } = useTranslation("creators", { useSuspense: false });
  const days = Number(program.hold_days);

  return (
    <section className={SECTION}>
      <h2 className={TITLE}>{t("public.payouts.title", { defaultValue: "Выплаты" })}</h2>
      <div className={`${CARD} mx-auto mt-6 max-w-3xl`}>
        <ul className="flex flex-col gap-3 break-words text-sm leading-relaxed text-foreground sm:text-base">
          <li>
            {t("public.payouts.main", {
              defaultValue:
                "Выплаты — только в USDT, сеть {{network}}. Минимальная сумма вывода — {{min}} USDT. Комиссия с выплаты не удерживается: запросили 50 USDT — получили 50 USDT.",
              network: program.network || "TRC20",
              // Сумма — строкой, как её прислал сервер.
              min: fmtUsdt(program.min_payout_usdt),
            })}
          </li>
          {/* Холд 0 дней — комиссия доступна сразу, и фраза «через 0 дней» только путала бы. */}
          {Number.isFinite(days) && days > 0 && (
            <li>
              {/* Срок задаёт администратор (до 90 дней) — слово «день» согласуется с числом. */}
              {t("public.payouts.hold", { count: days, defaultValue: holdRu(days) })}
            </li>
          )}
          <li>{t("public.payouts.no_tariff", { defaultValue: "Покупать тариф для участия не нужно." })}</li>
        </ul>
      </div>
    </section>
  );
}

"use client";

import { useTranslation } from "react-i18next";
import CopyField from "@/components/ui/CopyField";
import { cmpDec, fmtInt, fmtUsdt } from "@/lib/creators/format";
import type { Me } from "@/lib/creators/types";
import { Tile, Usdt } from "./FirstScreen";
import { CARD } from "./ui";

/**
 * «Обзор» — то, что не поместилось на первый экран: на телефоне — продажи,
 * заказы, «ожидает выплаты» и «выплачено» крупно; ссылка для Telegram-бота,
 * суммы на проверке и долг, пояснения к счётчикам. Всё из уже загруженного
 * ответа me/ — отдельных запросов этот раздел не делает.
 */
export default function OverviewTab({ me }: { me: Me }) {
  const { t, i18n } = useTranslation("creators", { useSuspense: false });
  const { money } = me;
  const held = cmpDec(money.held, "0") > 0;
  const debt = cmpDec(money.debt, "0") > 0;

  return (
    <div className="flex flex-col gap-3">
      {/*
        Телефон: счётчики п.14 ТЗ, которым на первом экране досталась только
        мелкая строка, здесь стоят крупно. С ширины sm они уже плитками на
        первом экране, и этот ряд не нужен.
      */}
      <div className="grid grid-cols-2 gap-1.5 sm:hidden">
        <Tile label={t("dash.results.sales", { defaultValue: "Продажи" })}>
          <Usdt value={me.counters.sales_usdt} />
        </Tile>
        <Tile label={t("dash.results.orders", { defaultValue: "Заказы" })}>
          {fmtInt(me.counters.orders, i18n.language)}
        </Tile>
        <Tile label={t("dash.money.pending", { defaultValue: "Ожидает выплаты" })}>
          <Usdt value={money.pending} />
        </Tile>
        <Tile label={t("dash.money.paid", { defaultValue: "Выплачено" })}>
          <Usdt value={money.paid} />
        </Tile>
      </div>

      {me.code && (
        <section className={CARD}>
          {me.telegram_link && (
            <CopyField
              label={t("dash.overview.telegram_link", { defaultValue: "Ссылка для Telegram-бота" })}
              value={me.telegram_link}
              className="mb-3"
            />
          )}
          <p className="text-sm text-muted">
            {t("dash.code.admin_only", { defaultValue: "Изменить промокод можно только через администратора." })}
          </p>
        </section>
      )}

      {(held || debt) && (
        <section className={`${CARD} flex flex-col gap-2`}>
          {held && (
            <p className="text-sm text-status-wait">
              {t("dash.overview.held", { defaultValue: "На проверке: {{held}} USDT", held: fmtUsdt(money.held) })}
            </p>
          )}
          {debt && (
            <p className="text-sm text-status-fail">
              {t("dash.overview.debt", {
                defaultValue: "Долг {{debt}} USDT — будет погашен следующими комиссиями",
                debt: fmtUsdt(money.debt),
              })}
            </p>
          )}
        </section>
      )}

      <ul className="flex list-disc flex-col gap-1 pl-5 text-xs text-muted">
        <li>{t("dash.overview.hint_clicks", { defaultValue: "Переходы — уникальные устройства в день" })}</li>
        <li>
          {t("dash.overview.hint_registrations", { defaultValue: "Регистрации и платящие — без аккаунтов на проверке" })}
        </li>
      </ul>
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { FiAward } from "react-icons/fi";
import { getProgram } from "@/lib/creators/api";
import { maxLevelPercent } from "@/lib/creators/format";
import type { Program } from "@/lib/creators/types";

/**
 * Карточка-ссылка в профиле: креатору — в его кабинет, остальным — на страницу
 * программы.
 *
 * Сама спрашивает API, поэтому верна в любом режиме программы: выключена для
 * этого человека (404 disabled) или запрос не удался — карточки просто нет.
 * Пункт меню зависит от флага сборки, а эта карточка — нет: для креатора она
 * остаётся постоянным входом в кабинет.
 */
export default function CreatorsEntryCard({ className = "" }: { className?: string }) {
  const { t, ready } = useTranslation("creators", { useSuspense: false });
  const [program, setProgram] = useState<Program | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await getProgram();
      if (alive && res.ok && res.data.mode !== "off") setProgram(res.data);
    })();
    return () => {
      alive = false;
    };
  }, []);

  // Пока переводы грузятся, ничего не рисуем — иначе в en/kg мелькнул бы русский текст.
  if (!program || !ready) return null;

  const creator = program.me.is_creator;
  const title = creator ? t("entry.cabinet_title", { defaultValue: "Кабинет креатора" }) : "EsAI Creators";
  const hint = creator
    ? t("entry.cabinet_hint", { defaultValue: "Статистика, промокод и выплаты" })
    : t("entry.join_hint", {
        defaultValue: "Зарабатывайте до {{max}}% с платежей приглашённых",
        max: maxLevelPercent(program.levels),
      });

  return (
    <Link
      href={creator ? "/creators/dashboard" : "/creators"}
      className={`flex items-center gap-3 rounded-2xl border border-border bg-surface p-6 transition-colors hover:border-accent/60 ${className}`}
    >
      <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-accent-soft">
        <FiAward className="text-xl text-accent" />
      </span>
      <span className="min-w-0">
        <span className="block font-semibold text-foreground">{title}</span>
        <span className="block text-sm text-muted">{hint}</span>
      </span>
    </Link>
  );
}

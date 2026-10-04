"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import CreatorsUnavailable from "@/components/creators/shared/CreatorsUnavailable";
import ErrorNote from "@/components/creators/shared/ErrorNote";
import { getApplication, getProgram } from "@/lib/creators/api";
import { maxLevelPercent } from "@/lib/creators/format";
import type { Application, CrError, Program } from "@/lib/creators/types";
import ApplicationForm, { type ApplyOutcome } from "./ApplicationForm";
import ApplyCta from "./ApplyCta";
import Benefits from "./Benefits";
import Hero from "./Hero";
import HowItWorks from "./HowItWorks";
import LandingSkeleton from "./LandingSkeleton";
import { CommissionSection, LevelConditionsSection, PayoutsSection } from "./Terms";
import { canApply, stageOf } from "./applyLogic";
import { CARD } from "./ui";

type Load =
  | { phase: "loading" }
  /** Программа для этого человека выключена (404 disabled). */
  | { phase: "unavailable" }
  | { phase: "error"; error: CrError }
  | { phase: "ready"; program: Program; application: Application | null };

const GUEST: Program["me"] = {
  is_authenticated: false,
  is_creator: false,
  creator_status: null,
  application_status: null,
};

/**
 * Условия программы и — для вошедшего, кто ещё не креатор, — его последняя
 * заявка (дата отправки, причина отказа, данные для повторной подачи).
 */
async function fetchLanding(): Promise<Load> {
  const res = await getProgram();
  if (!res.ok) {
    return res.error.code === "disabled" ? { phase: "unavailable" } : { phase: "error", error: res.error };
  }
  // Режим страница узнаёт только из ответа API; «off» сюда прийти не должен (сервер отвечает 404).
  if (res.data.mode === "off") return { phase: "unavailable" };

  const program: Program = {
    ...res.data,
    levels: Array.isArray(res.data.levels) ? res.data.levels : [],
    me: res.data.me || GUEST,
  };

  let application: Application | null = null;
  if (program.me.is_authenticated && !program.me.is_creator) {
    const own = await getApplication();
    if (own.ok) application = own.data.application || null;
    else if (own.error.code === "disabled") return { phase: "unavailable" };
    // Любая другая ошибка: статус заявки уже известен из условий программы,
    // карточка покажется без даты и причины — это лучше, чем не показать страницу.
  }
  return { phase: "ready", program, application };
}

/** В адресе стоит ?apply=1 — человек вернулся со входа, чтобы подать заявку. */
function takeApplyParam(): boolean {
  try {
    const url = new URL(window.location.href);
    if (url.searchParams.get("apply") !== "1") return false;
    // Убираем параметр, чтобы обновление страницы не открывало форму снова;
    // остальное (например ?ref=) остаётся на месте.
    url.searchParams.delete("apply");
    window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
    return true;
  } catch {
    return false;
  }
}

/**
 * Публичная страница программы EsAI Creators (ТЗ п.2–6): что это, как
 * работает, уровни и выплаты, заявка и её статус.
 *
 * Что стоит на месте главной кнопки, решает состояние человека (applyLogic.stageOf).
 * Уровни, проценты, минимум вывода и срок холда — только из ответа API.
 */
export default function CreatorsLanding() {
  const { t, ready } = useTranslation("creators", { useSuspense: false });
  const [load, setLoad] = useState<Load>({ phase: "loading" });
  /** Очередная загрузка; quiet — фоновая, поверх уже показанной страницы. */
  const [request, setRequest] = useState({ n: 0, quiet: false });
  const [formOpen, setFormOpen] = useState(false);
  /** ?apply=1 срабатывает один раз — при первой загрузке. */
  const applyChecked = useRef(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      const next = await fetchLanding();
      if (!alive) return;
      // Фоновая перечитка не удалась — оставляем то, что человек уже видит.
      if (request.quiet && next.phase === "error") return;
      setLoad(next);
      // Ошибка загрузки проверку не тратит: после «Повторить» ?apply=1 ещё сработает.
      if (next.phase !== "ready" || applyChecked.current) return;
      applyChecked.current = true;
      // Гостю форму не открываем и адрес не трогаем: кнопка ведёт его на вход,
      // а автоматический уход туда запер бы человека между двумя страницами.
      if (canApply(stageOf(next.program.me)) && takeApplyParam()) setFormOpen(true);
    })();
    return () => {
      alive = false;
    };
  }, [request]);

  /** Перечитать условия и заявку; quiet — не показывая заглушку поверх страницы. */
  const reload = (quiet: boolean) => {
    if (!quiet) setLoad({ phase: "loading" });
    setRequest((prev) => ({ n: prev.n + 1, quiet }));
  };

  // Пока переводы не загружены, страницу не рисуем: в en/kg иначе мелькнул бы русский текст.
  if (!ready || load.phase === "loading") return <LandingSkeleton />;
  if (load.phase === "unavailable") return <CreatorsUnavailable />;
  if (load.phase === "error") {
    return (
      <main className="mx-auto flex min-h-[70dvh] w-full max-w-md items-center px-4 pb-16 pt-28">
        <ErrorNote error={load.error} onRetry={() => reload(false)} className="w-full" />
      </main>
    );
  }

  const { program, application } = load;
  const stage = stageOf(program.me);
  const max = maxLevelPercent(program.levels);
  const applying = canApply(stage);

  const onDone = (outcome: ApplyOutcome) => {
    setFormOpen(false);
    if (outcome.kind === "submitted") {
      // Карточку «Заявка на рассмотрении» показываем сразу, по ответу сервера,
      // а условия программы перечитываем в фоне.
      setLoad({
        phase: "ready",
        program: { ...program, me: { ...program.me, application_status: outcome.application.status } },
        application: outcome.application,
      });
      reload(true);
      return;
    }
    reload(false);
  };

  const cta = <ApplyCta stage={stage} application={application} onApply={() => setFormOpen(true)} />;

  return (
    <main className="relative overflow-hidden pb-20">
      <Hero max={max}>{cta}</Hero>
      <Benefits max={max} />
      <HowItWorks />
      <CommissionSection levels={program.levels} />
      <LevelConditionsSection levels={program.levels} />
      <PayoutsSection program={program} />

      {/* Второй призыв: то же действие и та же логика состояний, что и в шапке. */}
      <section className="mx-auto max-w-5xl px-4 py-8 sm:py-10">
        <div className={`${CARD} flex flex-col items-center gap-5 text-center`}>
          <p className="max-w-2xl text-balance break-words text-lg font-semibold text-foreground sm:text-xl">
            {t("public.hero.sub", {
              defaultValue: "Получайте до {{max}}% с каждого платежа привлечённых пользователей — постоянно.",
              max,
            })}
          </p>
          <div className="flex w-full justify-center">{cta}</div>
        </div>
      </section>

      {applying && (
        // key: прошлая заявка пришла — форма собирается заново, уже заполненной.
        <ApplicationForm
          key={application?.id ?? "new"}
          open={formOpen}
          onClose={() => setFormOpen(false)}
          initial={stage === "rejected" ? application : null}
          onDone={onDone}
        />
      )}
    </main>
  );
}

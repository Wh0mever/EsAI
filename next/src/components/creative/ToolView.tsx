"use client";

import clsx from "clsx";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { FiArrowDown, FiGrid } from "react-icons/fi";
import { useAuthedHint } from "@/components/bootstrap/AuthHint";
import { getJob, isUid, type JobJSON } from "@/lib/creative/api";
import { formFor, initialValues, valuesFromParams, type FormValues } from "@/lib/creative/forms";
import { useCt } from "@/lib/creative/text";
import { toolById } from "@/lib/creative/tools";
import { CREATIVE_PATH } from "@/lib/nav/paths";
import type { PackageNeed } from "@/lib/packagePick";
import { requestTopUp, useTopUpRequest } from "@/lib/topupRequest";
import RunForm from "./run/RunForm";
import { toolGate, useCreativeAccess } from "./run/useCreativeAccess";
import { FOCUS, Skeleton } from "./run/ui";
import WorksList from "./works/WorksList";
import { OtherTools, SoonNotice, ToolBack, ToolHero } from "./ToolSoon";

// Окно пакетов нужно только тому, кому не хватило кредитов: в бандл страницы не кладём.
const TopUpModal = dynamic(() => import("@/components/chat/TopUpModal"), { ssr: false });

/**
 * Страница инструмента /creative/<id> (SPEC_B §9).
 *
 * Сервер и первый кадр браузера рисуют одно и то же: шапку инструмента и скелет
 * формы. Что показать дальше, решает GET tools/ после монтирования: форму (вошёл
 * и раздел открыт), форму с «Войти» (гость, раздел открыт всем) или «Скоро».
 * Под формой — «Мои работы» этого инструмента; у постоянного персонажа вместо
 * них — «Мои персонажи».
 */
const noopSubscribe = () => () => {};
const readSearch = () => window.location.search;
const serverSearch = () => "";

export default function ToolView({ id }: { id: string }) {
  const tool = toolById(id);
  const form = formFor(id);
  const { ct, lang } = useCt();
  const authed = useAuthedHint();
  const access = useCreativeAccess();
  const gate = form ? toolGate(access, id, authed) : ({ kind: "soon" } as const);

  // Адрес читаем только в браузере (useSearchParams потребовал бы Suspense и
  // увёл бы страницу из серверной отрисовки).
  const search = useSyncExternalStore(noopSubscribe, readSearch, serverSearch);
  const sp = useMemo(() => new URLSearchParams(search), [search]);
  const charParam = sp.get("character");
  const repeatParam = sp.get("repeat");

  // ?character=<uid> со страницы персонажей — сразу в форму (инструмент 8).
  const charPreset = useMemo<FormValues | null>(() => {
    if (!form || !isUid(charParam) || !form.fields.some((f) => f.type === "character")) return null;
    return { ...initialValues(form, lang), character: charParam };
    // язык — только для значения по умолчанию: менять форму при смене языка не нужно
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form, charParam]);
  const [preset, setPreset] = useState<FormValues | null>(null);
  const [notice, setNotice] = useState("");
  const [worksKey, setWorksKey] = useState(0);
  const formRef = useRef<HTMLElement>(null);

  const canRun = gate.kind === "form" && gate.run;

  // ?repeat=<uid> из общего списка «Мои работы»: настройки той работы — в форму.
  useEffect(() => {
    if (!form || !canRun || !isUid(repeatParam)) return;
    let alive = true;
    void getJob(repeatParam).then((r) => {
      if (!alive || !r.ok || r.data.tool !== id) return;
      setPreset(valuesFromParams(form, r.data.params_public, lang));
      setNotice(ct("works.repeat_done"));
    });
    return () => {
      alive = false;
    };
    // повторяем только при смене адреса или доступа
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repeatParam, canRun, id]);

  // Пополнение на месте: «Создать» без кредитов и напоминание об остатке открывают окно здесь.
  const [topup, setTopup] = useState<{ open: boolean; mounted: boolean; need: PackageNeed | null }>({ open: false, mounted: false, need: null });
  const needRef = useRef<PackageNeed | null>(null);
  const router = useRouter();
  useTopUpRequest(() => {
    const need = needRef.current;
    needRef.current = null;
    setTopup({ open: true, mounted: true, need });
  });
  const onTopUp = useCallback((need: PackageNeed | null) => {
    needRef.current = need;
    if (!requestTopUp()) router.push("/pricing");
  }, [router]);

  const onSettled = useCallback(() => setWorksKey((x) => x + 1), []);

  const onRepeat = useCallback(
    (job: JobJSON) => {
      if (!form) return;
      setPreset(valuesFromParams(form, job.params_public, lang));
      setNotice(ct("works.repeat_done"));
      const reduce = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      formRef.current?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
      formRef.current?.focus({ preventScroll: true });
    },
    [form, lang, ct],
  );

  if (!tool) return null;
  const toolName = ct(`tools.${tool.id}.name`) === `tools.${tool.id}.name` ? tool.name : ct(`tools.${tool.id}.name`);
  const priceHint = gate.kind === "form" ? gate.tool?.price_hint_credits ?? null : null;
  const showWorks = canRun && tool.id !== "consistent-character";

  return (
    <main className="mx-auto max-w-7xl px-4 pb-16 pt-28 sm:px-6 sm:pt-32 lg:px-8">
      <ToolBack />
      <ToolHero tool={tool}>
        {gate.kind === "checking" && <Skeleton className="mt-6 h-12 max-w-xs" />}
        {gate.kind === "soon" && <SoonNotice />}
        {gate.kind === "form" && (
          <div className="mt-5 flex flex-wrap items-center gap-2">
            {priceHint != null && (
              <span className="inline-flex min-h-9 items-center rounded-lg bg-[#F5C518]/15 px-3 text-sm font-semibold text-[var(--accent-text)]">
                {ct("run.price_hint", { n: priceHint })}
              </span>
            )}
            {showWorks && (
              <a href="#works" className={clsx("inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-border px-3 text-sm font-medium hover:border-[#F5C518]/60", FOCUS)}>
                <FiArrowDown aria-hidden="true" className="size-3.5" />
                {ct("run.tab_works")}
              </a>
            )}
          </div>
        )}
      </ToolHero>

      {gate.kind === "checking" && (
        <div className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(320px,400px)]" aria-busy="true" aria-label={ct("run.checking")}>
          <Skeleton className="h-72" />
          <Skeleton className="h-40" />
        </div>
      )}

      {gate.kind === "form" && form && (
        <section ref={formRef} tabIndex={-1} aria-labelledby="cs-form-title" className="mt-8 scroll-mt-24 outline-none">
          <h2 id="cs-form-title" className="sr-only">
            {ct("run.tab_create")}
          </h2>
          <p className={clsx("text-sm", notice && "mb-3 rounded-xl bg-[#F5C518]/15 px-3.5 py-2")} role="status" aria-live="polite">
            {notice}
          </p>
          <RunForm
            key={tool.id}
            toolId={tool.id}
            toolName={toolName}
            form={form}
            canRun={gate.run}
            priceHint={priceHint}
            ct={ct}
            lang={lang}
            onTopUp={onTopUp}
            onSettled={onSettled}
            preset={preset ?? charPreset}
          />
        </section>
      )}

      {showWorks && (
        <section id="works" aria-labelledby="cs-works-title" className="mt-12 scroll-mt-24">
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <h2 id="cs-works-title" className="text-xl font-bold">
              {ct("works.tool_title")}
            </h2>
            <Link href={`${CREATIVE_PATH}/works`} className={clsx("inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-[var(--accent-text)] hover:underline", FOCUS)}>
              <FiGrid aria-hidden="true" className="size-4" />
              {ct("run.all_works")}
            </Link>
          </div>
          <WorksList tool={tool.id} ct={ct} lang={lang} reloadKey={worksKey} onRepeat={onRepeat} labelledBy="cs-works-title" />
        </section>
      )}

      {canRun && tool.id === "consistent-character" && (
        <div className="mt-6 flex justify-end">
          <Link href={`${CREATIVE_PATH}/works`} className={clsx("inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-[var(--accent-text)] hover:underline", FOCUS)}>
            <FiGrid aria-hidden="true" className="size-4" />
            {ct("run.all_works")}
          </Link>
        </div>
      )}

      <OtherTools tool={tool} />

      {topup.mounted && (
        <TopUpModal
          open={topup.open}
          onClose={() => {
            setTopup((s) => ({ ...s, open: false }));
            try {
              window.dispatchEvent(new CustomEvent("balance:refresh"));
            } catch {
              /* старый браузер */
            }
          }}
          returnTo={`${CREATIVE_PATH}/${tool.id}`}
          need={topup.need}
        />
      )}
    </main>
  );
}


"use client";

import clsx from "clsx";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { FiChevronDown, FiLogIn } from "react-icons/fi";
import { cancelJob, getJobs, isOpen, newClientRequestId, run, type JobJSON } from "@/lib/creative/api";
import { errorText, fieldErrors, jobErrorText } from "@/lib/creative/errors";
import {
  buildParams,
  imagesMax,
  initialValues,
  missingFields,
  paramsKey,
  type EnumField,
  type FieldSpec,
  type FormValue,
  type FormValues,
  type ToolForm,
} from "@/lib/creative/forms";
import type { Ct } from "@/lib/creative/text";
import { apiLang } from "@/lib/apiLang";
import { rememberReturnPath } from "@/tools/authNext";
import { missingCredits } from "@/lib/vstudio/errors";
import type { PackageNeed } from "@/lib/packagePick";
import type { VsError } from "@/lib/vstudio/types";
import CatalogPicker from "./CatalogPicker";
import { CharacterList, CharacterPicker } from "./Characters";
import { ChoiceChips, RangeBox, SelectBox, Toggle } from "./Controls";
import InfluencerPicker, { type Selection } from "./InfluencerPicker";
import { JobOutcome, JobWaiting } from "./JobView";
import UploadField from "./UploadField";
import { refreshAccess } from "./useCreativeAccess";
import { useJobPoll } from "./useJobPoll";
import { useQuote } from "./useQuote";
import { BTN_GHOST, BTN_GOLD, CARD, FieldShell, FOCUS, INPUT, Spinner } from "./ui";

/**
 * Рамка запуска инструмента (SPEC_B §9): поля → цена до запуска → «Создать» →
 * ожидание (страницу можно закрыть) → результат. Одна на все 15 инструментов;
 * что за поля — решает конфиг формы (lib/creative/forms.ts).
 */
export type RunFormProps = {
  toolId: string;
  toolName: string;
  form: ToolForm;
  /** вошёл и раздел открыт: можно грузить, считать цену и запускать */
  canRun: boolean;
  /** цена «от …» из tools/ (для гостя её нет) */
  priceHint: number | null;
  ct: Ct;
  lang: string;
  /** открыть пополнение на месте (TopUpModal страницы) */
  onTopUp: (need: PackageNeed | null) => void;
  /** работа закончилась — «Мои работы» перечитают список */
  onSettled: () => void;
  /** значения «Повторить» из «Моих работ» (меняется ссылка — форма перезаполняется) */
  preset?: FormValues | null;
  /** ?character=<uid> со страницы персонажей (инструмент 8) */
  initialCharacter?: string | null;
};

/**
 * Ответ на run() доказывает, что работа НЕ создана: в теле наш error_code
 * (creative/errors.py, отказ резерва) или это 4xx — до вьюхи/транзакции.
 * Обрыв сети (0), 5xx без нашего кода (502/504/524 прокси, HTML) и «ok, но
 * тело не разобрать» — неясно: заказ мог закоммититься, client_request_id
 * держим, чтобы повтор вернул ту же работу (200), а не создал вторую.
 */
function provesNoJob(status: number, err: VsError): boolean {
  if (typeof err.data.error_code === "string" && err.data.error_code) return true;
  return status >= 400 && status < 500;
}

/** Незаконченная работа инструмента (новые сверху); null — нет или список не загрузился. */
async function findOpenJob(toolId: string): Promise<JobJSON | null> {
  const r = await getJobs({ tool: toolId });
  return r.ok ? r.data.items.find((j) => isOpen(j.status)) ?? null : null;
}

/** Первое поле формы, куда можно вернуть фокус (скрытый input файла пропускаем). */
function firstField(form: HTMLFormElement | null): HTMLElement | null {
  return (
    form?.querySelector<HTMLElement>(
      "textarea:not([disabled]), input:not([disabled]):not([type=file]):not([type=hidden]), select:not([disabled]), button:not([disabled])",
    ) ?? null
  );
}

export default function RunForm(props: RunFormProps) {
  const { toolId, toolName, form, canRun, priceHint, ct, lang, onTopUp, onSettled, preset, initialCharacter } = props;
  const guest = !canRun;

  const [values, setValues] = useState<FormValues>(() => {
    if (preset) return preset;
    const v = initialValues(form, lang);
    if (initialCharacter && "character" in v) v.character = initialCharacter;
    return v;
  });
  const [presetSeen, setPresetSeen] = useState(preset);

  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [runErrs, setRunErrs] = useState<{ key: string; errs: Record<string, string> } | null>(null);
  const [sending, setSending] = useState(false);
  const [runError, setRunError] = useState("");
  const [priceChange, setPriceChange] = useState<number | null>(null);
  const [current, setCurrent] = useState<JobJSON | null>(null);
  const [etaS, setEtaS] = useState<number | null>(null);
  const [canceling, setCanceling] = useState(false);
  const [restored, setRestored] = useState(false);
  const [charsKey, setCharsKey] = useState(0);
  const cidRef = useRef<{ cid: string; key: string } | null>(null);
  // Защита от двойного клика: state обновится только на следующем кадре.
  const sendingRef = useRef(false);
  const outcomeRef = useRef<HTMLDivElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const mainBtnRef = useRef<HTMLButtonElement>(null);

  const params = useMemo(() => buildParams(form, values), [form, values]);
  const key = useMemo(() => paramsKey(params), [params]);
  const missing = useMemo(() => missingFields(toolId, form, values), [toolId, form, values]);
  const uploading = Object.values(busy).some(Boolean);

  const handleSettled = useCallback(
    (job: JobJSON) => {
      onSettled();
      if (job.kind === "character") setCharsKey((x) => x + 1);
    },
    [onSettled],
  );
  const [job, setJob] = useJobPoll(current, handleSettled);
  const jobOpen = isOpen(job?.status);

  // «Повторить» из «Моих работ»: новые значения формы; готовый итог убираем,
  // идущую работу — нет (она досчитается и останется в «Моих работах»).
  if (preset && preset !== presetSeen) {
    setPresetSeen(preset);
    setValues(preset);
    setRunErrs(null);
    setRunError("");
    setPriceChange(null);
    if (!jobOpen) {
      setCurrent(null);
      setJob(null);
      setRestored(false);
    }
  }

  const quoteOn = canRun && !missing.length && !uploading && !jobOpen;
  const q = useQuote(toolId, params, key, quoteOn, apiLang(lang));

  /** Вернуть на экран незаконченную работу этого инструмента. */
  const showOpen = (open: JobJSON) => {
    setCurrent((cur) => cur ?? open);
    setRestored(true);
  };

  // После перезагрузки страницы.
  useEffect(() => {
    if (!canRun) return;
    let alive = true;
    void findOpenJob(toolId).then((open) => {
      if (!alive || !open) return;
      setCurrent((cur) => cur ?? open);
      setRestored(true);
    });
    return () => {
      alive = false;
    };
  }, [canRun, toolId]);

  const set = (name: string, v: FormValue) => {
    setValues((prev) => ({ ...prev, [name]: v }));
    setRunError("");
    setPriceChange(null);
  };

  // Ошибки полей: последнего запуска (для этой же формы) или расчёта цены.
  const errs: Record<string, string> = useMemo(() => {
    if (runErrs && runErrs.key === key) return runErrs.errs;
    if (q.error && q.error.code === "bad_params") return fieldErrors(ct, q.error);
    return {};
  }, [runErrs, key, q.error, ct]);

  const submit = async (credits: number) => {
    if (sendingRef.current) return;
    sendingRef.current = true;
    // Один клик — один client_request_id; повтор после обрыва сети — тот же.
    if (!cidRef.current || cidRef.current.key !== key) cidRef.current = { cid: newClientRequestId(), key };
    setSending(true);
    setRunError("");
    setPriceChange(null);
    const r = await run({ tool: toolId, params, quoted_credits: credits, client_request_id: cidRef.current.cid, lang: apiLang(lang) });
    sendingRef.current = false;
    setSending(false);
    if (r.ok) {
      cidRef.current = null;
      setRestored(false);
      setEtaS(q.quote?.eta_s ?? null);
      setCurrent(r.data.job);
      try {
        window.dispatchEvent(new CustomEvent("balance:refresh"));
      } catch {
        /* старый браузер */
      }
      requestAnimationFrame(() => outcomeRef.current?.focus());
      return;
    }
    const err = r.error;
    if (!provesNoJob(r.status, err)) {
      // Неясно, создана ли работа: тот же cid остаётся для повтора, открытую работу ищем сразу.
      setRunError(errorText(ct, err));
      const open = await findOpenJob(toolId);
      if (open) {
        showOpen(open);
        cidRef.current = null;
        setRunError("");
        requestAnimationFrame(() => outcomeRef.current?.focus());
      }
      return;
    }
    cidRef.current = null;
    const code = r.status === 402 && err.code !== "insufficient_tokens" ? "insufficient_balance" : err.code;
    switch (code) {
      case "insufficient_balance":
      case "insufficient_tokens": {
        const miss = missingCredits(err);
        onTopUp(miss > 0 ? { missing: miss, cost: credits, for: "generation" } : null);
        setRunError(errorText(ct, err));
        return;
      }
      case "price_changed": {
        const next = typeof err.data.credits === "number" ? err.data.credits : null;
        if (next != null) setPriceChange(next);
        else setRunError(errorText(ct, err));
        q.refresh();
        return;
      }
      case "bad_params":
        setRunErrs({ key, errs: fieldErrors(ct, err) });
        setRunError(errorText(ct, err));
        return;
      case "creative_disabled":
      case "tool_disabled":
        setRunError(errorText(ct, err));
        void refreshAccess(true);
        return;
      default:
        setRunError(errorText(ct, err));
    }
  };

  const cancel = async () => {
    if (!job) return;
    setCanceling(true);
    const r = await cancelJob(job.uid);
    setCanceling(false);
    if (r.ok) {
      setJob(r.data.job);
      try {
        window.dispatchEvent(new CustomEvent("balance:refresh"));
      } catch {
        /* старый браузер */
      }
      onSettled();
      // «Отменить» исчезает вместе с ожиданием — фокус на блок итога (он остаётся в DOM).
      requestAnimationFrame(() => outcomeRef.current?.focus());
    } else {
      setRunError(errorText(ct, r.error));
    }
  };

  const reset = () => {
    setCurrent(null);
    setJob(null);
    setRestored(false);
    setRunError("");
  };
  // Блок итога с нажатой кнопкой исчезает — фокус в форму, а не в начало страницы.
  const focusForm = () => requestAnimationFrame(() => (firstField(formRef.current) ?? mainBtnRef.current)?.focus());
  const again = () => {
    reset();
    focusForm();
  };
  const fresh = () => {
    reset();
    setValues(initialValues(form, lang));
    setRunErrs(null);
    focusForm();
  };

  // Итог для экранного диктора: одна постоянная live-область, меняется только текст.
  let announce = "";
  if (job && !jobOpen) {
    if (job.status === "done") {
      announce = job.credits_charged ? `${ct("run.done_title")}. ${ct("run.charged", { n: job.credits_charged })}` : ct("run.done_title");
    } else if (job.status === "canceled") {
      announce = jobErrorText(ct, job);
    } else {
      announce = `${ct("run.failed_title")}: ${jobErrorText(ct, job)}`;
    }
  }

  const plain = form.fields.filter((f) => !f.advanced);
  const extra = form.fields.filter((f) => f.advanced);
  const fieldsDisabled = jobOpen || sending;

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(320px,400px)] lg:items-start">
      <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {announce}
      </p>
      <form
        ref={formRef}
        className={clsx(CARD, "space-y-6 p-4 sm:p-6")}
        onSubmit={(e) => e.preventDefault()}
        noValidate
        aria-label={toolName}
      >
        {plain.map((f) => (
          <FieldView
            key={f.name}
            f={f}
            toolId={toolId}
            values={values}
            set={set}
            setBusy={(b) => setBusy((prev) => (prev[f.name] === b ? prev : { ...prev, [f.name]: b }))}
            error={errs[f.name]}
            guest={guest}
            disabled={fieldsDisabled}
            ct={ct}
          />
        ))}

        {extra.length > 0 && (
          <details className="group rounded-xl border border-border">
            <summary className={clsx("flex min-h-11 cursor-pointer list-none items-center justify-between gap-2 rounded-xl px-4 text-sm font-semibold", FOCUS)}>
              {toolId === "script-to-video" ? ct("run.creative_settings") : ct("run.advanced")}
              <FiChevronDown aria-hidden="true" className="size-4 transition-transform group-open:rotate-180" />
            </summary>
            <div className="space-y-6 border-t border-border p-4">
              {extra.map((f) => (
                <FieldView
                  key={f.name}
                  f={f}
                  toolId={toolId}
                  values={values}
                  set={set}
                  setBusy={(b) => setBusy((prev) => (prev[f.name] === b ? prev : { ...prev, [f.name]: b }))}
                  error={errs[f.name]}
                  guest={guest}
                  disabled={fieldsDisabled}
                  ct={ct}
                />
              ))}
            </div>
          </details>
        )}

        {form.consent && (
          <div className="space-y-1.5">
            <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-border bg-background p-3.5 text-sm">
              <input
                type="checkbox"
                checked={values.consent === true}
                disabled={fieldsDisabled}
                onChange={(e) => set("consent", e.target.checked)}
                aria-describedby="cs-consent-hint"
                aria-invalid={Boolean(errs.consent) || undefined}
                className="mt-0.5 size-5 shrink-0 cursor-pointer accent-[#F5C518]"
              />
              <span>
                <span className="font-semibold">{ct("run.consent")}</span>
                <span id="cs-consent-hint" className="mt-0.5 block text-xs text-muted">
                  {ct("run.consent_hint")}
                </span>
              </span>
            </label>
            {errs.consent && (
              <p role="alert" className="text-xs font-medium text-status-fail">
                {errs.consent}
              </p>
            )}
          </div>
        )}
      </form>

      <aside className="space-y-4 lg:sticky lg:top-24">
        {/* live-область всегда в DOM, внутри меняется только содержимое */}
        <div role="status">
          {restored && jobOpen && <p className="rounded-xl bg-[#F5C518]/15 px-3.5 py-2 text-sm">{ct("run.restored")}</p>}
        </div>
        <div ref={outcomeRef} tabIndex={-1} className="space-y-4 outline-none">
          {job && jobOpen && <JobWaiting job={job} etaS={etaS} onCancel={() => void cancel()} canceling={canceling} ct={ct} />}
          {job && !jobOpen && <JobOutcome job={job} toolName={toolName} onAgain={again} onNew={fresh} ct={ct} />}
        </div>

        {!jobOpen && !(job && !jobOpen) && (
          <RunPanel
            canRun={canRun}
            toolId={toolId}
            missing={missing}
            uploading={uploading}
            q={q}
            sending={sending}
            priceHint={priceHint}
            runError={runError}
            priceChange={priceChange}
            onRun={(credits) => void submit(credits)}
            onDismissChange={() => {
              setPriceChange(null);
              // Блок «Цена изменилась» исчезает — фокус обратно на «Создать».
              requestAnimationFrame(() => mainBtnRef.current?.focus());
            }}
            onTopUp={onTopUp}
            mainBtnRef={mainBtnRef}
            ct={ct}
          />
        )}
        {jobOpen && runError && (
          <p role="alert" className="text-sm text-status-fail">
            {runError}
          </p>
        )}
      </aside>

      {toolId === "consistent-character" && canRun && (
        <div className="lg:col-span-2">
          <CharacterList ct={ct} reloadKey={charsKey} />
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Цена и кнопка                                                       */
/* ------------------------------------------------------------------ */

function RunPanel({
  canRun,
  toolId,
  missing,
  uploading,
  q,
  sending,
  priceHint,
  runError,
  priceChange,
  onRun,
  onDismissChange,
  onTopUp,
  mainBtnRef,
  ct,
}: {
  canRun: boolean;
  toolId: string;
  missing: string[];
  uploading: boolean;
  q: ReturnType<typeof useQuote>;
  sending: boolean;
  priceHint: number | null;
  runError: string;
  priceChange: number | null;
  onRun: (credits: number) => void;
  onDismissChange: () => void;
  onTopUp: (need: PackageNeed | null) => void;
  /** главная кнопка панели («Создать» / «Пополнить»): сюда возвращаем фокус */
  mainBtnRef: RefObject<HTMLButtonElement | null>;
  ct: Ct;
}) {
  // 409 price_changed: кнопка с фокусом заменяется вопросом — фокус на «Да, создать»,
  // иначе он падает на <body> и диктор не прочтёт, что цена изменилась.
  const confirmRef = useRef<HTMLButtonElement>(null);
  const asking = priceChange != null;
  useEffect(() => {
    if (asking) confirmRef.current?.focus();
  }, [asking]);

  if (!canRun) {
    const next = `/creative/${toolId}`;
    return (
      <div className={clsx(CARD, "space-y-3 p-5")}>
        <p className="text-sm text-muted">{ct("run.signin_hint")}</p>
        <Link href={`/auth/signin?next=${encodeURIComponent(next)}`} onClick={() => rememberReturnPath(next)} className={clsx(BTN_GOLD, "w-full")}>
          <FiLogIn aria-hidden="true" className="size-4" />
          {ct("run.signin")}
        </Link>
      </div>
    );
  }

  const quote = q.quote;
  const after = quote?.balance?.after ?? null;
  const short = after != null && after < 0 ? Math.ceil(-after) : 0;
  const ready = !missing.length && !uploading && Boolean(quote) && !q.loading;

  let status = "";
  if (uploading) status = ct("run.wait_uploads");
  else if (missing.length === 1 && missing[0] === "consent") status = ct("run.need_consent");
  else if (missing.length) status = ct("run.fill_required");
  else if (q.loading && !quote) status = ct("run.quoting");
  else if (q.error && q.error.code !== "bad_params") status = errorText(ct, q.error);

  return (
    <div className={clsx(CARD, "space-y-4 p-5")}>
      <div className="flex items-end justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-muted">{ct("run.price")}</p>
          <p className="mt-0.5 text-2xl font-extrabold tabular-nums" aria-live="polite" aria-atomic="true">
            {quote ? (
              <span className={clsx(q.loading && "opacity-60")}>{ct("run.credits", { n: quote.credits })}</span>
            ) : priceHint != null && missing.length ? (
              <span className="text-lg text-muted">{ct("run.price_hint", { n: priceHint })}</span>
            ) : (
              <span className="text-lg text-muted">—</span>
            )}
          </p>
        </div>
        {q.loading && <Spinner className="mb-1.5 size-4 text-muted" />}
      </div>
      {quote?.balance && (
        <p className={clsx("text-sm", short ? "font-medium text-status-fail" : "text-muted")}>
          {short ? ct("run.balance_missing", { n: short }) : ct("run.balance_after", { n: Math.max(0, after ?? quote.balance.available) })}
        </p>
      )}
      {/* live-область всегда в DOM: меняется только текст (пустая — не занимает места) */}
      <p className={clsx("text-sm text-muted", !status && "sr-only")} role="status">
        {status}
      </p>

      {priceChange != null ? (
        <div className="space-y-3 rounded-xl border border-[#F5C518]/50 bg-[#F5C518]/10 p-3.5" role="alertdialog" aria-labelledby="cs-pc-title" aria-describedby="cs-pc-text">
          <p id="cs-pc-title" className="text-sm font-semibold">
            {ct("run.price_changed_title")}
          </p>
          <p id="cs-pc-text" className="text-sm">
            {ct("run.price_changed_text", { n: priceChange })}
          </p>
          <div className="flex flex-wrap gap-2">
            <button ref={confirmRef} type="button" className={BTN_GOLD} onClick={() => onRun(priceChange)} disabled={sending}>
              {ct("run.confirm_create")}
            </button>
            <button type="button" className={BTN_GHOST} onClick={onDismissChange}>
              {ct("run.cancel")}
            </button>
          </div>
        </div>
      ) : short > 0 && quote ? (
        <button ref={mainBtnRef} type="button" className={clsx(BTN_GOLD, "w-full")} onClick={() => onTopUp({ missing: short, cost: quote.credits, for: "generation" })}>
          {ct("run.topup_missing", { n: short })}
        </button>
      ) : (
        <button
          ref={mainBtnRef}
          type="button"
          className={clsx(BTN_GOLD, "w-full")}
          disabled={!ready || sending}
          aria-busy={sending}
          onClick={() => quote && onRun(quote.credits)}
        >
          {sending ? (
            <>
              <Spinner /> {ct("run.sending")}
            </>
          ) : quote ? (
            ct("run.create_for", { n: quote.credits })
          ) : (
            ct("run.create")
          )}
        </button>
      )}

      {runError && (
        <p role="alert" className="text-sm text-status-fail">
          {runError}
        </p>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Одно поле формы                                                     */
/* ------------------------------------------------------------------ */

function optionLabel(ct: Ct, f: EnumField, v: string): string {
  if (v === "auto") return ct("opt.auto");
  if (f.opt && f.opt !== "aspect") return ct(`opt.${f.opt}.${v}`);
  return v;
}

function FieldView({
  f,
  toolId,
  values,
  set,
  setBusy,
  error,
  guest,
  disabled,
  ct,
}: {
  f: FieldSpec;
  toolId: string;
  values: FormValues;
  set: (name: string, v: FormValue) => void;
  setBusy: (b: boolean) => void;
  error?: string;
  guest: boolean;
  disabled: boolean;
  ct: Ct;
}) {
  const label = ct(f.label);
  const hint = f.hint ? ct(f.hint) : undefined;
  const v = values[f.name];

  switch (f.type) {
    case "text": {
      const text = typeof v === "string" ? v : "";
      const single = (f.rows ?? 3) <= 1;
      return (
        <FieldShell
          label={label}
          hint={hint}
          error={error}
          required={f.required}
          counter={
            !single ? (
              <span className={clsx("text-xs tabular-nums", text.length > f.max * 0.9 ? "text-status-fail" : "text-muted")}>
                {ct("run.counter", { n: text.length, max: f.max })}
              </span>
            ) : undefined
          }
        >
          {({ id, describedBy }) =>
            single ? (
              <input
                id={id}
                type="text"
                value={text}
                maxLength={f.max}
                disabled={disabled}
                placeholder={f.placeholder ? ct(f.placeholder) : undefined}
                aria-describedby={describedBy}
                aria-invalid={Boolean(error) || undefined}
                aria-required={f.required || undefined}
                onChange={(e) => set(f.name, e.target.value)}
                className={INPUT}
              />
            ) : (
              <textarea
                id={id}
                value={text}
                rows={f.rows ?? 3}
                maxLength={f.max}
                disabled={disabled}
                placeholder={f.placeholder ? ct(f.placeholder) : undefined}
                aria-describedby={describedBy}
                aria-invalid={Boolean(error) || undefined}
                aria-required={f.required || undefined}
                onChange={(e) => set(f.name, e.target.value)}
                className={clsx(INPUT, "min-h-[3.25rem] resize-y leading-relaxed")}
              />
            )
          }
        </FieldShell>
      );
    }
    case "enum": {
      const value = typeof v === "string" ? v : f.default ?? "auto";
      const options = f.choices.map((c) => ({ value: c, label: optionLabel(ct, f, c) }));
      if (f.ui === "select") {
        return (
          <FieldShell label={label} hint={hint} error={error}>
            {({ id, describedBy }) => <SelectBox id={id} value={value} options={options} onChange={(x) => set(f.name, x)} disabled={disabled} describedBy={describedBy} />}
          </FieldShell>
        );
      }
      return (
        <FieldShell label={label} hint={hint} error={error} as="fieldset">
          {({ labelId }) => <ChoiceChips name={f.name} value={value} options={options} onChange={(x) => set(f.name, x)} disabled={disabled} labelId={labelId} />}
        </FieldShell>
      );
    }
    case "int": {
      const value = typeof v === "number" ? v : f.default;
      if (f.ui === "range") {
        return (
          <FieldShell label={label} hint={hint} error={error}>
            {({ id, describedBy }) => (
              <RangeBox
                id={id}
                value={value}
                min={f.min ?? 1}
                max={f.max ?? 10}
                unit={f.unit ? ct(f.unit) : ""}
                onChange={(x) => set(f.name, x)}
                disabled={disabled}
                describedBy={describedBy}
              />
            )}
          </FieldShell>
        );
      }
      const choices = f.choices ?? [];
      return (
        <FieldShell label={label} hint={hint} error={error} as="fieldset">
          {({ labelId }) => (
            <ChoiceChips name={f.name} value={value} options={choices.map((c) => ({ value: c, label: String(c) }))} onChange={(x) => set(f.name, x)} disabled={disabled} labelId={labelId} />
          )}
        </FieldShell>
      );
    }
    case "bool":
      return (
        <FieldShell label={label} hint={hint} error={error}>
          {({ id, describedBy, labelId }) => (
            <Toggle id={id} checked={v === true} onChange={(x) => set(f.name, x)} disabled={disabled} describedBy={describedBy} labelledBy={labelId} />
          )}
        </FieldShell>
      );
    case "image":
    case "video":
    case "images": {
      const multiple = f.type === "images";
      const max = f.type === "images" ? imagesMax(toolId, f, values) : 1;
      const required = f.type === "images" ? f.min > 0 || (f.name === "product_images" && Boolean(values.preset) && max <= 2) : f.required;
      return (
        <FieldShell label={label} hint={hint} error={error} required={required} as="fieldset">
          {({ labelId, describedBy }) =>
            guest ? (
              <p className="rounded-xl border border-dashed border-border px-4 py-5 text-center text-sm text-muted">{ct("run.signin_hint")}</p>
            ) : (
              <UploadField
                kind={f.type === "video" ? "video" : "image"}
                multiple={multiple}
                max={max}
                value={multiple ? (Array.isArray(v) ? v : []) : typeof v === "string" ? v : ""}
                onChange={(x) => set(f.name, x)}
                onBusy={setBusy}
                minFrame={f.type === "video" ? f.minFrame : undefined}
                disabled={disabled}
                ct={ct}
                labelId={labelId}
                describedBy={describedBy}
              />
            )
          }
        </FieldShell>
      );
    }
    case "catalog":
      return (
        <FieldShell label={label} hint={hint} error={error} required={f.required} as="fieldset">
          {({ labelId }) => (
            <CatalogPicker
              kind={f.catalog}
              value={typeof v === "string" ? v : ""}
              onChange={(x) => set(f.name, x)}
              required={f.required}
              disabled={disabled}
              guest={guest}
              ct={ct}
              labelId={labelId}
              noneLabel={f.catalog === "ms-presets" ? ct("run.none_preset") : ct("run.none_style")}
            />
          )}
        </FieldShell>
      );
    case "character":
      return (
        <FieldShell label={label} hint={hint} error={error} as="fieldset">
          {({ labelId }) => (
            <CharacterPicker value={typeof v === "string" ? v : ""} onChange={(x) => set(f.name, x)} disabled={disabled} guest={guest} ct={ct} labelId={labelId} />
          )}
        </FieldShell>
      );
    case "options":
      return (
        <FieldShell label={label} hint={hint} error={error} as="fieldset">
          {() => (
            <InfluencerPicker
              value={v && typeof v === "object" && !Array.isArray(v) ? (v as Selection) : {}}
              onChange={(x) => set(f.name, x)}
              disabled={disabled}
              guest={guest}
              ct={ct}
            />
          )}
        </FieldShell>
      );
    default:
      return null;
  }
}

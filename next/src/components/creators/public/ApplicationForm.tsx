"use client";

import { useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Modal } from "@/components/dialog/Dialog";
import ErrorNote from "@/components/creators/shared/ErrorNote";
import { useDialogFocus } from "@/components/creators/shared/useDialogFocus";
import { apiLang } from "@/lib/apiLang";
import { submitApplication } from "@/lib/creators/api";
import { errorText, fieldErrorText } from "@/lib/creators/errors";
import type { Application, CrError } from "@/lib/creators/types";
import {
  LIMITS,
  clearDraft,
  firstField,
  loadDraft,
  normalizeUrl,
  normalizeValues,
  saveDraft,
  validateApplication,
  valuesFromApplication,
  type FieldIssue,
  type FieldName,
  type FormValues,
  type Validation,
} from "./applyLogic";
import { BTN_PRIMARY, SIGNIN_TO_APPLY } from "./ui";

/** Чем закончилась отправка — решает страница. */
export type ApplyOutcome =
  /** Заявка принята (201). */
  | { kind: "submitted"; application: Application }
  /**
   * Сервер ответил, что положение уже другое: заявка на рассмотрении, человек
   * уже креатор, подача закрыта или программа выключена. Форме тут делать
   * нечего — страница перечитает состояние и покажет нужную карточку.
   */
  | { kind: "stale" };

type Props = {
  open: boolean;
  onClose: () => void;
  /** Прошлая (отклонённая) заявка — форма открывается заполненной. */
  initial: Application | null;
  onDone: (outcome: ApplyOutcome) => void;
};

/** Ответы, после которых форма закрывается, а страница перечитывает состояние. */
const STALE_CODES = new Set(["application_open", "already_creator", "apply_blocked", "disabled"]);

const NOTHING: Validation = { issues: {}, linksMissing: false, body: null };

const fieldId = (name: FieldName) => `creators-apply-${name}`;

const INPUT =
  "w-full min-w-0 rounded-xl border bg-surface-2 px-3.5 py-2.5 text-base text-foreground outline-none transition-colors placeholder:text-muted-2 focus:border-accent disabled:opacity-60 sm:text-sm";

function FieldShell({
  name,
  label,
  required,
  hint,
  error,
  counter,
  wide,
  children,
}: {
  name: FieldName;
  label: string;
  required?: boolean;
  hint?: string;
  error: string;
  counter?: string;
  /** На широком экране поле занимает обе колонки. */
  wide?: boolean;
  children: ReactNode;
}) {
  const id = fieldId(name);
  return (
    <div className={`flex min-w-0 flex-col gap-1.5 ${wide ? "sm:col-span-2" : ""}`}>
      <label htmlFor={id} className="break-words text-sm font-medium text-foreground">
        {label}
        {required && (
          <span aria-hidden className="text-status-fail">
            {" *"}
          </span>
        )}
      </label>
      {children}
      {(hint || counter) && (
        <div className="flex items-start justify-between gap-3 text-xs text-muted">
          <span id={`${id}-hint`} className="min-w-0 break-words">
            {hint}
          </span>
          {counter && <span className="shrink-0 tabular-nums">{counter}</span>}
        </div>
      )}
      {error && (
        <p id={`${id}-error`} role="alert" className="break-words text-xs text-status-fail">
          {error}
        </p>
      )}
    </div>
  );
}

/**
 * Заявка на участие (ТЗ п.6). Окно на телефоне открывается во весь экран.
 *
 * Значения живут здесь, а не в окне: закрыли окно (нажали мимо) — введённое
 * остаётся; вдобавок черновик пишется в sessionStorage. Файлы не загружаются —
 * примеры работ это ссылки.
 */
export default function ApplicationForm({ open, onClose, initial, onDone }: Props) {
  const { t, i18n } = useTranslation("creators", { useSuspense: false });
  const [values, setValues] = useState<FormValues>(() => loadDraft() ?? valuesFromApplication(initial));
  /** До первой попытки отправить ошибок не показываем: человек ещё заполняет. */
  const [attempted, setAttempted] = useState(false);
  const [serverFields, setServerFields] = useState<Record<string, string>>({});
  const [submitError, setSubmitError] = useState<CrError | null>(null);
  const [busy, setBusy] = useState(false);
  const sending = useRef(false);
  // Окно открылось — фокус клавиатуры внутрь него, закрылось — обратно на кнопку.
  const formRef = useDialogFocus<HTMLFormElement>(open);

  const check = useMemo(
    () => (attempted ? validateApplication(normalizeValues(values)) : NOTHING),
    [attempted, values],
  );

  const issueText = (issue: FieldIssue): string => {
    switch (issue.kind) {
      case "required":
        return t("apply.errors.required", { defaultValue: "Заполните это поле" });
      case "too_long":
        return t("apply.errors.too_long", { defaultValue: "Не длиннее {{max}} символов", max: issue.max });
      case "url":
        return t("apply.errors.url", { defaultValue: "Ссылка должна начинаться с http:// или https://" });
      case "url_too_long":
        return t("apply.errors.url_too_long", { defaultValue: "Ссылка не длиннее {{max}} символов", max: issue.max });
      case "too_many_links":
        return t("apply.errors.too_many_links", { defaultValue: "Не больше {{max}} ссылок", max: issue.max });
      case "followers":
        return t("apply.errors.followers", { defaultValue: "Укажите целое число от 0" });
    }
  };

  /** Своя проверка важнее: она про то, что в поле сейчас; ответ сервера — про прошлую отправку. */
  const errorOf = (name: FieldName): string => {
    const issue = check.issues[name];
    if (issue) return issueText(issue);
    return serverFields[name] ? fieldErrorText(t, i18n.language, serverFields[name]) : "";
  };

  const change = (name: FieldName, value: string) => {
    const next = { ...values, [name]: value };
    setValues(next);
    saveDraft(next);
    if (serverFields[name]) {
      const rest = { ...serverFields };
      delete rest[name];
      setServerFields(rest);
    }
    if (submitError) setSubmitError(null);
  };

  /** То же для полей «по одной ссылке в строке». */
  const tidyLinks = () => {
    const next = normalizeValues(values);
    if (JSON.stringify(next) === JSON.stringify(values)) return;
    setValues(next);
    saveDraft(next);
  };

  const focusField = (name: FieldName | null) => {
    if (!name) return;
    try {
      document.getElementById(fieldId(name))?.focus();
    } catch {}
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (sending.current) return;

    const clean = normalizeValues(values);
    const result = validateApplication(clean);
    setValues(clean);
    setAttempted(true);
    setServerFields({});
    setSubmitError(null);
    if (!result.body) {
      focusField(firstField(Object.keys(result.issues)) ?? (result.linksMissing ? "instagram_url" : null));
      return;
    }

    // Черновик — до запроса: если сессия кончилась и человека уведёт на вход, заявка не пропадёт.
    saveDraft(clean);
    sending.current = true;
    setBusy(true);
    const res = await submitApplication({ ...result.body, lang: apiLang(i18n.language) });
    sending.current = false;
    setBusy(false);

    if (res.ok) {
      clearDraft();
      onDone({ kind: "submitted", application: res.data.application });
      return;
    }

    const error = res.error;
    if (error.code === "unauthorized") {
      // Сессия кончилась: черновик сохранён, после входа человек вернётся в форму.
      window.location.assign(SIGNIN_TO_APPLY);
      return;
    }
    if (STALE_CODES.has(error.code)) {
      // Программа выключена — заявка ещё может пригодиться; в остальных случаях черновик больше не нужен.
      if (error.code !== "disabled") clearDraft();
      onDone({ kind: "stale" });
      return;
    }
    if (error.code === "validation" && error.fields) {
      setServerFields(error.fields);
      focusField(firstField(Object.keys(error.fields)));
    }
    setSubmitError(error);
  };

  /** Общие свойства поля ввода. */
  const control = (name: FieldName) => {
    const invalid = Boolean(errorOf(name));
    const id = fieldId(name);
    return {
      id,
      name,
      value: values[name],
      disabled: busy,
      "aria-invalid": invalid || undefined,
      "aria-describedby": invalid ? `${id}-error` : undefined,
      className: `${INPUT} ${invalid ? "border-status-fail" : "border-border"}`,
    };
  };
  const urlControl = (name: FieldName) => ({
    ...control(name),
    type: "url" as const,
    inputMode: "url" as const,
    autoCapitalize: "none",
    autoCorrect: "off",
    spellCheck: false,
    placeholder: "https://",
    // Ушли из поля — дописываем https://, если адрес вставили без него.
    onBlur: () => {
      const tidy = normalizeUrl(values[name]);
      if (tidy !== values[name]) change(name, tidy);
    },
  });

  // Нет ни одной ссылки: то же сообщение, что и у сервера (links_required).
  const linksMissing = check.linksMissing || submitError?.code === "links_required";
  const linksText = errorText(t, { code: "links_required" });
  const count = (value: string) => `${value.length} / ${LIMITS.text}`;

  return (
    <Modal
      title={t("apply.form.title", { defaultValue: "Заявка на участие" })}
      open={open}
      onClose={onClose}
      size="lg"
      mobileFull
    >
      <form
        ref={formRef}
        tabIndex={-1}
        onSubmit={submit}
        noValidate
        className="grid grid-cols-1 gap-4 pb-1 pr-1 outline-none sm:grid-cols-2"
      >
        <FieldShell
          name="name"
          required
          label={t("apply.form.name", { defaultValue: "Имя" })}
          error={errorOf("name")}
        >
          <input
            {...control("name")}
            type="text"
            autoComplete="name"
            maxLength={LIMITS.name}
            aria-required
            onChange={(e) => change("name", e.target.value)}
          />
        </FieldShell>

        <FieldShell name="telegram" required label="Telegram" error={errorOf("telegram")}>
          <input
            {...control("telegram")}
            type="text"
            autoComplete="off"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            maxLength={LIMITS.telegram}
            placeholder="@username"
            aria-required
            onChange={(e) => change("telegram", e.target.value)}
          />
        </FieldShell>

        <FieldShell
          name="country"
          required
          label={t("apply.form.country", { defaultValue: "Страна" })}
          error={errorOf("country")}
        >
          <input
            {...control("country")}
            type="text"
            autoComplete="country-name"
            maxLength={LIMITS.country}
            aria-required
            onChange={(e) => change("country", e.target.value)}
          />
        </FieldShell>

        <FieldShell
          name="instagram_url"
          label={t("apply.form.instagram", { defaultValue: "Ссылка на Instagram" })}
          error={errorOf("instagram_url")}
        >
          <input {...urlControl("instagram_url")} onChange={(e) => change("instagram_url", e.target.value)} />
        </FieldShell>

        <FieldShell
          name="tiktok_url"
          label={t("apply.form.tiktok", { defaultValue: "Ссылка на TikTok" })}
          error={errorOf("tiktok_url")}
        >
          <input {...urlControl("tiktok_url")} onChange={(e) => change("tiktok_url", e.target.value)} />
        </FieldShell>

        <FieldShell
          name="youtube_url"
          label={t("apply.form.youtube", { defaultValue: "Ссылка на YouTube" })}
          error={errorOf("youtube_url")}
        >
          <input {...urlControl("youtube_url")} onChange={(e) => change("youtube_url", e.target.value)} />
        </FieldShell>

        <FieldShell
          name="other_links"
          wide
          label={t("apply.form.other_links", { defaultValue: "Другие соцсети" })}
          hint={t("apply.form.other_links_hint", { defaultValue: "По одной ссылке в строке" })}
          error={errorOf("other_links")}
        >
          <textarea
            {...control("other_links")}
            rows={2}
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            onChange={(e) => change("other_links", e.target.value)}
            onBlur={tidyLinks}
          />
        </FieldShell>

        <FieldShell
          name="followers"
          required
          wide
          label={t("apply.form.followers", { defaultValue: "Количество подписчиков" })}
          error={errorOf("followers")}
        >
          <input
            {...control("followers")}
            type="text"
            inputMode="numeric"
            autoComplete="off"
            maxLength={16}
            aria-required
            className={`${control("followers").className} sm:max-w-xs`}
            onChange={(e) => change("followers", e.target.value)}
          />
        </FieldShell>

        <FieldShell
          name="occupation"
          required
          wide
          label={t("apply.form.occupation", { defaultValue: "Чем вы занимаетесь" })}
          counter={count(values.occupation)}
          error={errorOf("occupation")}
        >
          <textarea
            {...control("occupation")}
            rows={3}
            maxLength={LIMITS.text}
            aria-required
            onChange={(e) => change("occupation", e.target.value)}
          />
        </FieldShell>

        <FieldShell
          name="motivation"
          required
          wide
          label={t("apply.form.motivation", { defaultValue: "Зачем вы хотите участвовать в программе" })}
          counter={count(values.motivation)}
          error={errorOf("motivation")}
        >
          <textarea
            {...control("motivation")}
            rows={3}
            maxLength={LIMITS.text}
            aria-required
            onChange={(e) => change("motivation", e.target.value)}
          />
        </FieldShell>

        <FieldShell
          name="samples"
          wide
          label={t("apply.form.samples", { defaultValue: "Примеры работ" })}
          hint={t("apply.form.samples_hint", { defaultValue: "Ссылки на ваши работы, по одной в строке" })}
          error={errorOf("samples")}
        >
          <textarea
            {...control("samples")}
            rows={3}
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            onChange={(e) => change("samples", e.target.value)}
            onBlur={tidyLinks}
          />
        </FieldShell>

        <div className="flex flex-col gap-3 sm:col-span-2">
          {linksMissing ? (
            <p
              role="alert"
              className="break-words rounded-xl border border-status-fail/40 bg-status-fail/10 px-3 py-2 text-sm text-foreground"
            >
              {linksText}
            </p>
          ) : (
            <p className="break-words text-xs text-muted">{linksText}</p>
          )}
          {submitError && submitError.code !== "links_required" && <ErrorNote error={submitError} />}
          <button type="submit" disabled={busy} aria-busy={busy} className={`${BTN_PRIMARY} w-full sm:w-auto sm:self-start`}>
            {busy
              ? t("apply.form.submitting", { defaultValue: "Отправляем…" })
              : t("apply.form.submit", { defaultValue: "Отправить заявку" })}
          </button>
        </div>
      </form>
    </Modal>
  );
}

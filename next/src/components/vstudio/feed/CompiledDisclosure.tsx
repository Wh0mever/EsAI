"use client";

import { memo, useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiCheck, FiChevronDown, FiCopy, FiLoader } from "react-icons/fi";
import { getTake } from "@/lib/vstudio/api";
import { errorText, issueText } from "@/lib/vstudio/errors";
import type { ShotInputJSON, TakeJSON, TakeLite, Uid, VsError } from "@/lib/vstudio/types";
import { VS_FOCUS, VS_LABEL, vx } from "../ui/skin";
import { inputRows } from "./feedLogic";

/**
 * serialized_prompt и request_body дубля пишутся при создании и дальше не
 * меняются — раз загруженное не спрашиваем повторно (листание карусели,
 * повторное раскрытие).
 */
const CACHE = new Map<Uid, TakeJSON>();
const CACHE_MAX = 60;

function remember(take: TakeJSON) {
  CACHE.set(take.uid, take);
  if (CACHE.size > CACHE_MAX) {
    const first = CACHE.keys().next().value;
    if (first) CACHE.delete(first);
  }
}

type Tr = (k: string, o?: Record<string, unknown>) => string;

/** Тихая кнопка-строка: раскрытие блока, «Копировать». На телефоне зона нажатия 44 px. */
const QUIET_BTN = `inline-flex min-h-11 cursor-pointer items-center gap-1.5 rounded-full px-2.5 text-xs font-medium text-muted transition-colors hover:bg-vs-ink/[0.07] hover:text-foreground md:min-h-8 ${VS_FOCUS}`;
/**
 * Блок «как это было сделано» — углубление в карточке. В тёмной теме оно темнее
 * карточки (затемнение), в светлой затемнять белое нельзя — выйдет грязь:
 * там это тёплый лоток (surface-2), а текст в нём лежит на белом листе.
 */
const WELL = "border-border bg-surface-2 dark:bg-black/25";
/** Текст «как есть»: промпт и тело запроса. */
const CODE_BOX = "overflow-auto rounded-lg border border-border bg-surface p-3 dark:bg-black/30";

function paramRows(t: Tr, take: TakeLite): Array<[string, string]> {
  const e = take.effective || {};
  const rows: Array<[string, string]> = [];
  if (e.duration != null) {
    rows.push([
      t("sent.param.duration", { defaultValue: "Длительность" }),
      t("shot.seconds", { defaultValue: "{{n}} с", n: e.duration }),
    ]);
  }
  if (e.resolution) rows.push([t("sent.param.resolution", { defaultValue: "Качество" }), e.resolution]);
  if (e.aspect_ratio) {
    rows.push([
      t("sent.param.aspect", { defaultValue: "Пропорции" }),
      e.aspect_ratio === "auto" ? t("shot.aspectAuto", { defaultValue: "Авто" }) : e.aspect_ratio,
    ]);
  }
  if (typeof e.generate_audio === "boolean") {
    rows.push([
      t("sent.param.audio", { defaultValue: "Звук" }),
      e.generate_audio ? t("sent.yes", { defaultValue: "да" }) : t("sent.no", { defaultValue: "нет" }),
    ]);
  }
  return rows;
}

function CopyButton({ text, label, done }: { text: string; label: string; done: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      /* буфер недоступен (http, запрет) — текст и так на экране */
    }
  };
  return (
    <button
      type="button"
      onClick={() => void copy()}
      // На телефоне кнопка выше строки заголовка: лишнее съедает отрицательный отступ.
      className={vx(QUIET_BTN, "-my-2 shrink-0 md:my-0")}
    >
      {copied ? <FiCheck className="text-status-ok" aria-hidden /> : <FiCopy aria-hidden />}
      {copied ? done : label}
    </button>
  );
}

export type CompiledDisclosureProps = {
  take: TakeLite;
  inputs: ShotInputJSON[];
};

/**
 * «Что ушло модели» (§4.8, §9.6): ровно тот текст, который получила модель
 * (serialized_prompt, целиком — без обрезки), режим, итоговые параметры,
 * какие материалы ушли и что «не учтено», предупреждения компилятора и
 * тело запроса. Грузится по раскрытию: GET takes/<uid>/.
 */
function CompiledDisclosure({ take, inputs }: CompiledDisclosureProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const tr = t as unknown as Tr;
  const panelId = useId();
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState<{ uid: Uid; data: TakeJSON | null; error: VsError | null } | null>(null);
  const [attempt, setAttempt] = useState(0);

  // Карусель может переключить дубль при открытом блоке: всё считаем от take.uid.
  const cached = CACHE.get(take.uid) ?? null;
  const shown = cached ?? (result && result.uid === take.uid ? result.data : null);
  const error = result && result.uid === take.uid ? result.error : null;
  const loading = open && !shown && !error;

  useEffect(() => {
    if (!open || CACHE.has(take.uid)) return;
    const uid = take.uid;
    let alive = true;
    void getTake(uid).then((res) => {
      if (res.ok) remember(res.data);
      // Пока ждали, карусель могла уйти на другой дубль — чужой ответ не показываем.
      if (alive) setResult({ uid, data: res.ok ? res.data : null, error: res.ok ? null : res.error });
    });
    return () => {
      alive = false;
    };
  }, [open, take.uid, attempt]);

  const retry = () => {
    setResult(null);
    setAttempt((n) => n + 1);
  };

  const rows = inputRows(inputs, take.dropped, null);
  const used = rows.filter((r) => !r.excluded);
  const excluded = rows.filter((r) => r.excluded);
  const params = paramRows(tr, take);
  const mode = shown?.mode || take.mode;
  const rowLabel = (slot: string, n: number | null) =>
    slot === "first_frame"
      ? tr("inputs.firstFrame", { defaultValue: "Первый кадр" })
      : slot === "last_frame"
        ? tr("inputs.lastFrame", { defaultValue: "Последний кадр" })
        : n
          ? `@Image ${n}`
          : "@Image —";

  return (
    // Подвал карточки: тонкая черта отделяет «как это было сделано» от самого кадра.
    <div className="-mx-3 -mb-2 flex flex-col border-t border-vs-ink/10 px-3 pt-1 sm:-mx-4 sm:-mb-1.5 sm:px-4 dark:border-vs-ink/[0.07]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        className={vx(QUIET_BTN, "-ml-2 w-fit")}
      >
        <FiChevronDown
          className={vx("transition-transform duration-200 motion-reduce:transition-none", open && "rotate-180")}
          aria-hidden
        />
        {t("run.actions.sent", { defaultValue: "Что ушло модели" })}
      </button>

      {open && (
        <div
          id={panelId}
          className={vx(WELL, "mb-2 mt-1 flex flex-col gap-4 rounded-xl border p-3 text-sm sm:mb-1.5 sm:p-4")}
        >
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-xs">
            <dt className="text-muted">{t("sent.modeTitle", { defaultValue: "Режим" })}</dt>
            <dd className="text-foreground">
              {t(`sent.mode.${mode}`, { defaultValue: MODE_RU[mode] || mode })}
            </dd>
            {params.map(([k, v]) => (
              <FragmentRow key={k} k={k} v={v} />
            ))}
          </dl>

          <section className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
              <h4 className={VS_LABEL}>
                {t("sent.prompt", { defaultValue: "Текст, который получила модель" })}
                {shown && (
                  <span className="ml-1.5 whitespace-nowrap font-normal normal-case tracking-normal">
                    {t("sent.chars", { defaultValue: "{{n}} симв.", n: shown.serialized_prompt.length })}
                  </span>
                )}
              </h4>
              {shown && shown.serialized_prompt && (
                <CopyButton
                  text={shown.serialized_prompt}
                  label={t("run.actions.copy", { defaultValue: "Копировать" })}
                  done={t("run.actions.copied", { defaultValue: "Скопировано" })}
                />
              )}
            </div>
            {loading && !shown ? (
              <p className="flex items-center gap-2 text-xs text-muted">
                <FiLoader className="animate-spin motion-reduce:animate-none" aria-hidden />
                {t("sent.loading", { defaultValue: "Загружаем…" })}
              </p>
            ) : error && !shown ? (
              <p className="flex flex-wrap items-center gap-2 text-xs text-status-fail">
                {errorText(t, error)}
                <button type="button" onClick={retry} className={vx(QUIET_BTN, "!text-foreground")}>
                  {t("feed.retry", { defaultValue: "Попробовать снова" })}
                </button>
              </p>
            ) : shown ? (
              <pre
                className={vx(CODE_BOX, "max-h-80 whitespace-pre-wrap break-words font-sans text-[13px] leading-relaxed text-foreground/90")}
              >
                {shown.serialized_prompt || "—"}
              </pre>
            ) : null}
          </section>

          <section className="flex flex-col gap-2">
            <h4 className={VS_LABEL}>{t("sent.inputs", { defaultValue: "Материалы" })}</h4>
            {used.length ? (
              <ul className="flex flex-col gap-1 text-xs text-foreground/90">
                {used.map((r) => (
                  <li key={r.key}>
                    {rowLabel(r.input.slot, r.n)}
                    {r.input.role ? <span className="text-muted"> — {r.input.role}</span> : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-muted">{t("sent.noInputs", { defaultValue: "Без фото — только текст" })}</p>
            )}
            {excluded.length > 0 && (
              <>
                <h5 className={vx(VS_LABEL, "mt-1.5")}>{t("sent.excluded", { defaultValue: "Не учтено" })}</h5>
                <ul className="flex flex-col gap-1 text-xs text-muted">
                  {excluded.map((r) => (
                    <li key={r.key}>
                      {rowLabel(r.input.slot, null)} —{" "}
                      {r.reason === "duplicate_frame"
                        ? t("sent.reason.duplicate_frame", { defaultValue: "Второй кадр в том же слоте — не отправлен" })
                        : r.reason === "excluded_by_user"
                          ? t("sent.reason.excluded_by_user", { defaultValue: "Не учитывается и не оплачивается" })
                          : t("sent.reason.other", { defaultValue: "Модель не получила этот материал" })}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>

          {take.warnings?.length > 0 && (
            <section className="flex flex-col gap-2">
              <h4 className={VS_LABEL}>{t("sent.warnings", { defaultValue: "Предупреждения" })}</h4>
              <ul className="flex list-disc flex-col gap-1 pl-4 text-xs text-status-wait">
                {take.warnings.map((w, k) => (
                  <li key={`${w.code}-${k}`}>{issueText(t, w, "warnings")}</li>
                ))}
              </ul>
            </section>
          )}

          {shown && shown.request_body && Object.keys(shown.request_body).length > 0 && (
            <details className="group text-xs">
              <summary
                className={vx(
                  "w-fit cursor-pointer select-none rounded-md py-1 text-muted transition-colors hover:text-foreground",
                  VS_FOCUS,
                )}
              >
                {t("sent.body", { defaultValue: "Технические подробности (тело запроса)" })}
              </summary>
              <pre className={vx(CODE_BOX, "mt-1.5 max-h-72 font-mono text-[11px] leading-snug text-muted")}>
                {JSON.stringify(shown.request_body, null, 2)}
              </pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

function FragmentRow({ k, v }: { k: string; v: string }) {
  return (
    <>
      <dt className="text-muted">{k}</dt>
      <dd className="text-foreground">{v}</dd>
    </>
  );
}

/** Русские названия режимов (ключи sent.mode.<mode>). */
const MODE_RU: Record<string, string> = {
  t2v: "Видео по тексту",
  i2v: "Видео с первого кадра",
  flf2v: "Видео между первым и последним кадром",
  r2v: "Видео по фото-референсам",
  r2v_pin: "Фото-референсы, первый кадр — одним из них",
  t2i: "Картинка по тексту",
  i2i: "Картинка по фото",
};

export default memo(CompiledDisclosure);

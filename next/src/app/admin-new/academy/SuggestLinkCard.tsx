"use client";

import { useId, useState } from "react";
import { FiExternalLink, FiSend } from "react-icons/fi";
import SuggestText from "@/components/academy/SuggestText";
import type { AcademySuggest } from "@/lib/academy/shared";
import { CARD, INPUT_LG, btn } from "../vstudio-showcase/parts";
import { classifySuggest, suggestPunycodeHost } from "./academyAdmin";

type Props = {
  /** Сохранённое значение; "" — под приглашением на сайте ничего нет. */
  value: string;
  /** Что из него показывает сайт — по ответу сервера; null — ничего. */
  saved: AcademySuggest | null;
  maxLength: number;
  /** Отправить значение ("" — убрать с сайта); вернуть текст отказа или null. */
  onSave: (raw: string) => Promise<string | null>;
};

/** Поле растёт с текстом: от 2 до 5 строк — больше строк сайт всё равно не покажет. */
const rowsFor = (value: string): number => Math.min(5, Math.max(2, value.split("\n").length));

/**
 * Что стоит под приглашением для авторов внизу /academy (ТЗ п.6, бриф F28): @username
 * или ссылка — кнопка «Предложить курс» на неё, e-mail — та же кнопка письмом, любой
 * другой текст — абзац без кнопки. Пусто — ничего, текст блока на сайте остаётся.
 * Страница монтирует карточку с key={значение}: после сохранения поле показывает то,
 * что записал сервер (@имя → https://t.me/имя).
 */
export default function SuggestLinkCard({ value, saved, maxLength, onSave }: Props) {
  const [draft, setDraft] = useState(value);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hintId = useId();

  const dirty = draft.trim() !== value;
  // Пока поле не трогали — показываем, что решил сервер; при правке — подсказку по его правилам.
  const check = dirty ? classifySuggest(draft, maxLength) : { ok: true as const, suggest: saved };

  const save = async (raw: string) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    const problem = await onSave(raw);
    setBusy(false);
    setError(problem);
  };

  return (
    <section className={`${CARD} flex flex-col gap-3 p-4`} aria-labelledby="academy-suggest-title">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="academy-suggest-title" className="flex items-center gap-2 text-base font-semibold">
          <FiSend className="h-4 w-4 text-accent" aria-hidden />
          Кнопка «Предложить курс»
        </h2>
        <span className="text-xs text-muted-2">{STATUS[saved?.kind ?? "none"]}</span>
      </div>
      <form
        noValidate
        className="flex flex-col gap-2 sm:flex-row sm:items-start"
        onSubmit={(e) => {
          e.preventDefault();
          void save(draft);
        }}
      >
        <textarea
          value={draft}
          rows={rowsFor(draft)}
          maxLength={maxLength + 50}
          disabled={busy}
          placeholder="@username, ссылка, e-mail или текст"
          aria-label="Кнопка «Предложить курс»: @username, ссылка, e-mail или текст"
          aria-describedby={hintId}
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            // Enter — новая строка текста; Ctrl/Cmd+Enter — сохранить, как в других полях панели.
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && dirty) {
              e.preventDefault();
              void save(draft);
            }
          }}
          className={`${INPUT_LG} min-h-11 min-w-0 flex-1 resize-none leading-relaxed`}
        />
        <div className="flex gap-2">
          <button type="submit" disabled={busy || !dirty} className={`${btn("primary", "lg")} min-h-11 flex-1 sm:flex-none`}>
            {busy ? "Сохраняю…" : "Сохранить"}
          </button>
          {value && (
            <button
              type="button"
              disabled={busy}
              onClick={() => void save("")}
              className={`${btn("danger", "lg")} min-h-11 flex-1 sm:flex-none`}
            >
              Убрать с сайта
            </button>
          )}
        </div>
      </form>
      <div id={hintId} className="flex flex-col gap-1.5 text-xs text-muted-2">
        {error ? (
          <p role="alert" className="text-status-fail">
            {error}
          </p>
        ) : !check.ok ? (
          <p className="text-status-wait">{check.error}</p>
        ) : (
          <Preview suggest={check.suggest} draft={dirty} />
        )}
        {!dirty && !error && (
          <p>
            Можно @username или t.me/…, ссылку, e-mail или любой текст до 5 строк — e-mail и ссылки в тексте станут
            кликабельными. Пусто — под приглашением ничего.
          </p>
        )}
      </div>
    </section>
  );
}

const STATUS: Record<AcademySuggest["kind"] | "none", string> = {
  url: "На сайте кнопка-ссылка",
  email: "На сайте кнопка-письмо",
  text: "На сайте текст без кнопки",
  none: "Пусто — под приглашением ничего нет",
};

/** «На сайте: …» — то же, что увидит посетитель; у текста — сам текст со ссылками, как на странице. */
function Preview({ suggest, draft }: { suggest: AcademySuggest | null; draft: boolean }) {
  const lead = draft ? "После сохранения на сайте:" : "На сайте:";
  const host = suggestPunycodeHost(suggest);
  if (!suggest) return <p>{lead} ничего не будет — только заголовок и приглашение.</p>;
  if (suggest.kind === "url") {
    return (
      <p className="flex flex-wrap items-center gap-x-2">
        <span>
          {lead} кнопка → ссылка{" "}
          <span className="font-mono text-muted [overflow-wrap:anywhere]">{suggest.text}</span>
          {host && (
            <>
              {" "}
              (сайт <span className="font-mono text-muted [overflow-wrap:anywhere]">{host}</span>)
            </>
          )}
        </span>
        <a
          href={suggest.href}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex min-h-9 items-center gap-1 text-accent hover:underline"
        >
          Проверить ссылку
          <FiExternalLink className="h-3.5 w-3.5" aria-hidden />
        </a>
      </p>
    );
  }
  if (suggest.kind === "email") {
    return (
      <p>
        {lead} кнопка → письмо на <span className="font-mono text-muted [overflow-wrap:anywhere]">{suggest.text}</span>
        {host && (
          <>
            {" "}
            (домен <span className="font-mono text-muted [overflow-wrap:anywhere]">{host}</span>)
          </>
        )}
        , адрес виден под кнопкой.
      </p>
    );
  }
  return (
    <>
      <p>{lead} текст под приглашением, без кнопки:</p>
      <SuggestText
        text={suggest.text}
        newTab="(откроется в новой вкладке)"
        className="whitespace-pre-line rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm text-foreground [overflow-wrap:anywhere]"
        linkClassName="text-accent underline underline-offset-2"
      />
    </>
  );
}

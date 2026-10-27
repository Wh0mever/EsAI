"use client";

import { useState } from "react";
import { FiExternalLink, FiSend } from "react-icons/fi";
import { CARD, INPUT_LG, btn } from "../vstudio-showcase/parts";
import { normalizeSuggestUrl } from "./academyAdmin";

type Props = {
  /** Сохранённая ссылка; "" — кнопки на сайте нет. */
  value: string;
  maxLength: number;
  /** Отправить ссылку ("" — убрать кнопку); вернуть текст отказа или null. */
  onSave: (raw: string) => Promise<string | null>;
};

/**
 * Ссылка кнопки «Предложить курс» внизу /academy (ТЗ п.6): обычно Telegram.
 * Нет ссылки — нет кнопки, текст блока на сайте остаётся. Страница монтирует
 * карточку с key={ссылка}: после сохранения поле показывает то, что записал
 * сервер (@имя → https://t.me/имя).
 */
export default function SuggestLinkCard({ value, maxLength, onSave }: Props) {
  const [draft, setDraft] = useState(value);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const preview = normalizeSuggestUrl(draft, maxLength);
  const dirty = draft.trim() !== value;

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
        <span className="text-xs text-muted-2">{value ? "Кнопка на сайте есть" : "Ссылки нет — кнопки на сайте нет"}</span>
      </div>
      <form
        noValidate
        className="flex flex-col gap-2 sm:flex-row sm:items-center"
        onSubmit={(e) => {
          e.preventDefault();
          void save(draft);
        }}
      >
        <input
          type="text"
          value={draft}
          maxLength={maxLength + 50}
          disabled={busy}
          placeholder="@username или https://t.me/username"
          aria-label="Ссылка кнопки «Предложить курс»"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          onChange={(e) => setDraft(e.target.value)}
          className={`${INPUT_LG} min-h-11 min-w-0 flex-1 font-mono`}
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
              Убрать кнопку
            </button>
          )}
        </div>
      </form>
      {error ? (
        <p role="alert" className="text-xs text-status-fail">
          {error}
        </p>
      ) : dirty && draft.trim() ? (
        <p className="text-xs text-muted-2">
          {preview.ok ? (
            <>
              Кнопка будет вести на <span className="font-mono text-muted">{preview.url}</span>
            </>
          ) : (
            <span className="text-status-wait">{preview.error}</span>
          )}
        </p>
      ) : (
        <p className="flex flex-wrap items-center gap-x-2 text-xs text-muted-2">
          <span>Можно @username, t.me/… или адрес сайта с https://. Пусто — кнопки на сайте нет, текст блока остаётся.</span>
          {value && (
            <a
              href={value}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex min-h-9 items-center gap-1 text-accent hover:underline"
            >
              Проверить ссылку
              <FiExternalLink className="h-3.5 w-3.5" aria-hidden />
            </a>
          )}
        </p>
      )}
    </section>
  );
}

"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { INPUT_LG, Preview, StartFrame, btn, chip, mediaFacts } from "./parts";
import {
  TITLE_MAX,
  addDefaults,
  titleForScenario,
  type AddForm,
  type Candidate,
  type Category,
} from "./showcaseAdmin";

/**
 * «В витрину»: какой сценарий карусели работа показывает, как она называется
 * и можно ли показывать её запрос.
 *
 * Окно своё, а не Modal из components/dialog: тот рисуется в document.body,
 * мимо обёртки data-theme="dark" панели, и при светлой теме сайта вышел бы
 * светлым. Монтируется только на время действия — поля каждый раз чистые.
 */
type Props = {
  candidate: Candidate;
  categories: Category[];
  /** null — добавлено (окно закроется), иначе текст отказа сервера. */
  onSubmit: (form: AddForm) => Promise<string | null>;
  onClose: () => void;
};

export default function AddDialog({ candidate, categories, onSubmit, onClose }: Props) {
  const [{ title, category, showPrompt }, setForm] = useState(() => addDefaults(candidate));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  // Окно закрываем, только если и нажали, и отпустили на затемнении: выделяя
  // название мышью, легко увести её за край окна — набранное терять нельзя.
  const pressedOutside = useRef(false);

  // Фокус: окно открылось — в поле названия, закрылось — обратно на кнопку
  // «В витрину». Иначе Tab ходит по карточкам под затемнением.
  useEffect(() => {
    const before = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const box = dialogRef.current;
    try {
      (box?.querySelector<HTMLElement>("input[type=text]") ?? box)?.focus({ preventScroll: true });
    } catch {}
    return () => {
      try {
        if (before?.isConnected) before.focus({ preventScroll: true });
      } catch {}
    };
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev || "";
    };
  }, [busy, onClose]);

  if (typeof document === "undefined") return null;

  const ready = title.trim() !== "" && category !== "";

  const submit = async () => {
    if (!ready || busy) return;
    setBusy(true);
    setError(null);
    const failure = await onSubmit({ title, category, showPrompt });
    setBusy(false);
    if (failure) setError(failure);
    else onClose();
  };

  return createPortal(
    <div
      data-theme="dark"
      className="fixed inset-0 z-[1100] flex items-end justify-center bg-black/80 text-foreground sm:items-center sm:p-4"
      onMouseDown={(e) => {
        pressedOutside.current = e.target === e.currentTarget;
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && pressedOutside.current && !busy) onClose();
      }}
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label="Добавить в витрину"
        className="flex max-h-[92dvh] w-full max-w-lg flex-col overflow-hidden rounded-t-2xl border border-border bg-surface outline-none sm:rounded-2xl"
      >
        <div className="border-b border-border px-5 py-4">
          <h3 className="text-base font-semibold">Добавить в витрину</h3>
          <div className="mt-1 truncate text-sm text-muted">
            {[candidate.modelName, mediaFacts(candidate), candidate.authorEmail].filter(Boolean).join(" · ")}
          </div>
        </div>

        <form
          className="flex min-h-0 flex-1 flex-col"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain px-5 py-4">
            <Preview media={candidate} className="rounded-xl" />

            <label className="block text-sm">
              <span className="text-muted">Название *</span>
              <input
                type="text"
                value={title}
                onChange={(e) => {
                  const typed = e.target.value;
                  setForm((prev) => ({ ...prev, title: typed }));
                }}
                maxLength={TITLE_MAX}
                placeholder="Например: Ночной город"
                className={`${INPUT_LG} mt-1.5 w-full`}
              />
              <span className="mt-1 block text-xs text-muted-2">
                Пустое поле заполнится названием сценария: им ролик и подписан в карусели.
              </span>
            </label>

            <div className="text-sm">
              <span className="text-muted">Сценарий *</span>
              <div role="group" aria-label="Сценарий" className="mt-1.5 flex flex-wrap gap-2">
                {categories.map((option) => (
                  <button
                    key={option.key}
                    type="button"
                    aria-pressed={category === option.key}
                    onClick={() =>
                      setForm((prev) => ({
                        ...prev,
                        category: option.key,
                        title: titleForScenario(prev.title, option.key, categories),
                      }))
                    }
                    className={chip(category === option.key)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="rounded-xl border border-border bg-surface-2 p-3">
              <label className="flex cursor-pointer items-start gap-2.5 text-sm">
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 shrink-0 accent-accent"
                  checked={showPrompt}
                  disabled={candidate.prompt === ""}
                  onChange={(e) => {
                    const checked = e.target.checked;
                    setForm((prev) => ({ ...prev, showPrompt: checked }));
                  }}
                />
                <span>
                  Показывать запрос
                  <span className="mt-0.5 block text-xs text-muted-2">
                    {candidate.prompt
                      ? "По запросу работает кнопка «Снять похожее». У работ с первым кадром станет виден и он."
                      : "У этого дубля нет текста запроса — показывать нечего."}
                  </span>
                </span>
              </label>
              {candidate.prompt && (
                <p className="mt-2 max-h-28 overflow-y-auto whitespace-pre-wrap break-words border-t border-border pt-2 text-xs text-muted">
                  {candidate.prompt}
                </p>
              )}
              {candidate.startFrame && (
                <div className="mt-2 flex items-center gap-3 border-t border-border pt-2">
                  <StartFrame src={candidate.startFrame} shown={showPrompt} size="lg" />
                  <p className="text-xs text-muted-2">
                    Первый кадр этого ролика. С галочкой «Показывать запрос» его увидят все посетители.
                  </p>
                </div>
              )}
            </div>

            {error && (
              <div
                role="alert"
                className="rounded-xl border border-status-fail/40 bg-status-fail/10 px-3 py-2 text-sm text-status-fail"
              >
                {error}
              </div>
            )}
          </div>

          <div className="flex justify-end gap-2 border-t border-border px-5 py-3">
            <button type="button" onClick={onClose} disabled={busy} className={btn("plain", "lg")}>
              Отмена
            </button>
            <button type="submit" disabled={!ready || busy} className={btn("primary", "lg")}>
              {busy ? "Добавляю…" : "Добавить"}
            </button>
          </div>
        </form>
      </div>
    </div>,
    document.body,
  );
}

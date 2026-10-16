"use client";

import { useEffect, useState, type ReactNode } from "react";
import { FiAlertTriangle, FiCheck, FiFilm, FiRefreshCw } from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";
import { Skeleton } from "../vstudio-showcase/parts";
import {
  DEFAULTS_PATH,
  RESET_BODY,
  allFromCode,
  draftFrom,
  durationOptions,
  effectiveText,
  errorText,
  findDefaultsModel,
  modelNote,
  parseDefaults,
  patchBody,
  pickModel,
  resolutionOptions,
  tripleText,
  type CartoonDefaults,
  type DefaultsTriple,
} from "./cartoonDefaults";

const INPUT =
  "min-h-10 rounded-lg bg-surface-2 border border-border px-3 py-2 text-sm text-foreground focus:border-accent outline-none disabled:opacity-60";
const SAVE_BTN =
  "rounded-lg bg-accent px-4 py-2 text-xs font-semibold text-on-accent transition-opacity hover:opacity-90 disabled:opacity-50";
const PLAIN_BTN =
  "rounded-lg border border-border bg-surface-2 px-3 py-2 text-xs font-semibold text-foreground transition-opacity hover:opacity-90 disabled:opacity-50";

function Header({ children }: { children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        <FiFilm className="h-4 w-4 text-accent" aria-hidden />
        <h2 className="text-base font-semibold">Мультстудия: по умолчанию</h2>
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

/**
 * «Мультстудия: по умолчанию» (просьба клиента 15.10.2026: по умолчанию —
 * Seedance 2.0 Mini в 480p, чтобы сцена стоила меньше). С какими моделью,
 * качеством и длительностью начинается новый мультфильм на сайте и в боте;
 * человек потом меняет их в доке студии. Пока выбранная модель выключена или не
 * умеет эту пару, новые мультфильмы снимаются как в сцене библиотеки — карточка
 * пишет это словами. Грузится сама: страница настроек её не ждёт.
 */
export default function CartoonDefaultsSection() {
  const [tick, setTick] = useState(0);
  const [loaded, setLoaded] = useState<{ tick: number; error: string | null } | null>(null);
  const [saved, setSaved] = useState<CartoonDefaults | null>(null);
  const [draft, setDraft] = useState<DefaultsTriple | null>(null);
  const [notes, setNotes] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [flash, setFlash] = useState(false);

  const loading = loaded?.tick !== tick;

  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await fetchData<unknown>(DEFAULTS_PATH, "GET", undefined, true);
      if (!alive) return;
      const data = res.ok ? parseDefaults(res.data) : null;
      if (data) {
        setSaved(data);
        setDraft(draftFrom(data));
      }
      setLoaded({ tick, error: data ? null : errorText(res, "Не удалось загрузить настройки мультстудии") });
    })();
    return () => {
      alive = false;
    };
  }, [tick]);

  if (loading && !saved) {
    return (
      <section className="rounded-2xl border border-border bg-surface p-5" aria-busy="true">
        <Header />
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
        </div>
      </section>
    );
  }

  if (!saved || !draft) {
    return (
      <section className="rounded-2xl border border-border bg-surface p-5">
        <Header />
        <p className="mt-3 text-sm text-status-fail">{loaded?.error || "Не удалось загрузить настройки мультстудии"}</p>
        <button type="button" onClick={() => setTick((t) => t + 1)} disabled={loading} className={`${PLAIN_BTN} mt-3`}>
          <FiRefreshCw className="mr-1.5 inline h-3.5 w-3.5" aria-hidden />
          {loading ? "Загрузка…" : "Повторить"}
        </button>
      </section>
    );
  }

  const body = patchBody(draft, saved);
  const dirty = Object.keys(body).length > 0;
  const model = findDefaultsModel(saved, draft.model);
  const fromCode = allFromCode(saved);

  const send = async (payload: Record<string, unknown>) => {
    setSaving(true);
    setSaveError(null);
    const res = await fetchData<unknown>(DEFAULTS_PATH, "PATCH", payload, true);
    setSaving(false);
    const data = res.ok ? parseDefaults(res.data) : null;
    if (!data) {
      setSaveError(errorText(res, "Не удалось сохранить настройки мультстудии"));
      return;
    }
    setSaved(data);
    setDraft(draftFrom(data));
    setNotes([]);
    setFlash(true);
    setTimeout(() => setFlash(false), 2000);
  };

  const save = () => {
    if (saving || !dirty) return;
    void send(body);
  };

  const reset = () => {
    setDraft(draftFrom(saved));
    setNotes([]);
    setSaveError(null);
  };

  const backToCode = () => {
    if (saving) return;
    if (!window.confirm(`Вернуть значения из кода: ${tripleText(saved, saved.codeDefaults)}?`)) return;
    void send({ ...RESET_BODY });
  };

  return (
    <section className="rounded-2xl border border-border bg-surface p-5">
      <Header>
        {flash && (
          <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-400">
            <FiCheck className="h-4 w-4" aria-hidden /> Сохранено
          </span>
        )}
        {dirty && (
          <button type="button" onClick={reset} disabled={saving} className={PLAIN_BTN}>
            Отменить
          </button>
        )}
        {dirty && (
          <button type="button" onClick={save} disabled={saving} className={SAVE_BTN}>
            {saving ? "Сохранение…" : "Сохранить"}
          </button>
        )}
      </Header>
      <p className="mt-1 text-xs text-muted-2">
        С какими моделью, качеством и длительностью начинается каждый новый мультфильм — на сайте и в боте.
        Человек может поменять их в доке внизу студии. Уже созданные мультфильмы не меняются.
      </p>

      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="cartoon-default-model" className="text-xs text-muted">
            Модель
          </label>
          <select
            id="cartoon-default-model"
            value={draft.model}
            onChange={(e) => {
              const next = pickModel(saved, draft, e.target.value);
              setDraft(next.draft);
              setNotes(next.notes);
            }}
            disabled={saving}
            className={INPUT}
          >
            {!model && <option value={draft.model}>{draft.model}</option>}
            {saved.models.map((m) => {
              const note = modelNote(m);
              return (
                <option key={m.id} value={m.id}>
                  {m.short}
                  {note ? ` — ${note}` : ""}
                </option>
              );
            })}
          </select>
          <span className="text-[11px] text-muted-2">
            Seedance Mini — самая дешёвая сцена. Модель включают в «Моделях».
          </span>
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="cartoon-default-resolution" className="text-xs text-muted">
            Качество
          </label>
          <select
            id="cartoon-default-resolution"
            value={draft.resolution}
            onChange={(e) => setDraft({ ...draft, resolution: e.target.value })}
            disabled={saving}
            className={INPUT}
          >
            {resolutionOptions(model, draft.resolution).map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <span className="text-[11px] text-muted-2">Выше качество — дороже сцена.</span>
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="cartoon-default-duration" className="text-xs text-muted">
            Длительность сцены
          </label>
          <select
            id="cartoon-default-duration"
            value={String(draft.duration)}
            onChange={(e) => setDraft({ ...draft, duration: Number(e.target.value) })}
            disabled={saving}
            className={INPUT}
          >
            {durationOptions(model, draft.duration).map((n) => (
              <option key={n} value={n}>
                {n} с
              </option>
            ))}
          </select>
          <span className="text-[11px] text-muted-2">Сцены библиотеки рассчитаны на 5 с.</span>
        </div>
      </div>

      {notes.length > 0 && (
        <div className="mt-3 space-y-0.5 text-xs text-status-wait" role="status">
          {notes.map((n) => (
            <p key={n}>{n}</p>
          ))}
        </div>
      )}

      <div className="mt-4 flex flex-col gap-2 border-t border-border pt-4 text-sm">
        <p className={saved.effective.source === "settings" ? "text-foreground" : "text-status-wait"}>{effectiveText(saved)}</p>
        {saved.warnings.map((w) => (
          <p key={w} className="flex items-start gap-1.5 text-xs text-status-wait">
            <FiAlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            {w}
          </p>
        ))}
        <div className="flex flex-wrap items-center gap-3 text-xs text-muted-2">
          <span>
            {fromCode
              ? `Сейчас действуют значения из кода: ${tripleText(saved, saved.codeDefaults)}.`
              : `Значения из кода: ${tripleText(saved, saved.codeDefaults)}.`}
          </span>
          {!fromCode && (
            <button type="button" onClick={backToCode} disabled={saving} className={PLAIN_BTN}>
              Вернуть значения из кода
            </button>
          )}
        </div>
      </div>

      {saveError && <p className="mt-3 text-sm text-status-fail">{saveError}</p>}
    </section>
  );
}

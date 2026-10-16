"use client";

import { useEffect, useState, type ReactNode } from "react";
import { FiCheck, FiRefreshCw, FiScissors } from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";
import { Skeleton } from "../vstudio-showcase/parts";
import {
  MAX_MERGE_PRICE,
  MERGE_SETTINGS_PATH,
  errorText,
  parseMergePrice,
  parsePriceInput,
  priceSummary,
  priceText,
  type MergePriceSettings,
} from "./mergePrice";

const INPUT =
  "min-h-10 w-32 rounded-lg bg-surface-2 border border-border px-3 py-2 text-sm text-foreground tabular-nums focus:border-accent outline-none disabled:opacity-60";
const SAVE_BTN =
  "rounded-lg bg-accent px-4 py-2 text-xs font-semibold text-on-accent transition-opacity hover:opacity-90 disabled:opacity-50";
const PLAIN_BTN =
  "rounded-lg border border-border bg-surface-2 px-3 py-2 text-xs font-semibold text-foreground transition-opacity hover:opacity-90 disabled:opacity-50";

function Header({ children }: { children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        <FiScissors className="h-4 w-4 text-accent" aria-hidden />
        <h2 className="text-base font-semibold">Склейка: цена</h2>
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}

/**
 * «Склейка: цена» — сколько кредитов стоит готовая склейка видео (/merge).
 * Списывается только за сохранённый ролик; 0 — бесплатно. Пусто и «Вернуть
 * цену из кода» — снова цена из кода (20 кр, цифра клиента). Карточка грузится
 * сама: страница настроек её не ждёт.
 */
export default function MergePriceSection() {
  const [tick, setTick] = useState(0);
  const [loaded, setLoaded] = useState<{ tick: number; error: string | null } | null>(null);
  const [saved, setSaved] = useState<MergePriceSettings | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [flash, setFlash] = useState(false);

  const loading = loaded?.tick !== tick;

  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await fetchData<unknown>(MERGE_SETTINGS_PATH, "GET", undefined, true);
      if (!alive) return;
      const data = res.ok ? parseMergePrice(res.data) : null;
      if (data) {
        setSaved(data);
        setDraft(String(data.price));
      }
      setLoaded({ tick, error: data ? null : errorText(res, "Не удалось загрузить цену склейки") });
    })();
    return () => {
      alive = false;
    };
  }, [tick]);

  if (loading && !saved) {
    return (
      <section className="rounded-2xl border border-border bg-surface p-5" aria-busy="true">
        <Header />
        <Skeleton className="mt-4 h-10 w-48" />
      </section>
    );
  }

  if (!saved) {
    return (
      <section className="rounded-2xl border border-border bg-surface p-5">
        <Header />
        <p className="mt-3 text-sm text-status-fail">{loaded?.error || "Не удалось загрузить цену склейки"}</p>
        <button type="button" onClick={() => setTick((t) => t + 1)} disabled={loading} className={`${PLAIN_BTN} mt-3`}>
          <FiRefreshCw className="mr-1.5 inline h-3.5 w-3.5" aria-hidden />
          {loading ? "Загрузка…" : "Повторить"}
        </button>
      </section>
    );
  }

  const parsed = parsePriceInput(draft);
  const dirty = draft.trim() !== String(saved.price);
  const inputError = dirty && !parsed.ok ? parsed.error : null;

  const send = async (value: number | null) => {
    setSaving(true);
    setSaveError(null);
    const res = await fetchData<unknown>(MERGE_SETTINGS_PATH, "PATCH", { price_credits: value }, true);
    setSaving(false);
    const data = res.ok ? parseMergePrice(res.data) : null;
    if (!data) {
      setSaveError(errorText(res, "Не удалось сохранить цену склейки"));
      return;
    }
    setSaved(data);
    setDraft(String(data.price));
    setFlash(true);
    setTimeout(() => setFlash(false), 2000);
  };

  const save = () => {
    if (saving || !dirty || !parsed.ok) return;
    void send(parsed.value);
  };

  const backToCode = () => {
    if (saving) return;
    if (!window.confirm(`Вернуть цену из кода: ${priceText(saved.defaultPrice)}?`)) return;
    void send(null);
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
          <button type="button" onClick={() => setDraft(String(saved.price))} disabled={saving} className={PLAIN_BTN}>
            Отменить
          </button>
        )}
        {dirty && (
          <button type="button" onClick={save} disabled={saving || !parsed.ok} className={SAVE_BTN}>
            {saving ? "Сохранение…" : "Сохранить"}
          </button>
        )}
      </Header>
      <p className="mt-1 text-xs text-muted-2">
        Сколько кредитов стоит склейка роликов в один на странице «Склейка видео». Кредиты резервируются при запуске, а
        списываются, только когда ролик готов. 0 — бесплатно. Новая цена действует примерно через 30 секунд.
      </p>

      <form
        className="mt-4 flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          save();
        }}
      >
        <div className="flex flex-col gap-1">
          <label htmlFor="merge-price" className="text-xs text-muted">
            Цена, кр
          </label>
          <input
            id="merge-price"
            type="text"
            inputMode="numeric"
            pattern="[0-9]*"
            maxLength={String(MAX_MERGE_PRICE).length}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            disabled={saving}
            aria-invalid={inputError ? true : undefined}
            aria-describedby={inputError ? "merge-price-error" : undefined}
            className={INPUT}
          />
        </div>
        <span className="pb-2.5 text-xs text-muted-2">за готовую склейку</span>
      </form>
      {inputError && (
        <p id="merge-price-error" className="mt-2 text-xs text-status-fail">
          {inputError}
        </p>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-border pt-4 text-sm">
        <p className={saved.overridden ? "text-foreground" : "text-muted"}>{priceSummary(saved)}</p>
        {saved.overridden && (
          <button type="button" onClick={backToCode} disabled={saving} className={PLAIN_BTN}>
            Вернуть цену из кода
          </button>
        )}
      </div>

      {saveError && <p className="mt-3 text-sm text-status-fail">{saveError}</p>}
    </section>
  );
}

"use client";

import clsx from "clsx";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { FiEyeOff, FiSlash, FiUser } from "react-icons/fi";
import { getCharacters, hideCharacter, type CharacterJSON } from "@/lib/creative/api";
import { errorText } from "@/lib/creative/errors";
import type { Ct } from "@/lib/creative/text";
import { CREATIVE_PATH } from "@/lib/nav/paths";
import type { VsError } from "@/lib/vstudio/types";
import { BTN_GHOST, CARD, FOCUS, Skeleton } from "./ui";

/** Свои постоянные персонажи (GET characters/): список для выбора и для управления. */
export function useCharacters(enabled: boolean) {
  const [state, setState] = useState<{ tick: number; items: CharacterJSON[] | null; error: VsError | null } | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    void getCharacters().then((r) => {
      if (alive) setState(r.ok ? { tick, items: r.data, error: null } : { tick, items: null, error: r.error });
    });
    return () => {
      alive = false;
    };
  }, [enabled, tick]);
  const reload = useCallback(() => setTick((x) => x + 1), []);
  const current = state && state.tick === tick ? state : null;
  // Пока перечитываем — показываем прежний список, без мигания скелетом.
  const items = current?.items ?? state?.items ?? null;
  return { items, error: current?.error ?? null, loading: enabled && !state, reload };
}

const STATUS_TONE: Record<CharacterJSON["status"], string> = {
  training: "bg-[#F5C518]/20 text-[var(--accent-text)]",
  ready: "bg-status-ok/15 text-status-ok",
  failed: "bg-status-fail/15 text-status-fail",
};

function Thumb({ ch, className }: { ch: CharacterJSON; className?: string }) {
  return ch.thumb ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={ch.thumb} alt="" loading="lazy" className={clsx("object-cover", className)} />
  ) : (
    <span className={clsx("grid place-items-center bg-surface-2 text-muted", className)}>
      <FiUser aria-hidden="true" className="size-5" />
    </span>
  );
}

/** Инструмент 8: выбрать готового персонажа (или без него). */
export function CharacterPicker({
  value,
  onChange,
  disabled,
  guest,
  ct,
  labelId,
}: {
  value: string;
  onChange: (uid: string) => void;
  disabled?: boolean;
  guest?: boolean;
  ct: Ct;
  labelId: string;
}) {
  const { items, error, loading, reload } = useCharacters(!guest);
  if (guest) return <p className="rounded-xl border border-dashed border-border px-4 py-3 text-sm text-muted">{ct("run.signin_hint")}</p>;
  if (loading) return <Skeleton className="h-14" />;
  if (error) {
    return (
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span role="alert" className="text-status-fail">
          {errorText(ct, error)}
        </span>
        <button type="button" className={BTN_GHOST} onClick={reload}>
          {ct("run.catalog_retry")}
        </button>
      </div>
    );
  }
  const ready = (items || []).filter((c) => c.status === "ready");
  return (
    <div className="space-y-2">
      <div role="radiogroup" aria-labelledby={labelId} className="flex flex-wrap gap-2">
        <button
          type="button"
          role="radio"
          aria-checked={!value}
          disabled={disabled}
          onClick={() => onChange("")}
          className={clsx(
            "inline-flex min-h-11 items-center gap-2 rounded-xl border-2 px-3 text-sm font-medium",
            !value ? "border-[#F5C518] bg-[#F5C518]/10" : "border-border bg-background hover:border-[#F5C518]/50",
            FOCUS,
          )}
        >
          <FiSlash aria-hidden="true" className="size-4 text-muted" />
          {ct("run.none_character")}
        </button>
        {ready.map((c) => (
          <button
            key={c.uid}
            type="button"
            role="radio"
            aria-checked={value === c.uid}
            disabled={disabled}
            onClick={() => onChange(c.uid)}
            className={clsx(
              "inline-flex min-h-11 items-center gap-2 rounded-xl border-2 py-1 pl-1 pr-3 text-sm font-medium",
              value === c.uid ? "border-[#F5C518] bg-[#F5C518]/10" : "border-border bg-background hover:border-[#F5C518]/50",
              FOCUS,
            )}
          >
            <Thumb ch={c} className="size-9 rounded-lg" />
            <span className="max-w-[10rem] truncate">{c.name || "—"}</span>
          </button>
        ))}
      </div>
      {!ready.length && (
        <p className="text-xs text-muted">
          {ct("char.none_ready")}{" "}
          <Link href={`${CREATIVE_PATH}/consistent-character`} className="font-medium text-[var(--accent-text)] underline-offset-2 hover:underline">
            {ct("char.create_link")}
          </Link>
        </p>
      )}
    </div>
  );
}

/** Инструмент 10: «Мои персонажи» — статус обучения и «Скрыть». */
export function CharacterList({ ct, reloadKey }: { ct: Ct; reloadKey: number }) {
  const [hiding, setHiding] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const headRef = useRef<HTMLHeadingElement>(null);
  const { items, error, loading, reload } = useCharacters(true);
  const [seenKey, setSeenKey] = useState(reloadKey);
  if (seenKey !== reloadKey) {
    // Работа персонажа закончилась — перечитать список.
    setSeenKey(reloadKey);
    reload();
  }

  // Пока кто-то обучается — перечитываем список раз в 20 с (видимая вкладка).
  const training = Boolean(items?.some((c) => c.status === "training"));
  useEffect(() => {
    if (!training) return;
    const id = setInterval(() => {
      if (document.visibilityState === "visible") reload();
    }, 20_000);
    return () => clearInterval(id);
  }, [training, reload]);

  const hide = async (c: CharacterJSON) => {
    if (!window.confirm(ct("char.hide_confirm", { name: c.name || "—" }))) return;
    setHiding(c.uid);
    const r = await hideCharacter(c.uid);
    setHiding(null);
    if (r.ok) {
      setMessage(ct("char.hidden"));
      // Строка с кнопкой исчезнет — фокус на заголовок списка, а не в начало страницы.
      headRef.current?.focus();
      reload();
    } else {
      setMessage(errorText(ct, r.error));
    }
  };

  return (
    <section className={clsx(CARD, "p-4 sm:p-5")} aria-labelledby="cs-chars">
      <h2 id="cs-chars" ref={headRef} tabIndex={-1} className="text-base font-bold outline-none">
        {ct("char.title")}
      </h2>
      <p className="sr-only" aria-live="polite">
        {message}
      </p>
      {loading ? (
        <div className="mt-3 space-y-2">
          <Skeleton className="h-14" />
          <Skeleton className="h-14" />
        </div>
      ) : error ? (
        <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
          <span role="alert" className="text-status-fail">
            {errorText(ct, error)}
          </span>
          <button type="button" className={BTN_GHOST} onClick={reload}>
            {ct("works.retry")}
          </button>
        </div>
      ) : !items?.length ? (
        <p className="mt-2 text-sm text-muted">{ct("char.empty")}</p>
      ) : (
        <>
        {training && <p className="mt-2 text-xs text-muted">{ct("run.character_training")}</p>}
        <ul className="mt-3 divide-y divide-border">
          {items.map((c) => (
            <li key={c.uid} className="flex items-center gap-3 py-2.5">
              <Thumb ch={c} className="size-12 shrink-0 rounded-xl" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{c.name || "—"}</p>
                <span className={clsx("mt-0.5 inline-block rounded-full px-2 py-0.5 text-[11px] font-medium", STATUS_TONE[c.status])}>
                  {ct(`char.status.${c.status}`)}
                </span>
              </div>
              {c.status === "ready" && (
                <Link href={`${CREATIVE_PATH}/text-to-image?character=${c.uid}`} className={clsx(BTN_GHOST, "hidden sm:inline-flex")}>
                  {ct("run.character_use")}
                </Link>
              )}
              <button
                type="button"
                onClick={() => void hide(c)}
                disabled={hiding === c.uid}
                className={clsx("grid size-10 place-items-center rounded-xl text-muted hover:bg-surface-2 hover:text-foreground", FOCUS)}
                aria-label={`${ct("char.hide")}: ${c.name || "—"}`}
                title={ct("char.hide")}
              >
                <FiEyeOff aria-hidden="true" className="size-4" />
              </button>
            </li>
          ))}
        </ul>
        </>
      )}
    </section>
  );
}

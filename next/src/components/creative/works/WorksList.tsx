"use client";

import clsx from "clsx";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { FiAlertTriangle, FiChevronDown, FiFilm, FiImage, FiRotateCcw, FiUser } from "react-icons/fi";
import { getJobs, isOpen, type JobJSON } from "@/lib/creative/api";
import { errorText, jobErrorText } from "@/lib/creative/errors";
import type { Ct } from "@/lib/creative/text";
import { toolById } from "@/lib/creative/tools";
import { CREATIVE_PATH } from "@/lib/nav/paths";
import type { VsError } from "@/lib/vstudio/types";
import { JobFiles } from "@/components/creative/run/JobView";
import { BTN_GHOST, CARD, FOCUS, Skeleton, Spinner } from "@/components/creative/run/ui";

/**
 * «Мои работы» (GET jobs/?tool=&page=): новые сверху, «Показать ещё» по 20.
 *
 * Пока в первой странице есть незаконченные работы — раз в 10 с перечитываем
 * её и подменяем строки по uid (скрытая вкладка не опрашивает). Список грузится
 * только после монтирования: сервер и первый кадр браузера рисуют скелет.
 */
const POLL_MS = 10_000;

type State = {
  items: JobJSON[];
  page: number;
  hasMore: boolean;
  error: VsError | null;
  loaded: boolean;
};

const EMPTY: State = { items: [], page: 0, hasMore: false, error: null, loaded: false };

/** Свежая первая страница поверх уже загруженного: новые — вперёд, известные — обновить. */
function mergeFirst(prev: JobJSON[], fresh: JobJSON[]): JobJSON[] {
  const byUid = new Map(fresh.map((j) => [j.uid, j]));
  const known = new Set(prev.map((j) => j.uid));
  const added = fresh.filter((j) => !known.has(j.uid));
  return [...added, ...prev.map((j) => byUid.get(j.uid) ?? j)];
}

const LOCALES: Record<string, string> = { ru: "ru-RU", en: "en-GB", kg: "ky-KG" };

function formatDate(iso: string | null, lang: string): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "";
  try {
    return new Intl.DateTimeFormat(LOCALES[lang.slice(0, 2)] || "ru-RU", {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(t));
  } catch {
    return new Date(t).toLocaleString();
  }
}

export type WorksListProps = {
  /** только работы этого инструмента; без него — все */
  tool?: string;
  ct: Ct;
  lang: string;
  /** меняется — список перечитывается (закончилась работа на странице) */
  reloadKey?: number;
  /** «Повторить с этими настройками» на странице инструмента */
  onRepeat?: (job: JobJSON) => void;
  /** подписывать инструмент у каждой работы (общий список) */
  showTool?: boolean;
  /** id заголовка секции для aria-labelledby списка */
  labelledBy?: string;
};

export default function WorksList({ tool, ct, lang, reloadKey = 0, onRepeat, showTool, labelledBy }: WorksListProps) {
  const [state, setState] = useState<State & { tool?: string; key: number }>({ ...EMPTY, tool, key: reloadKey });
  const [loadingMore, setLoadingMore] = useState(false);
  const [tick, setTick] = useState(0);

  // Смена фильтра или reloadKey — начинаем заново (без мигания: старое видно до ответа).
  const stale = state.tool !== tool || state.key !== reloadKey;
  if (stale) setState((s) => ({ ...s, tool, key: reloadKey, ...(s.tool !== tool ? EMPTY : {}) }));

  useEffect(() => {
    let alive = true;
    void getJobs({ tool }).then((r) => {
      if (!alive) return;
      setState((s) => {
        if (s.tool !== tool) return s;
        if (!r.ok) return { ...s, error: r.error, loaded: true };
        // Первая загрузка — как есть; повтор — слить с уже показанными страницами.
        const items = s.page > 1 ? mergeFirst(s.items, r.data.items) : r.data.items;
        return { ...s, items, page: Math.max(1, s.page), hasMore: s.page > 1 ? s.hasMore : r.data.has_more, error: null, loaded: true };
      });
    });
    return () => {
      alive = false;
    };
  }, [tool, reloadKey, tick]);

  // Незаконченные работы — тихий опрос первой страницы.
  const anyOpen = state.items.some((j) => isOpen(j.status));
  useEffect(() => {
    if (!anyOpen) return;
    const id = setInterval(() => {
      if (document.visibilityState === "visible") setTick((x) => x + 1);
    }, POLL_MS);
    return () => clearInterval(id);
  }, [anyOpen]);

  const retry = useCallback(() => {
    setState((s) => ({ ...s, error: null, loaded: false }));
    setTick((x) => x + 1);
  }, []);

  const more = async () => {
    if (loadingMore) return;
    setLoadingMore(true);
    const next = state.page + 1;
    const r = await getJobs({ tool, page: next });
    setLoadingMore(false);
    setState((s) => {
      if (s.tool !== tool) return s;
      if (!r.ok) return { ...s, error: r.error };
      const known = new Set(s.items.map((j) => j.uid));
      return { ...s, items: [...s.items, ...r.data.items.filter((j) => !known.has(j.uid))], page: next, hasMore: r.data.has_more, error: null };
    });
  };

  if (!state.loaded && !state.items.length) {
    return (
      <div className="grid grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-busy="true" aria-label={ct("works.loading")}>
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} className="h-28" />
        ))}
      </div>
    );
  }

  if (state.error && !state.items.length) {
    return (
      <div className={clsx(CARD, "flex flex-wrap items-center gap-3 p-4 text-sm")}>
        <span role="alert" className="text-status-fail">
          {state.error.code === "creative_disabled" ? ct("works.closed") : `${ct("works.load_error")} ${errorText(ct, state.error)}`}
        </span>
        {state.error.code !== "creative_disabled" && (
          <button type="button" className={BTN_GHOST} onClick={retry}>
            {ct("works.retry")}
          </button>
        )}
      </div>
    );
  }

  if (!state.items.length) {
    return <p className={clsx(CARD, "p-5 text-sm text-muted")}>{tool ? ct("works.empty_tool") : ct("works.empty")}</p>;
  }

  return (
    <div className="space-y-4">
      <ul className="grid grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-labelledby={labelledBy} aria-busy={stale || undefined}>
        {state.items.map((job) => (
          <li key={job.uid} className="min-w-0">
            <WorkCard job={job} ct={ct} lang={lang} showTool={showTool} onRepeat={onRepeat} />
          </li>
        ))}
      </ul>
      {state.error && (
        <p role="alert" className="text-sm text-status-fail">
          {errorText(ct, state.error)}
        </p>
      )}
      {state.hasMore && (
        <button type="button" className={BTN_GHOST} onClick={() => void more()} disabled={loadingMore} aria-busy={loadingMore}>
          {loadingMore && <Spinner />}
          {ct("works.more")}
        </button>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Одна работа                                                         */
/* ------------------------------------------------------------------ */

const STATUS_TONE: Record<string, string> = {
  done: "bg-status-ok/15 text-status-ok",
  failed: "bg-status-fail/15 text-status-fail",
  nsfw: "bg-status-fail/15 text-status-fail",
  lost: "bg-status-fail/15 text-status-fail",
  canceled: "bg-surface-3 text-muted",
};

function summary(job: JobJSON): string {
  const p = job.params_public;
  for (const k of ["prompt", "brief", "name"]) {
    const v = p[k];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return "";
}

function WorkCard({
  job,
  ct,
  lang,
  showTool,
  onRepeat,
}: {
  job: JobJSON;
  ct: Ct;
  lang: string;
  showTool?: boolean;
  onRepeat?: (job: JobJSON) => void;
}) {
  const [open, setOpen] = useState(false);
  const meta = toolById(job.tool);
  const toolName = ct(`tools.${job.tool}.name`) === `tools.${job.tool}.name` ? meta?.name || job.tool : ct(`tools.${job.tool}.name`);
  const running = isOpen(job.status);
  const done = job.status === "done";
  const first = job.results[0];
  const thumb = first ? (first.mime.startsWith("video") ? first.poster : first.url) : null;
  const text = summary(job);
  const detailsId = `work-${job.uid}`;
  const hasDetails = (done && job.results.length > 0) || (!done && !running);

  return (
    <article className={clsx(CARD, "flex h-full flex-col overflow-hidden")}>
      <div className="flex gap-3 p-3">
        <span className="relative grid size-20 shrink-0 place-items-center overflow-hidden rounded-xl bg-surface-2 text-muted">
          {thumb ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={thumb} alt="" loading="lazy" decoding="async" className="size-full object-cover" />
          ) : running ? (
            <Spinner className="size-5" />
          ) : !done ? (
            <FiAlertTriangle aria-hidden="true" className="size-5" />
          ) : job.kind === "character" ? (
            <FiUser aria-hidden="true" className="size-5" />
          ) : job.kind === "video" ? (
            <FiFilm aria-hidden="true" className="size-5" />
          ) : (
            <FiImage aria-hidden="true" className="size-5" />
          )}
          {first?.mime.startsWith("video") && (
            <span aria-hidden="true" className="absolute bottom-1 right-1 grid size-5 place-items-center rounded-full bg-black/70 text-white">
              <FiFilm className="size-3" />
            </span>
          )}
          {job.results.length > 1 && (
            <span className="absolute bottom-1 left-1 rounded-md bg-black/70 px-1.5 text-[11px] font-semibold text-white">{job.results.length}</span>
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className={clsx("inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold", running ? "bg-[#F5C518]/20 text-[var(--accent-text)]" : STATUS_TONE[job.status] || "bg-surface-3 text-muted")}>
              {ct(`status.${job.status}`)}
            </span>
            <time dateTime={job.created_at || undefined} className="text-xs text-muted">
              {formatDate(job.created_at, lang)}
            </time>
          </div>
          {showTool &&
            (meta ? (
              <Link href={`${CREATIVE_PATH}/${meta.id}`} className={clsx("mt-1 block truncate text-sm font-semibold hover:underline", FOCUS)}>
                {toolName}
              </Link>
            ) : (
              <p className="mt-1 truncate text-sm font-semibold">{toolName}</p>
            ))}
          {text && <p className="mt-1 line-clamp-2 text-sm text-muted">{text}</p>}
          {done && job.credits_charged > 0 && <p className="mt-1 text-xs text-muted">{ct("run.charged", { n: job.credits_charged })}</p>}
        </div>
      </div>

      {open && hasDetails && (
        <div id={detailsId} className="border-t border-border p-3">
          {done ? (
            <JobFiles job={job} toolName={toolName} ct={ct} compact />
          ) : (
            <p className="text-sm text-status-fail">{jobErrorText(ct, job)}</p>
          )}
        </div>
      )}

      <div className="mt-auto flex flex-wrap gap-2 border-t border-border p-2.5">
        {hasDetails && (
          <button
            type="button"
            className={clsx(BTN_GHOST, "min-h-9 px-3")}
            aria-expanded={open}
            aria-controls={open ? detailsId : undefined}
            onClick={() => setOpen((x) => !x)}
          >
            <FiChevronDown aria-hidden="true" className={clsx("size-4 transition-transform motion-reduce:transition-none", open && "rotate-180")} />
            {open ? ct("works.hide_details") : ct("works.details")}
          </button>
        )}
        {running && <span className="inline-flex min-h-9 items-center px-1 text-xs text-muted">{ct("run.wait_note")}</span>}
        {onRepeat && !running && job.kind !== "character" && (
          <button type="button" className={clsx(BTN_GHOST, "min-h-9 px-3")} onClick={() => onRepeat(job)}>
            <FiRotateCcw aria-hidden="true" className="size-4" />
            {ct("works.repeat")}
          </button>
        )}
        {!onRepeat && meta && !running && (
          <Link href={`${CREATIVE_PATH}/${meta.id}?repeat=${job.uid}`} className={clsx(BTN_GHOST, "min-h-9 px-3")}>
            <FiRotateCcw aria-hidden="true" className="size-4" />
            {ct("works.repeat")}
          </Link>
        )}
      </div>
    </article>
  );
}

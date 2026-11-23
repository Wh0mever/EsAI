"use client";

import clsx from "clsx";
import Link from "next/link";
import { useEffect, useState } from "react";
import { FiAlertTriangle, FiCheckCircle, FiClock, FiRotateCcw, FiPlus, FiUser } from "react-icons/fi";
import SaveMediaButton from "@/components/ui/SaveMediaButton";
import { isOpen, type JobFile, type JobJSON } from "@/lib/creative/api";
import { jobErrorText } from "@/lib/creative/errors";
import type { Ct } from "@/lib/creative/text";
import { CREATIVE_PATH } from "@/lib/nav/paths";
import { BTN_GHOST, BTN_GOLD, CARD, FOCUS, Spinner, clock, resultFilename } from "./ui";

/** Секунды с момента created_at, раз в секунду (только в браузере, после монтирования). */
function useElapsed(since: string | null, running: boolean): number | null {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    if (!running) return;
    const tick = () => setNow(Date.now());
    const first = setTimeout(tick, 0);
    const id = setInterval(tick, 1000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [running]);
  if (now == null || !since) return null;
  const t = Date.parse(since);
  return Number.isFinite(t) ? Math.max(0, (now - t) / 1000) : null;
}

/** Ожидание: статус, таймер, «можно закрыть страницу», отмена в очереди. */
export function JobWaiting({
  job,
  etaS,
  onCancel,
  canceling,
  ct,
}: {
  job: JobJSON;
  etaS: number | null;
  onCancel: () => void;
  canceling: boolean;
  ct: Ct;
}) {
  const elapsed = useElapsed(job.created_at, isOpen(job.status));
  const slow = etaS != null && etaS > 0 && elapsed != null && elapsed > etaS * 1.5;
  const share = etaS && elapsed != null ? Math.min(0.95, elapsed / etaS) : null;
  return (
    <div className={clsx(CARD, "p-5 sm:p-6")}>
      <div className="flex items-start gap-3">
        <span className="grid size-10 shrink-0 place-items-center rounded-full bg-[#F5C518]/15 text-[var(--accent-text)]">
          <Spinner className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-bold">{ct("run.wait_title")}</h2>
          <p className="mt-0.5 text-sm text-muted" role="status" aria-live="polite">
            {ct(`status.${job.status}`)}
          </p>
        </div>
      </div>
      <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-surface-3" aria-hidden="true">
        <div
          className={clsx("h-full rounded-full bg-[#F5C518] transition-[width] duration-1000", share == null && "w-1/3 animate-pulse motion-reduce:animate-none")}
          style={share != null ? { width: `${Math.max(6, share * 100)}%` } : undefined}
        />
      </div>
      <dl className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        {elapsed != null && (
          <div className="flex items-center gap-1">
            <FiClock aria-hidden="true" className="size-3.5" />
            <dt className="sr-only">{ct("run.elapsed", { time: "" })}</dt>
            <dd className="tabular-nums">{ct("run.elapsed", { time: clock(elapsed) })}</dd>
          </div>
        )}
        {etaS != null && etaS > 0 && <div>{etaS < 60 ? ct("run.eta_short") : ct("run.eta", { min: Math.round(etaS / 60) })}</div>}
      </dl>
      {slow && <p className="mt-2 text-xs text-muted">{ct("run.slow")}</p>}
      <p className="mt-4 rounded-xl bg-surface-2 px-3.5 py-2.5 text-sm">{ct("run.wait_note")}</p>
      {job.status === "queued" && (
        <button type="button" className={clsx(BTN_GHOST, "mt-4")} onClick={onCancel} disabled={canceling} aria-busy={canceling}>
          {canceling ? ct("run.canceling") : ct("run.cancel_job")}
        </button>
      )}
    </div>
  );
}

/** Файлы результата: сетка картинок или плеер с обложкой; у каждого — «Скачать». */
export function JobFiles({ job, toolName, ct, compact }: { job: JobJSON; toolName: string; ct: Ct; compact?: boolean }) {
  const files = job.results;
  if (!files.length) return null;
  const video = files.find((f) => f.mime.startsWith("video"));
  if (video) return <VideoResult file={video} job={job} ct={ct} />;
  return (
    <ul className={clsx("grid gap-3", files.length === 1 ? "grid-cols-1" : "grid-cols-2", compact && "gap-2")}>
      {files.map((f, i) => (
        <li key={f.url} className="group relative overflow-hidden rounded-xl border border-border bg-background">
          <a href={f.url} target="_blank" rel="noopener" className={clsx("block", FOCUS)} title={ct("run.open_result")}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={f.url}
              alt={ct("run.result_image_alt", { tool: toolName, n: i + 1 })}
              loading="lazy"
              decoding="async"
              width={f.w || undefined}
              height={f.h || undefined}
              className={clsx("h-auto w-full object-contain", files.length > 1 && "aspect-square object-cover")}
            />
          </a>
          <div className="flex items-center justify-end gap-2 border-t border-border px-2 py-1.5">
            <SaveMediaButton
              url={f.url}
              filename={resultFilename(job.tool, job.uid, i, f.mime, f.url)}
              label={files.length > 1 ? ct("run.download_n", { n: i + 1 }) : ct("run.download")}
              className={clsx("inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-[#F5C518] px-3 text-xs font-semibold text-black hover:bg-[#ffd633]", FOCUS)}
              iconClassName="size-3.5"
            >
              {ct("run.download")}
            </SaveMediaButton>
          </div>
        </li>
      ))}
    </ul>
  );
}

function VideoResult({ file, job, ct }: { file: JobFile; job: JobJSON; ct: Ct }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-black">
      <video
        src={file.url}
        poster={file.poster || undefined}
        controls
        playsInline
        preload="metadata"
        className="max-h-[70vh] w-full bg-black object-contain"
      />
      <div className="flex items-center justify-end gap-2 border-t border-white/10 bg-surface px-3 py-2">
        <SaveMediaButton
          url={file.url}
          filename={resultFilename(job.tool, job.uid, 0, file.mime, file.url)}
          label={ct("run.download")}
          className={clsx("inline-flex min-h-10 items-center gap-1.5 rounded-lg bg-[#F5C518] px-4 text-sm font-semibold text-black hover:bg-[#ffd633]", FOCUS)}
          iconClassName="size-4"
        >
          {ct("run.download")}
        </SaveMediaButton>
      </div>
    </div>
  );
}

/** Итог работы на странице инструмента: файлы или причина отказа + «Ещё раз». */
export function JobOutcome({
  job,
  toolName,
  onAgain,
  onNew,
  ct,
}: {
  job: JobJSON;
  toolName: string;
  onAgain: () => void;
  onNew: () => void;
  ct: Ct;
}) {
  const done = job.status === "done";
  return (
    <div className={clsx(CARD, "p-5 sm:p-6")}>
      <div className="flex items-start gap-3">
        <span
          className={clsx(
            "grid size-10 shrink-0 place-items-center rounded-full",
            done ? "bg-status-ok/15 text-status-ok" : "bg-status-fail/15 text-status-fail",
          )}
        >
          {done ? <FiCheckCircle aria-hidden="true" className="size-5" /> : <FiAlertTriangle aria-hidden="true" className="size-5" />}
        </span>
        {/* Итог объявляет постоянная live-область RunForm: вставленная вместе с текстом область не зачитывается. */}
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-bold">{done ? ct("run.done_title") : ct("run.failed_title")}</h2>
          <p className="mt-0.5 text-sm text-muted">
            {done ? (job.credits_charged ? ct("run.charged", { n: job.credits_charged }) : ct(`status.${job.status}`)) : jobErrorText(ct, job)}
          </p>
        </div>
      </div>

      {done && job.kind === "character" && (
        <div className="mt-4 flex items-start gap-3 rounded-xl bg-surface-2 p-3.5 text-sm">
          <FiUser aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <div className="space-y-2">
            <p>{ct("run.character_ready")}</p>
            <Link href={`${CREATIVE_PATH}/text-to-image`} className="font-semibold text-[var(--accent-text)] underline-offset-2 hover:underline">
              {ct("run.character_use")}
            </Link>
          </div>
        </div>
      )}

      {done && job.kind !== "character" && (
        <div className="mt-4">
          <JobFiles job={job} toolName={toolName} ct={ct} />
        </div>
      )}

      <div className="mt-5 flex flex-wrap gap-2">
        <button type="button" className={BTN_GOLD} onClick={onAgain}>
          <FiRotateCcw aria-hidden="true" className="size-4" />
          {done ? ct("run.again") : ct("run.try_again")}
        </button>
        <button type="button" className={BTN_GHOST} onClick={onNew}>
          <FiPlus aria-hidden="true" className="size-4" />
          {ct("run.new")}
        </button>
      </div>
    </div>
  );
}

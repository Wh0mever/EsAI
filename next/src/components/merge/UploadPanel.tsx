"use client";

import { useEffect, useId, useRef, useState, type DragEvent, type RefObject } from "react";
import { useTranslation } from "react-i18next";
import { FiAlertCircle, FiLoader, FiRefreshCw, FiUploadCloud, FiX } from "react-icons/fi";
import { apiLang } from "@/lib/apiLang";
import { VS_BTN_GHOST, VS_BTN_LINK, VS_FOCUS, vx } from "@/components/vstudio/ui/skin";
import { CS_NOTE_FAIL } from "@/components/studio/ui/cartoonSkin";
import { fillText, type TextSpec } from "./mergeLogic";
import { MERGE_ERROR_RU } from "./mergeText";
import { formatMb, numberLocale, uploadShare, uploadsFull } from "./uploadLogic";
import type { MergeUploadLimits, MergeUploadUsage } from "./mergeTypes";
import type { UploadState } from "./useMerge";

/**
 * «Мои файлы»: загрузить своё видео — кнопкой (на телефоне откроется
 * галерея) или перетаскиванием файла на компьютере. Пока файл идёт — полоска
 * с процентами и «Отменить»; отказ — здесь же, рядом с кнопкой, а если файл
 * не виноват (связь, сбой, лимит) — с «Повторить». Под ней — пределы: форматы,
 * сколько своих видео в склейке, размер, длина и занятое место.
 */

export type UploadPanelProps = {
  limits: MergeUploadLimits;
  usage: MergeUploadUsage | null;
  upload: UploadState | null;
  error: TextSpec | null;
  /** Отказ не из-за самого файла: можно отправить тот же ещё раз. */
  canRetry: boolean;
  onFile: (file: File) => void;
  onRetry: () => void;
  onCancel: () => void;
  onDismissError: () => void;
  /** id кнопки «Загрузить видео»: сюда возвращается фокус после удаления видео. */
  buttonId: string;
};

export default function UploadPanel({
  limits,
  usage,
  upload,
  error,
  canRetry,
  onFile,
  onRetry,
  onCancel,
  onDismissError,
  buttonId,
}: UploadPanelProps) {
  const { t, i18n } = useTranslation("vstudio", { useSuspense: false });
  const inputRef = useRef<HTMLInputElement>(null);
  const progressRef = useRef<HTMLDivElement>(null);
  const [over, setOver] = useState(false);
  /** Бросили несколько файлов — берём первый и говорим об этом. */
  const [note, setNote] = useState("");
  const nameId = useId();
  const locale = numberLocale(apiLang(i18n.language));
  const busy = upload !== null;
  const phase = upload?.phase ?? null;
  const seen = useRef({ busy, phase });
  // Десять файлов из десяти: новая загрузка получила бы отказ сразу — говорим это до выбора.
  const full = !busy && uploadsFull(usage, limits);

  // Кнопка сменилась полоской (и обратно), «Отменить» пропал после 100 % — фокус
  // не должен упасть в начало страницы. Только если он и правда потерян.
  useEffect(() => {
    if (seen.current.busy === busy && seen.current.phase === phase) return;
    seen.current = { busy, phase };
    const focused = document.activeElement;
    if (focused && focused !== document.body) return;
    if (busy) progressRef.current?.focus({ preventScroll: true });
    else document.getElementById(buttonId)?.focus({ preventScroll: true });
  }, [busy, phase, buttonId]);

  const take = (files: FileList | null | undefined) => {
    const file = files && files.length > 0 ? files[0] : null;
    if (!file || upload || full) return;
    setNote(
      files && files.length > 1
        ? t("merge.upload.onlyFirst", {
            defaultValue: "Видео загружаются по одному: взято «{{name}}». Остальные добавьте после него.",
            name: file.name,
          })
        : "",
    );
    onFile(file);
  };

  // Перетаскивание — только файлов: текст или ссылку со страницы зона не ловит.
  const withFiles = (e: DragEvent<HTMLDivElement>) => Array.from(e.dataTransfer.types).includes("Files");

  const onDragOver = (e: DragEvent<HTMLDivElement>) => {
    if (!withFiles(e)) return;
    e.preventDefault();
    const closed = Boolean(upload) || full;
    e.dataTransfer.dropEffect = closed ? "none" : "copy";
    if (!over && !closed) setOver(true);
  };

  const onDragLeave = (e: DragEvent<HTMLDivElement>) => {
    const next = e.relatedTarget;
    if (next instanceof Node && e.currentTarget.contains(next)) return;
    setOver(false);
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    if (!withFiles(e)) return;
    e.preventDefault();
    setOver(false);
    take(e.dataTransfer.files);
  };

  const errorText = error ? (error.key ? t(error.key, { defaultValue: error.ru, ...error.params }) : fillText(error.ru, error.params)) : "";
  const closeLabel = t("merge.closeError", { defaultValue: "Скрыть" });
  const fullText = t("merge.err.upload_quota", { defaultValue: MERGE_ERROR_RU.upload_quota });
  // Диктору — смена этапа, а не каждый процент. Область живёт, пока открыта панель:
  // первое сообщение («Проверяю файл…») не теряется в только что появившейся области.
  const said = !upload
    ? ""
    : upload.phase === "checking"
      ? t("merge.upload.checking", { defaultValue: "Проверяю файл…" })
      : upload.phase === "processing"
        ? t("merge.upload.processing", { defaultValue: "Проверяю видео — это несколько секунд…" })
        : t("merge.upload.sendingSr", { defaultValue: "Загружаю видео" });

  return (
    <div className="flex flex-col gap-2.5">
      <div
        onDragEnter={onDragOver}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        className={vx(
          "flex min-h-[132px] flex-col items-center justify-center gap-2 rounded-2xl border border-dashed px-4 py-5 text-center transition-colors motion-reduce:transition-none",
          over ? "border-vs-accent/70 bg-accent/[0.08]" : "border-vs-ink/15",
        )}
      >
        {upload ? (
          <UploadProgress upload={upload} nameId={nameId} onCancel={onCancel} boxRef={progressRef} />
        ) : (
          <>
            <FiUploadCloud className={vx("size-6", full ? "text-muted-2" : "text-vs-accent")} aria-hidden="true" />
            {full ? (
              <p id={`${buttonId}-full`} className="max-w-xs text-sm leading-snug text-status-fail">
                {fullText}
              </p>
            ) : (
              <p className="max-w-xs text-sm leading-snug text-muted">
                <span className="hidden pointer-fine:inline">
                  {t("merge.upload.drop", { defaultValue: "Перетащите видео сюда или выберите файл" })}
                </span>
                <span className="pointer-fine:hidden">
                  {t("merge.upload.pick", { defaultValue: "Видео из галереи или из файлов" })}
                </span>
              </p>
            )}
            <button
              id={buttonId}
              type="button"
              onClick={() => {
                if (!full) inputRef.current?.click();
              }}
              aria-disabled={full || undefined}
              aria-describedby={full ? `${buttonId}-full` : undefined}
              className={vx(VS_BTN_GHOST, "mt-0.5", full && "!cursor-not-allowed opacity-60")}
            >
              <FiUploadCloud className={full ? undefined : "text-vs-accent"} aria-hidden="true" />
              {t("merge.upload.button", { defaultValue: "Загрузить видео" })}
            </button>
          </>
        )}
        {/* На телефоне accept с типами видео открывает галерею, а не только файлы. */}
        <input
          ref={inputRef}
          type="file"
          accept={limits.accept}
          tabIndex={-1}
          aria-hidden="true"
          className="sr-only"
          onChange={(e) => {
            take(e.currentTarget.files);
            // Тот же файл ещё раз (после отказа или удаления) — снова событие change.
            e.currentTarget.value = "";
          }}
        />
      </div>

      <div className="flex flex-col gap-0.5 text-xs leading-snug text-muted-2">
        <p>
          {t("merge.upload.limits", {
            defaultValue: "MP4, MOV или WebM · до {{n}} своих видео в склейке · до {{mb}} МБ · до {{sec}} с",
            n: limits.max_per_project,
            mb: limits.max_mb,
            sec: limits.max_duration_s,
          })}
        </p>
        {usage && (
          <p className={usage.files >= usage.max_files ? "text-status-fail" : undefined}>
            {t("merge.upload.usage", {
              defaultValue: "Загружено: {{files}} из {{maxFiles}} · {{used}} из {{maxMb}} МБ · хранятся {{days}} дн.",
              files: usage.files,
              maxFiles: usage.max_files,
              used: formatMb(usage.bytes, locale),
              maxMb: formatMb(usage.max_bytes, locale),
              days: limits.retention_days,
            })}
          </p>
        )}
        {note && <p className="break-words text-muted">{note}</p>}
      </div>

      {error && (
        <div role="alert" className={vx(CS_NOTE_FAIL, "flex items-start gap-3")}>
          <FiAlertCircle className="mt-0.5 shrink-0" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <p className="break-words">{errorText}</p>
            {canRetry && !upload && (
              <button
                type="button"
                onClick={onRetry}
                className={vx(
                  "mt-1 inline-flex min-h-11 cursor-pointer items-center gap-1.5 rounded-lg font-semibold underline-offset-4 hover:underline md:min-h-8",
                  VS_FOCUS,
                )}
              >
                <FiRefreshCw aria-hidden="true" />
                {t("merge.upload.retry", { defaultValue: "Повторить" })}
              </button>
            )}
          </div>
          <button
            type="button"
            onClick={onDismissError}
            aria-label={closeLabel}
            title={closeLabel}
            className={vx(
              "relative -my-1 -mr-1.5 grid size-8 shrink-0 cursor-pointer place-items-center rounded-full transition-colors hover:bg-status-fail/15 before:absolute before:-inset-1.5",
              VS_FOCUS,
            )}
          >
            <FiX aria-hidden="true" />
          </button>
        </div>
      )}
      <p className="sr-only" role="status" aria-live="polite">
        {said}
      </p>
    </div>
  );
}

/**
 * Ход загрузки одной строкой — для ярлыка «Мои файлы» и переключателя вида на
 * телефоне, когда сама панель не на экране: «42 %», «проверка», «ошибка».
 */
export function useUploadBadge(upload: UploadState | null, failed: boolean): { text: string; failed: boolean } | null {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  if (upload) {
    return {
      text:
        upload.phase === "upload"
          ? t("merge.upload.badgePct", { defaultValue: "{{pct}} %", pct: upload.pct })
          : t("merge.upload.badgeChecking", { defaultValue: "проверка" }),
      failed: false,
    };
  }
  return failed ? { text: t("merge.upload.badgeFailed", { defaultValue: "ошибка" }), failed: true } : null;
}

function UploadProgress({
  upload,
  nameId,
  onCancel,
  boxRef,
}: {
  upload: UploadState;
  nameId: string;
  onCancel: () => void;
  boxRef: RefObject<HTMLDivElement | null>;
}) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { phase, pct } = upload;
  const share = phase === "checking" ? 0 : uploadShare(pct, phase);
  const status =
    phase === "checking"
      ? t("merge.upload.checking", { defaultValue: "Проверяю файл…" })
      : phase === "processing"
        ? t("merge.upload.processing", { defaultValue: "Проверяю видео — это несколько секунд…" })
        : t("merge.upload.sending", { defaultValue: "Загружаю… {{pct}} %", pct });

  return (
    // tabIndex — сюда ставится фокус, когда кнопка «Загрузить видео» сменилась полоской.
    <div ref={boxRef} tabIndex={-1} className="flex w-full flex-col gap-2 text-left focus:outline-none">
      <div className="flex min-w-0 items-center gap-2">
        <p id={nameId} className="min-w-0 flex-1 truncate text-[13px] font-medium text-foreground" title={upload.name}>
          {upload.name}
        </p>
        {phase !== "processing" && (
          <button type="button" onClick={onCancel} className={vx(VS_BTN_LINK, "shrink-0 !px-2")}>
            <FiX aria-hidden="true" />
            {t("merge.upload.cancel", { defaultValue: "Отменить" })}
          </button>
        )}
      </div>
      <div
        role="progressbar"
        aria-labelledby={nameId}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(share * 100)}
        aria-valuetext={status}
        className="h-1.5 w-full overflow-hidden rounded-full bg-vs-ink/10"
      >
        <div
          className="h-full rounded-full bg-vs-accent transition-[width] duration-300 motion-reduce:transition-none"
          style={{ width: `${share * 100}%` }}
        />
      </div>
      <p className="flex items-center gap-1.5 text-xs tabular-nums text-muted" aria-hidden="true">
        {phase !== "upload" && <FiLoader className="shrink-0 animate-spin motion-reduce:animate-none" />}
        {status}
      </p>
    </div>
  );
}

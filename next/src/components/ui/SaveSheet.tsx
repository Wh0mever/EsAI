"use client";

import { useEffect, useId, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { FiCheck, FiCopy, FiDownload, FiExternalLink, FiLoader, FiRefreshCw, FiX } from "react-icons/fi";
import { trackFunnel } from "@/tools/funnel";
import {
  envLabel,
  errName,
  fileFallback,
  mediaKind,
  openableUrl,
  sameOriginMediaPath,
  saveLinkFor,
  sheetMode,
  type SaveDiagResult,
  type SaveEnv,
  type SaveStage,
  type SaveStep,
  type SheetMode,
} from "@/tools/saveEnv";
import {
  canShareFileNow,
  downloadBlob,
  followMedia,
  holdMedia,
  mediaEventMeta,
  readSaveEnv,
  shareFile,
  toFile,
  type MediaProgress,
  type SheetStart,
} from "@/tools/saveMedia";
import { fileGone, httpStatusOf } from "./saveSheetLogic";

/**
 * Шторка «Сохранить видео/фото» — следующий шаг, когда первое нажатие «Скачать»
 * не открыло системное окно сразу (tools/saveMedia): файл качался дольше жеста,
 * окно отказало, его нет во встроенном браузере или файл не скачался.
 *
 * Раньше в этих случаях телефон уходил на сам файл, и человек видел тёмную
 * страницу со значком загрузки. Здесь файл догружается с прогрессом, а кнопка
 * «Сохранить видео» открывает окно синхронно в нажатии — жест свежий, файл уже
 * в памяти. Во встроенных браузерах (Telegram, Instagram) — путь в Safari через
 * страницу /save, которой не нужен вход, и запасное «Скачать файл».
 *
 * SavePanel — содержимое шторки; её же без шторки показывает страница /save.
 */

type ClientInfo = { env: SaveEnv; origin: string };

const noSubscribe = () => () => {};
let _client: ClientInfo | null = null;

// Среда за сессию не меняется; один объект — иначе useSyncExternalStore
// считал бы каждый вызов новым состоянием.
function clientSnapshot(): ClientInfo {
  if (!_client) _client = { env: readSaveEnv().env, origin: window.location.origin };
  return _client;
}

function useClientInfo(): ClientInfo | null {
  return useSyncExternalStore(noSubscribe, clientSnapshot, () => null);
}

const BTN =
  "inline-flex min-h-12 w-full cursor-pointer items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold transition-colors motion-reduce:transition-none disabled:cursor-wait disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/80 focus-visible:ring-offset-2 focus-visible:ring-offset-surface";
const BTN_PRIMARY = `${BTN} bg-accent text-on-accent hover:bg-accent-strong`;
const BTN_SECONDARY = `${BTN} border border-border text-foreground hover:bg-surface-2`;

type Phase = "loading" | "ready" | "error";

function mb(bytes: number, lang: string): string {
  return new Intl.NumberFormat(lang === "en" ? "en" : "ru", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(bytes / 1048576);
}

function sendEvent(meta: ReturnType<typeof mediaEventMeta>): void {
  if (meta) trackFunnel("media_save", meta);
}

export function SavePanel({
  url,
  filename,
  start,
  page = false,
  onSaved,
}: {
  url: string;
  filename: string;
  start: SheetStart;
  /** Страница /save: файл открыт по ссылке, а не из шторки. */
  page?: boolean;
  onSaved?: () => void;
}) {
  const { t, i18n } = useTranslation("common");
  const client = useClientInfo();
  const kind = mediaKind(filename, url);
  const video = kind === "video";
  const { diag } = start;
  // На компьютере страница /save просто отдаёт ссылку на файл — качать его в память незачем.
  const direct = page && client !== null && !client.env.handheld;

  const [phase, setPhase] = useState<Phase>(start.failed ? "error" : "loading");
  const [run, setRun] = useState(start.failed ? 0 : 1);
  const [progress, setProgress] = useState<MediaProgress>({ done: 0, total: 0 });
  const [blob, setBlob] = useState<Blob | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [canShare, setCanShare] = useState<boolean | null>(null);
  const [lastErr, setLastErr] = useState(start.reason);
  const [http, setHttp] = useState<number | null>(start.http ?? null);
  // После отказа окна в самой шторке второе нажатие не поможет — показываем запасной путь.
  const [forced, setForced] = useState<SheetMode | null>(null);
  const [busy, setBusy] = useState(false);
  const [copy, setCopy] = useState<"idle" | "copied" | "manual">("idle");

  // Файл держится в памяти, пока открыта шторка; закрыли — выбрасываем.
  useEffect(() => holdMedia(url), [url]);

  useEffect(() => {
    if (!run || direct) return;
    let alive = true;
    const follow = followMedia(url, (p) => {
      if (alive) setProgress(p);
    });
    follow.blob.then(
      (b) => {
        if (!alive) return;
        const f = toFile(b, filename);
        setBlob(b);
        setFile(f);
        setCanShare(canShareFileNow(f));
        setPhase("ready");
      },
      (e) => {
        if (!alive) return;
        const name = errName(e) || "other";
        setLastErr(name);
        setHttp(httpStatusOf(e));
        setPhase("error");
        sendEvent(
          mediaEventMeta({
            url,
            filename,
            step: "sheet",
            result: "error",
            err: name,
            stage: "fetch",
            canShareFile: null,
            blob: null,
            diag,
          }),
        );
      },
    );
    return () => {
      alive = false;
      follow.stop();
    };
  }, [url, filename, run, direct, diag]);

  const report = (step: SaveStep, result: SaveDiagResult, err: string, stage: SaveStage) =>
    sendEvent(mediaEventMeta({ url, filename, step, result, err, stage, canShareFile: canShare, blob, diag }));

  const retry = () => {
    setPhase("loading");
    setProgress({ done: 0, total: 0 });
    setForced(null);
    setRun((r) => r + 1);
  };

  const onShare = () => {
    if (!file || busy || !client) return;
    setBusy(true);
    // Окно открывается здесь же, без await перед вызовом: жест ещё действует.
    shareFile(file)
      .then(
        () => {
          report("sheet_share", "saved", "", "share");
          onSaved?.();
        },
        (e) => {
          const name = errName(e) || "other";
          if (name === "AbortError") {
            report("sheet_share", "cancelled", name, "share");
            return;
          }
          report("sheet_share", "error", name, "share");
          setLastErr(name);
          setForced(sheetMode(client.env, false, name));
        },
      )
      .finally(() => setBusy(false));
  };

  const filePath = client ? sameOriginMediaPath(url, client.origin) : null;
  const saveLink = client ? saveLinkFor(url, filename, client.origin) : null;
  const absLink = client && saveLink ? `${client.origin}${saveLink}` : "";

  const onCopy = () => {
    if (!absLink) return;
    const done = (ok: boolean) => {
      setCopy(ok ? "copied" : "manual");
      report("sheet_copy", ok ? "copied" : "error", ok ? "" : "CopyFailed", "copy");
    };
    try {
      const pending = navigator.clipboard?.writeText(absLink);
      if (!pending) {
        done(false);
        return;
      }
      pending.then(
        () => done(true),
        () => done(false),
      );
    } catch {
      done(false);
    }
  };

  const ios = client?.env.os === "ios";
  const saveLabel = video
    ? t("media.sheet.save_video", { defaultValue: "Сохранить видео" })
    : t("media.sheet.save_image", { defaultValue: "Сохранить фото" });
  const mode: SheetMode = direct
    ? "files"
    : forced ?? (client ? sheetMode(client.env, canShare, lastErr) : "files");

  // Путь к файлу, когда окна нет: после сбоя загрузки «Повторить» при постоянной
  // ошибке (вместо файла страница, чужой адрес без CORS) падает так же.
  const fallback = client
    ? fileFallback({ filePath, url, origin: client.origin, os: client.env.os, hasBlob: blob !== null })
    : "none";
  const openHref = fallback === "open" && client ? openableUrl(url, client.origin) : null;

  const fileLink = filePath ? (
    <div className="flex flex-col gap-1.5">
      <a
        href={filePath}
        download={filename}
        onClick={() => report("sheet_files", "downloaded", "", "download")}
        className={mode === "files" && phase !== "error" ? BTN_PRIMARY : BTN_SECONDARY}
      >
        <FiDownload aria-hidden />
        {t("media.sheet.file_btn", { defaultValue: "Скачать файл" })}
      </a>
      <p className="text-xs leading-relaxed text-muted">
        {!ios
          ? t("media.sheet.file_hint_other", { defaultValue: "Файл появится в «Загрузках»." })
          : video
            ? t("media.sheet.file_hint_video", {
                defaultValue: "Файл появится в «Файлы» → «Загрузки». Откройте его там → «Поделиться» → «Сохранить видео».",
              })
            : t("media.sheet.file_hint_image", {
                defaultValue:
                  "Файл появится в «Файлы» → «Загрузки». Откройте его там → «Поделиться» → «Сохранить изображение».",
              })}
      </p>
    </div>
  ) : null;

  // Чужой адрес без CORS: файл открывается во вкладке (не на iPhone — там это тёмная страница).
  const openLink = openHref ? (
    <a href={openHref} target="_blank" rel="noopener noreferrer" className={BTN_SECONDARY}>
      <FiExternalLink aria-hidden />
      {t("media.sheet.open_file", { defaultValue: "Открыть файл" })}
    </a>
  ) : null;

  // Чужой адрес, а файл уже в памяти: сохранить его оттуда (компьютер, Android).
  const blobLink =
    fallback === "blob" && blob ? (
      <div className="flex flex-col gap-1.5">
        <button
          type="button"
          onClick={() => {
            downloadBlob(blob, filename);
            report("sheet_files", "downloaded", "", "download");
          }}
          className={BTN_PRIMARY}
        >
          <FiDownload aria-hidden />
          {t("media.sheet.file_btn", { defaultValue: "Скачать файл" })}
        </button>
        <p className="text-xs leading-relaxed text-muted">
          {t("media.sheet.file_hint_other", { defaultValue: "Файл появится в «Загрузках»." })}
        </p>
      </div>
    ) : null;

  const preparing = t("media.sheet.preparing", { defaultValue: "Готовим файл…" });
  const progressText = (done: number) =>
    t("media.sheet.progress", {
      defaultValue: "Готовим файл… {{done}} из {{total}} МБ",
      done: mb(done, i18n.language),
      total: mb(progress.total, i18n.language),
    });

  let body;
  if (phase === "error" && !direct && fileGone(http)) {
    // Файла больше нет: «Повторить» упадёт так же, «Скачать файл» откроет страницу ошибки.
    body = (
      <p role="alert" className="text-sm leading-relaxed text-foreground">
        {t("media.sheet.gone", { defaultValue: "Файл больше недоступен: его удалили или истёк срок хранения." })}
      </p>
    );
  } else if (phase === "error" && !direct) {
    body = (
      <div className="flex flex-col gap-3">
        <p role="alert" className="text-sm leading-relaxed text-foreground">
          {t("media.sheet.failed", {
            defaultValue: "Не удалось загрузить файл. Проверьте интернет и попробуйте ещё раз.",
          })}
        </p>
        <button type="button" onClick={retry} className={BTN_PRIMARY}>
          <FiRefreshCw aria-hidden />
          {t("media.sheet.retry", { defaultValue: "Повторить" })}
        </button>
        {fileLink || openLink}
      </div>
    );
  } else if (phase === "loading" && !direct) {
    const pct = progress.total > 0 ? Math.min(100, Math.round((progress.done * 100) / progress.total)) : 0;
    // Читалке — раз в четверть: строка на экране меняется на каждом куске файла.
    const quarter = progress.total > 0 ? Math.floor(pct / 25) * 25 : 0;
    body = (
      <div className="flex flex-col gap-2">
        <p aria-hidden className="flex items-center gap-2 text-sm text-muted">
          <FiLoader aria-hidden className="shrink-0 animate-spin motion-reduce:animate-none" />
          {progress.total > 0 ? progressText(progress.done) : preparing}
        </p>
        <p className="sr-only" aria-live="polite">
          {quarter > 0 ? progressText((progress.total * quarter) / 100) : preparing}
        </p>
        <div
          className="h-2 overflow-hidden rounded-full bg-surface-2"
          role="progressbar"
          aria-label={preparing}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progress.total > 0 ? pct : undefined}
        >
          {progress.total > 0 ? (
            <div
              className="h-full rounded-full bg-accent transition-[width] duration-200 motion-reduce:transition-none"
              style={{ width: `${pct}%` }}
            />
          ) : (
            <div className="h-full w-full rounded-full bg-accent/50 animate-pulse motion-reduce:animate-none" />
          )}
        </div>
      </div>
    );
  } else if (mode === "share") {
    body = (
      <div className="flex flex-col gap-2">
        <button type="button" onClick={onShare} disabled={busy} className={BTN_PRIMARY}>
          <FiDownload aria-hidden />
          {saveLabel}
        </button>
        {ios && (
          <p className="text-xs leading-relaxed text-muted">
            {video
              ? t("media.sheet.hint_video", { defaultValue: "В открывшемся окне нажмите «Сохранить видео»." })
              : t("media.sheet.hint_image", { defaultValue: "В открывшемся окне нажмите «Сохранить изображение»." })}
          </p>
        )}
      </div>
    );
  } else if (mode === "inapp") {
    body = (
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <p className="text-sm font-semibold text-foreground">
            {video
              ? t("media.sheet.inapp_title_video", {
                  defaultValue: "Этот встроенный браузер не сохраняет видео в «Фото»",
                })
              : t("media.sheet.inapp_title_image", {
                  defaultValue: "Этот встроенный браузер не сохраняет изображения в «Фото»",
                })}
          </p>
          <p className="text-sm leading-relaxed text-muted">
            {page
              ? t("media.sheet.inapp_page", {
                  defaultValue: "Нажмите «⋯» вверху экрана → «Открыть в Safari». Там нажмите «{{button}}».",
                  button: saveLabel,
                })
              : t("media.sheet.inapp_copy", {
                  defaultValue:
                    "Нажмите «Скопировать ссылку», откройте Safari и вставьте ссылку в адресную строку — входить в аккаунт не нужно. Там нажмите «{{button}}».",
                  button: saveLabel,
                })}
          </p>
        </div>
        {absLink && (
          <div className="flex flex-col gap-1.5">
            <button type="button" onClick={onCopy} className={BTN_PRIMARY}>
              {copy === "copied" ? <FiCheck aria-hidden /> : <FiCopy aria-hidden />}
              {t("media.sheet.copy_link", { defaultValue: "Скопировать ссылку" })}
            </button>
            <p aria-live="polite" className="text-xs leading-relaxed text-muted">
              {copy === "copied" && t("media.sheet.copied", { defaultValue: "Ссылка скопирована — вставьте её в Safari" })}
            </p>
            {copy === "manual" && (
              <label className="flex flex-col gap-1 text-xs text-muted">
                {t("media.sheet.copy_manual", { defaultValue: "Скопируйте ссылку вручную:" })}
                <input
                  readOnly
                  value={absLink}
                  onFocus={(e) => e.currentTarget.select()}
                  className="min-h-11 w-full rounded-lg border border-border bg-surface-2 px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/80"
                />
              </label>
            )}
          </div>
        )}
        {!page && (
          <p className="text-xs leading-relaxed text-muted">
            {t("media.sheet.inapp_or_menu", {
              defaultValue: "Или «⋯» вверху → «Открыть в Safari»: откроется эта же страница, там может понадобиться вход.",
            })}
          </p>
        )}
        {fileLink}
      </div>
    );
  } else {
    body = fileLink || blobLink || openLink || (
      <p role="alert" className="text-sm leading-relaxed text-foreground">
        {t("media.sheet.failed", {
          defaultValue: "Не удалось загрузить файл. Проверьте интернет и попробуйте ещё раз.",
        })}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {body}
      {client && (
        <p className="select-all text-[11px] leading-snug text-muted-2">
          {t("media.sheet.code", { defaultValue: "Код для поддержки: {{code}}", code: diag })} · {envLabel(client.env)}
        </p>
      )}
    </div>
  );
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])';

export default function SaveSheet({
  url,
  filename,
  start,
  onClose,
}: {
  url: string;
  filename: string;
  start: SheetStart;
  onClose: () => void;
}) {
  const { t } = useTranslation("common");
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const video = mediaKind(filename, url) === "video";

  useEffect(() => {
    const body = document.body;
    const prevOverflow = body.style.overflow;
    body.style.overflow = "hidden";
    panelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      // Ловим на window в фазе захвата: иначе Esc закрыл бы и окно под шторкой (просмотр картинки в чате).
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        return;
      }
      const panel = panelRef.current;
      if (e.key !== "Tab" || !panel) return;
      const items = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && (document.activeElement === first || document.activeElement === panel)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      body.style.overflow = prevOverflow;
    };
  }, [onClose]);

  if (typeof document === "undefined") return null;
  return createPortal(
    // Клики не всплывают к карточке или окну, внутри которых стоит кнопка
    // «Скачать»: портал передаёт события родителям по дереву React.
    <div
      className="fixed inset-0 z-[1300] flex items-end justify-center bg-black/60 sm:items-center sm:p-4"
      onPointerDown={(e) => e.stopPropagation()}
      onClick={(e) => {
        e.stopPropagation();
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="relative max-h-[90dvh] w-full overflow-y-auto overscroll-contain rounded-t-2xl border border-border bg-surface p-4 pb-[max(1rem,env(safe-area-inset-bottom))] text-foreground shadow-lg outline-none sm:max-w-md sm:rounded-2xl"
      >
        <div className="mb-3 flex items-start justify-between gap-3">
          <h2 id={titleId} className="pt-2.5 text-base font-semibold">
            {video
              ? t("media.sheet.save_video", { defaultValue: "Сохранить видео" })
              : t("media.sheet.save_image", { defaultValue: "Сохранить фото" })}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("media.sheet.close", { defaultValue: "Закрыть" })}
            className="-mr-2 -mt-1 grid h-11 w-11 shrink-0 cursor-pointer place-items-center rounded-full text-muted transition-colors hover:bg-surface-2 hover:text-foreground motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/80"
          >
            <FiX aria-hidden className="text-lg" />
          </button>
        </div>
        <SavePanel url={url} filename={filename} start={start} onSaved={onClose} />
      </div>
    </div>,
    document.body,
  );
}

"use client";

import clsx from "clsx";
import { useEffect, useId, useRef, useState, type DragEvent } from "react";
import { FiAlertTriangle, FiFilm, FiImage, FiRefreshCw, FiUploadCloud, FiX } from "react-icons/fi";
import { IMAGE_MAX_MB, uploadFile, VIDEO_MAX_MB, type UploadJSON, type UploadKind } from "@/lib/creative/api";
import { errorText } from "@/lib/creative/errors";
import type { Ct } from "@/lib/creative/text";
import { prepareImage } from "@/lib/vstudio/upload";
import { probeVideoFile } from "@/components/merge/uploadLogic";
import type { VsError } from "@/lib/vstudio/types";
import { FOCUS, Spinner } from "./ui";

/**
 * Загрузка фото и видео формы: перетаскивание и выбор, прогресс, отмена,
 * повтор, наши тексты ошибок. В форму уходит только uid готовой загрузки.
 *
 * Проверяем до сети то же, что сервер (core/creative/uploads.py): тип, размер,
 * а у видео — длину 4–30 с и кадр (у замены объекта ≥ 854×480). Большие фото
 * уменьшаем на телефоне до 2048 px — быстрее уходят. Сервер всё равно проверит.
 */
const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];
const IMAGE_EXT = [".jpg", ".jpeg", ".jfif", ".png", ".webp"];
const VIDEO_EXT: Record<string, string> = { mp4: "mp4", m4v: "mp4", mov: "mov", qt: "mov", webm: "webm" };
const VIDEO_MIME: Record<string, string> = { "video/mp4": "mp4", "video/quicktime": "mov", "video/webm": "webm" };
const VIDEO_MIN_S = 4;
const VIDEO_MAX_S = 30;
const DURATION_SLACK_S = 0.5;
const SWAP_MIN_PIXELS = 409_600;
const MB = 1024 * 1024;

type Item = {
  lid: string;
  status: "uploading" | "processing" | "ready" | "failed";
  pct: number;
  /** blob: до ответа сервера, потом — наше превью */
  preview: string;
  blobUrl: string | null;
  uid: string | null;
  duration: number | null;
  w: number | null;
  h: number | null;
  error: VsError | null;
  file: File | null;
  abort: AbortController | null;
};

let lidSeq = 0;
const nextLid = () => `u${++lidSeq}`;

const extOf = (name: string) => {
  const m = /\.([a-z0-9]+)$/i.exec(name || "");
  return m ? m[1].toLowerCase() : "";
};

function localErr(code: string, data: Record<string, unknown> = {}): VsError {
  return { status: 400, code, message: "", data };
}

/** Имя видео для сервера: обязательно с расширением mp4/mov/webm. */
function videoName(file: File): string | null {
  const ext = VIDEO_EXT[extOf(file.name)] || VIDEO_MIME[file.type];
  if (!ext) return null;
  const base = (file.name || "video").replace(/\.[^.]+$/, "") || "video";
  return `${base}.${ext}`;
}

export default function UploadField({
  kind,
  multiple,
  max,
  value,
  onChange,
  onBusy,
  minFrame,
  disabled,
  ct,
  labelId,
  describedBy,
}: {
  kind: UploadKind;
  multiple: boolean;
  max: number;
  value: string | string[];
  onChange: (next: string | string[]) => void;
  /** есть ли незаконченные загрузки (кнопка «Создать» ждёт) */
  onBusy: (busy: boolean) => void;
  minFrame?: boolean;
  disabled?: boolean;
  ct: Ct;
  labelId: string;
  describedBy?: string;
}) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [drag, setDrag] = useState(false);
  const [notice, setNotice] = useState<string>("");
  const itemsRef = useRef(items);
  const onChangeRef = useRef(onChange);
  const onBusyRef = useRef(onBusy);
  // Последнее значение формы: загрузка, начатая раньше, не должна читать устаревшее value
  // из своего рендера. Обновляем, только когда форма прислала новое значение, и сами — в emit
  // (две загрузки могут закончиться раньше, чем форма перерисуется).
  const valueRef = useRef(value);
  const maxRef = useRef(max);
  useEffect(() => {
    itemsRef.current = items;
    maxRef.current = max;
    onChangeRef.current = onChange;
    onBusyRef.current = onBusy;
  });
  useEffect(() => {
    valueRef.current = value;
  }, [value]);

  // В форме видны только готовые загрузки, которые форма помнит (после «Новая работа» — пусто).
  const picked = new Set(Array.isArray(value) ? value : value ? [value] : []);
  const visible = items.filter((i) => i.status !== "ready" || (i.uid && picked.has(i.uid)));
  const room = Math.max(0, max - visible.length);

  const busy = items.some((i) => i.status === "uploading" || i.status === "processing");
  useEffect(() => {
    onBusyRef.current(busy);
  }, [busy]);

  // Уход со страницы: отменить загрузки и отпустить blob-ссылки.
  useEffect(
    () => () => {
      for (const i of itemsRef.current) {
        i.abort?.abort();
        if (i.blobUrl) URL.revokeObjectURL(i.blobUrl);
      }
    },
    [],
  );

  const patch = (lid: string, p: Partial<Item>) => setItems((list) => list.map((i) => (i.lid === lid ? { ...i, ...p } : i)));

  /** Готова загрузка uid: к последнему значению формы добавляется только она. */
  const emit = (uid: string) => {
    let next: string | string[];
    if (multiple) {
      const cur = Array.isArray(valueRef.current) ? valueRef.current : [];
      // Старые готовые плитки (после «Новая работа», «Повторить», «Убрать») назад не возвращаем;
      // предел max срезает самые ранние, новая загрузка остаётся.
      const merged = [...cur.filter((u) => u !== uid), uid];
      const lim = maxRef.current;
      next = merged.length > lim ? merged.slice(merged.length - lim) : merged;
    } else {
      next = uid;
    }
    valueRef.current = next;
    onChangeRef.current(next);
  };

  const finish = (lid: string, res: { ok: true; data: UploadJSON } | { ok: false; error: VsError }) => {
    setItems((list) => {
      const next = list.map((i): Item => {
        if (i.lid !== lid) return i;
        if (!res.ok) return { ...i, status: "failed", error: res.error, abort: null };
        return {
          ...i,
          status: "ready",
          uid: res.data.uid,
          preview: res.data.preview || i.preview,
          duration: res.data.duration ?? i.duration,
          w: res.data.w ?? i.w,
          h: res.data.h ?? i.h,
          error: null,
          abort: null,
          file: null,
        };
      });
      // Одиночное поле: новая загрузка заменяет прежнюю.
      return !multiple && res.ok ? next.filter((i) => i.lid === lid || i.status !== "ready") : next;
    });
    if (res.ok) emit(res.data.uid);
  };

  const start = async (item: Item) => {
    const file = item.file;
    if (!file) return;
    const abort = new AbortController();
    patch(item.lid, { status: "uploading", pct: 0, error: null, abort });
    let blob: Blob = file;
    let name = file.name || (kind === "video" ? "video.mp4" : "photo.jpg");
    if (kind === "image") {
      const prepared = await prepareImage(file);
      blob = prepared.blob;
      name = prepared.filename || name;
      if (blob.size > IMAGE_MAX_MB * MB) {
        finish(item.lid, { ok: false, error: localErr("too_big", { max_mb: IMAGE_MAX_MB }) });
        return;
      }
    } else {
      name = videoName(file) || name;
    }
    if (abort.signal.aborted) return;
    const r = await uploadFile(blob, name, kind, {
      signal: abort.signal,
      onProgress: (pct, phase) => patch(item.lid, { pct, status: phase === "processing" ? "processing" : "uploading" }),
    });
    // Убрали плитку, пока ответ был в пути: uid в форму не добавляем.
    if (abort.signal.aborted || (!r.ok && r.error.code === "aborted")) return;
    finish(item.lid, r.ok ? { ok: true, data: r.data } : { ok: false, error: r.error });
  };

  /** Проверка до сети. null — можно грузить. */
  const precheck = async (file: File): Promise<{ error: VsError | null; meta: { duration: number | null; w: number | null; h: number | null } }> => {
    const meta = { duration: null as number | null, w: null as number | null, h: null as number | null };
    if (kind === "image") {
      const okType = IMAGE_TYPES.includes(file.type) || IMAGE_EXT.includes(`.${extOf(file.name)}`);
      if (!okType) return { error: localErr("bad_type"), meta };
      return { error: null, meta };
    }
    if (!videoName(file)) return { error: localErr("bad_type"), meta };
    if (file.size > VIDEO_MAX_MB * MB) return { error: localErr("too_big", { max_mb: VIDEO_MAX_MB }), meta };
    const probe = await probeVideoFile(file);
    if (probe) {
      meta.duration = Number.isFinite(probe.duration) ? probe.duration : null;
      meta.w = probe.width || null;
      meta.h = probe.height || null;
      if (meta.duration != null && meta.duration < VIDEO_MIN_S) return { error: localErr("too_short", { min_s: VIDEO_MIN_S }), meta };
      if (meta.duration != null && meta.duration > VIDEO_MAX_S + DURATION_SLACK_S) return { error: localErr("too_long", { max_s: VIDEO_MAX_S }), meta };
      if (minFrame && meta.w && meta.h && meta.w * meta.h < SWAP_MIN_PIXELS) return { error: localErr("too_small_frame"), meta };
    }
    return { error: null, meta };
  };

  const addFiles = async (list: FileList | File[]) => {
    if (disabled) return;
    setNotice("");
    const files = Array.from(list);
    if (!files.length) return;
    const limit = multiple ? room : 1;
    if (limit <= 0) {
      setNotice(ct("ferr.too_many", { max }));
      return;
    }
    if (files.length > limit) setNotice(ct("ferr.too_many", { max }));
    for (const file of files.slice(0, limit)) {
      const { error, meta } = await precheck(file);
      const blobUrl = kind === "image" && !error ? URL.createObjectURL(file) : null;
      const item: Item = {
        lid: nextLid(),
        status: error ? "failed" : "uploading",
        pct: 0,
        preview: blobUrl || "",
        blobUrl,
        uid: null,
        duration: meta.duration,
        w: meta.w,
        h: meta.h,
        error,
        file: error ? null : file,
        abort: null,
      };
      setItems((prev) => {
        // Одиночное поле: прежнюю неудачную/текущую загрузку убираем.
        const base = multiple ? prev : prev.filter((i) => i.status === "ready");
        return [...base, item];
      });
      if (!error) void start(item);
    }
  };

  const remove = (lid: string) => {
    const it = items.find((i) => i.lid === lid);
    it?.abort?.abort();
    if (it?.blobUrl) URL.revokeObjectURL(it.blobUrl);
    setItems((list) => list.filter((i) => i.lid !== lid));
    if (it?.status === "ready" && it.uid) {
      const cur = valueRef.current;
      const next = multiple ? (Array.isArray(cur) ? cur : []).filter((u) => u !== it.uid) : "";
      valueRef.current = next;
      onChange(next);
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    if (e.dataTransfer?.files?.length) void addFiles(e.dataTransfer.files);
  };

  const accept = kind === "image" ? "image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp" : "video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm";
  const Icon = kind === "image" ? FiImage : FiFilm;
  const dropText = kind === "video" ? ct("run.drop_video") : multiple ? ct("run.drop_images") : ct("run.drop_image");
  const showDrop = multiple ? room > 0 : visible.length === 0;
  // Номер плитки для «Фото 2: …» и id строки ошибки (aria-describedby кнопки повтора).
  const failed = kind === "image" ? visible.map((i, n) => ({ i, n: n + 1 })).filter(({ i }) => i.status === "failed") : [];
  const errId = (lid: string) => `${inputId}-err-${lid}`;

  return (
    <div className="space-y-2">
      <input
        ref={inputRef}
        id={inputId}
        type="file"
        accept={accept}
        multiple={multiple}
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
        disabled={disabled}
        onChange={(e) => {
          if (e.target.files) void addFiles(e.target.files);
          e.target.value = "";
        }}
      />

      {visible.length > 0 && (
        <ul className={clsx("grid gap-2", kind === "video" ? "grid-cols-1" : "grid-cols-3 sm:grid-cols-4")}>
          {visible.map((i) => (
            <li
              key={i.lid}
              className={clsx(
                "relative overflow-hidden rounded-xl border bg-background",
                i.status === "failed" ? "border-status-fail/60" : "border-border",
                kind === "video" ? "flex min-h-20 items-center gap-3 p-2.5" : "aspect-square",
              )}
            >
              {kind === "video" ? (
                <>
                  <span className="relative grid size-16 shrink-0 place-items-center overflow-hidden rounded-lg bg-surface-2">
                    {i.preview ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={i.preview} alt="" className="size-full object-cover" />
                    ) : (
                      <FiFilm aria-hidden="true" className="size-6 text-muted" />
                    )}
                  </span>
                  <span className="min-w-0 flex-1 text-sm">
                    <span className="block truncate font-medium">{i.file?.name || ct("form.label.video")}</span>
                    <UploadStatus item={i} ct={ct} kind={kind} />
                  </span>
                </>
              ) : (
                <>
                  {i.preview ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={i.preview} alt="" className="size-full object-cover" />
                  ) : (
                    <span className="grid size-full place-items-center bg-surface-2">
                      <FiImage aria-hidden="true" className="size-6 text-muted" />
                    </span>
                  )}
                  {i.status !== "ready" && (
                    <span className="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-black/60 p-1.5 text-center text-[11px] leading-tight text-white">
                      <UploadStatus item={i} ct={ct} kind={kind} compact />
                    </span>
                  )}
                </>
              )}
              <span className={clsx("flex gap-1", kind === "video" ? "shrink-0" : "absolute right-1 top-1")}>
                {i.status === "failed" && i.file && (
                  <button
                    type="button"
                    aria-describedby={kind === "image" ? errId(i.lid) : undefined}
                    onClick={() => void start(i)}
                    className={clsx("grid size-8 place-items-center rounded-full bg-black/70 text-white hover:bg-black", FOCUS)}
                    aria-label={ct("run.retry_upload")}
                    title={ct("run.retry_upload")}
                  >
                    <FiRefreshCw aria-hidden="true" className="size-3.5" />
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => remove(i.lid)}
                  className={clsx("grid size-8 place-items-center rounded-full bg-black/70 text-white hover:bg-black", FOCUS)}
                  aria-label={i.status === "uploading" || i.status === "processing" ? ct("run.cancel_upload") : ct("run.remove_file")}
                  title={i.status === "uploading" || i.status === "processing" ? ct("run.cancel_upload") : ct("run.remove_file")}
                >
                  <FiX aria-hidden="true" className="size-4" />
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}

      {showDrop && (
        <button
          type="button"
          disabled={disabled}
          aria-labelledby={labelId}
          aria-describedby={describedBy}
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            if (!disabled) setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={onDrop}
          className={clsx(
            "flex w-full flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 text-center text-sm transition-colors",
            visible.length ? "min-h-20 py-3" : "min-h-32 py-6",
            drag ? "border-[#F5C518] bg-[#F5C518]/10" : "border-border bg-background hover:border-[#F5C518]/60",
            "disabled:cursor-not-allowed disabled:opacity-60",
            FOCUS,
          )}
        >
          {visible.length ? <FiUploadCloud aria-hidden="true" className="size-5 text-muted" /> : <Icon aria-hidden="true" className="size-7 text-muted" />}
          <span className="font-medium">{visible.length ? ct("run.add_more") : dropText}</span>
        </button>
      )}

      {failed.length > 0 && (
        <ul className="space-y-1">
          {failed.map(({ i, n }) => (
            <li key={i.lid} id={errId(i.lid)} role="alert" className="text-xs font-medium text-status-fail">
              {ct("run.file_error", { n, error: i.error ? errorText(ct, i.error, kind) : ct("errors.unknown") })}
            </li>
          ))}
        </ul>
      )}

      {multiple && (
        <p className="text-xs text-muted" aria-live="polite">
          {ct("run.files_count", { n: visible.filter((i) => i.status === "ready").length, max })}
        </p>
      )}
      {notice && (
        <p role="alert" className="text-xs font-medium text-status-fail">
          {notice}
        </p>
      )}
    </div>
  );
}

function UploadStatus({ item, ct, kind, compact }: { item: Item; ct: Ct; kind: UploadKind; compact?: boolean }) {
  // На плитке фото — только значок: текст ошибки выводится строкой под сеткой.
  if (item.status === "failed" && compact) return <FiAlertTriangle aria-hidden="true" className="size-6 text-white" />;
  if (item.status === "failed") {
    return (
      <span role="alert" className={clsx("block", compact ? "" : "text-xs text-status-fail")}>
        {item.error ? errorText(ct, item.error, kind) : ct("errors.unknown")}
      </span>
    );
  }
  if (item.status === "uploading" || item.status === "processing") {
    return (
      <span className={clsx("flex items-center gap-1.5", compact ? "flex-col" : "text-xs text-muted")} aria-live="polite">
        <Spinner className="size-3.5" />
        {item.status === "processing" ? ct("run.processing") : ct("run.uploading", { pct: item.pct })}
        {!compact && (
          <span className="ml-1 h-1 w-20 overflow-hidden rounded-full bg-surface-3" aria-hidden="true">
            <span className="block h-full bg-[#F5C518] transition-[width]" style={{ width: `${item.status === "processing" ? 100 : item.pct}%` }} />
          </span>
        )}
      </span>
    );
  }
  if (kind === "video" && item.duration != null) {
    const dur = item.duration.toFixed(1).replace(/\.0$/, "");
    return (
      <span className="block text-xs text-muted">
        {item.w && item.h ? ct("run.video_meta", { dur, w: item.w, h: item.h }) : ct("run.video_meta_short", { dur })}
      </span>
    );
  }
  return null;
}

"use client";

/**
 * Видеостудия: загрузка фото в запрос (§9.4 useUpload, §9.6 «Материал»).
 *
 *  - чип появляется сразу — с blob-превью и прогрессом (приём из
 *    ChatComposer.uploadFiles), номер @Image N он получит, когда у него
 *    будет uid;
 *  - файлы уходят по одному (очередь lib/vstudio/upload.ts), прогресс — XHR;
 *  - JPEG/PNG/WebP больше 2048 px уменьшаются на клиенте, HEIC уходит как есть;
 *  - после отправки байтов — «Обрабатываем фото…» (сервер перекодирует);
 *  - ошибка — красный чип с причиной и «Повторить» (файл помним), отмена —
 *    чип пропадает;
 *  - тот же файл второй раз (сервер ответил 200 — дубль по sha256) не даёт
 *    второго чипа: промис всё равно отдаёт uid, и редактор вставит тег.
 *
 * Гостю — окно входа (actions.requireAuth), ничего не отправляется.
 */
import { useCallback, useEffect, useLayoutEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { trackVs } from "@/lib/vstudio/api";
import { errorText, reactionFor } from "@/lib/vstudio/errors";
import { checkFile, createUploadQueue, uploadOne, type UploadQueue } from "@/lib/vstudio/upload";
import { MAX_INPUTS } from "@/lib/vstudio/types";
import type { InputSlot, TrayItem, TrayStatus, Uid, UploadResult, VsResult } from "@/lib/vstudio/types";
import { useVStudio } from "../context";
import { allItems } from "../composer/composerLogic";
import { ct } from "../composer/composerText";

export type UploadTarget = {
  /** reference (по умолчанию) — в лоток; first_frame / last_frame — в слот кадра. */
  slot?: InputSlot;
};

export type UseUpload = {
  /** Загрузить файлы; промис — uid загруженных (по порядку файлов, без упавших). */
  addFiles: (files: File[], target?: UploadTarget) => Promise<Uid[]>;
  retry: (lid: string) => void;
  /** Отменить загрузку (чип пропадает). */
  cancel: (lid: string) => void;
  /** Убрать чип из запроса (и отменить загрузку, если она идёт). */
  remove: (lid: string) => void;
  /** Этот чип — наша загрузка, и её можно повторить. */
  canRetry: (lid: string) => boolean;
};

type Kept = { file: File; slot: InputSlot; blob: string | null };

let seq = 0;
function newLid(): string {
  seq += 1;
  return `up:${Date.now().toString(36)}:${seq}`;
}

function revoke(url: string | null | undefined) {
  if (!url || !url.startsWith("blob:")) return;
  try {
    URL.revokeObjectURL(url);
  } catch {
    /* уже отозвана */
  }
}

function blobPreview(file: File): string | null {
  try {
    return typeof URL !== "undefined" && typeof URL.createObjectURL === "function" ? URL.createObjectURL(file) : null;
  } catch {
    return null;
  }
}

function statusOf(result: UploadResult): TrayStatus {
  const s = result.asset.status;
  return s === "ready" ? "ready" : s === "failed" ? "failed" : "pending";
}

export function useUpload(): UseUpload {
  const { state, dispatch, actions } = useVStudio();
  const { t } = useTranslation("vstudio", { useSuspense: false });

  const live = useRef({ state, actions, t });
  useLayoutEffect(() => {
    live.current = { state, actions, t };
  });

  const kept = useRef(new Map<string, Kept>());
  /** Последний показанный процент по чипу: не будить стор на каждый байт. */
  const shown = useRef(new Map<string, { pct: number; phase: string }>());
  const queueRef = useRef<UploadQueue | null>(null);

  const queue = useCallback((): UploadQueue => {
    if (queueRef.current) return queueRef.current;
    queueRef.current = createUploadQueue(
      (job, ctl) => uploadOne(job.file, { project: job.project, signal: ctl.signal, onProgress: ctl.onProgress }),
      (e) => {
        if (e.type !== "progress") return;
        const prev = shown.current.get(e.lid);
        if (prev && prev.phase === e.phase && Math.abs(prev.pct - e.pct) < 5 && e.pct < 100) return;
        shown.current.set(e.lid, { pct: e.pct, phase: e.phase });
        dispatch({
          type: "tray/update",
          lid: e.lid,
          patch: e.phase === "processing" ? { status: "processing", progress: 100 } : { status: "uploading", progress: e.pct },
        });
      },
    );
    return queueRef.current;
  }, [dispatch]);

  /** Итог одной загрузки → чип. Возвращает uid или null. */
  const settle = useCallback(
    (lid: string, res: VsResult<UploadResult>): Uid | null => {
      shown.current.delete(lid);
      const k = kept.current.get(lid);
      const { state: s, actions: a, t: tt } = live.current;
      if (res.ok) {
        const asset = res.data.asset;
        const slot = k?.slot ?? "reference";
        // Тот же файл уже в запросе (дубль по sha256): второй чип не нужен.
        const twin = allItems(s.composer).find(
          (i) => i.lid !== lid && i.assetUid === asset.uid && (slot === "reference" ? i.slot === "reference" : i.slot === slot),
        );
        if (twin) {
          dispatch({ type: "tray/remove", lid });
        } else {
          dispatch({
            type: "tray/update",
            lid,
            patch: {
              assetUid: asset.uid,
              asset,
              status: statusOf(res.data),
              progress: 100,
              preview: asset.thumb_url || asset.url || k?.blob || null,
              errorCode: asset.status === "failed" ? asset.error_code || "asset_failed" : undefined,
            },
          });
        }
        dispatch({ type: "library/upsert", asset });
        if (asset.thumb_url || asset.url) revoke(k?.blob);
        kept.current.delete(lid);
        trackVs("vstudio_upload", { ok: true });
        return asset.uid;
      }
      const err = res.error;
      if (err.code === "aborted") {
        // Отменили: чип уже убран тем, кто отменял.
        return null;
      }
      trackVs("vstudio_upload", { ok: false, code: String(err.code) });
      const reaction = reactionFor(err);
      if (reaction.kind === "auth" || reaction.kind === "disabled") {
        a.handleError(err);
        dispatch({ type: "tray/remove", lid });
        revoke(k?.blob);
        kept.current.delete(lid);
        return null;
      }
      dispatch({ type: "tray/update", lid, patch: { status: "failed", progress: 0, errorCode: String(err.code) } });
      // Нет сети или сервер занят — понятнее сказать и тостом (чип покажет «Повторить»).
      if (reaction.kind === "offline" || reaction.kind === "retry_later") a.toast(errorText(tt, err), "error");
      return null;
    },
    [dispatch],
  );

  const start = useCallback(
    (lid: string): Promise<Uid | null> => {
      const k = kept.current.get(lid);
      if (!k) return Promise.resolve(null);
      const project = live.current.state.project?.uid ?? null;
      return queue()
        .add({ lid, file: k.file, project })
        .then((res) => settle(lid, res));
    },
    [queue, settle],
  );

  const addFiles = useCallback(
    async (files: File[], target: UploadTarget = {}): Promise<Uid[]> => {
      const list = Array.from(files || []);
      if (!list.length) return [];
      const { state: s, actions: a, t: tt } = live.current;
      if (!a.requireAuth()) return [];
      const slot: InputSlot = target.slot ?? "reference";

      // Проверка до сети: тип и размер. Отказ — тостом, чип не рисуем.
      const accepted: File[] = [];
      for (const f of list) {
        const check = checkFile(f);
        if (check.ok) accepted.push(f);
        else {
          trackVs("vstudio_upload", { ok: false, code: check.code });
          a.toast(errorText(tt, { code: check.code, message: "" }), "error");
        }
      }
      if (!accepted.length) return [];

      // Лимит материалов в одном запросе (too_many_inputs). Кадр заменяет прежний — место не занимает.
      let batch: File[];
      if (slot === "reference") {
        const free = Math.max(0, MAX_INPUTS - allItems(s.composer).length);
        batch = accepted.slice(0, free);
        if (batch.length < accepted.length) a.toast(ct(tt, "composer.tooManyInputs", { max: MAX_INPUTS }), "error");
      } else {
        batch = accepted.slice(0, 1);
        // Прежний кадр этого слота ещё грузится — он больше не нужен.
        const prev = s.composer.frames[slot];
        if (prev && kept.current.has(prev.lid)) {
          queue().cancel(prev.lid);
          revoke(kept.current.get(prev.lid)?.blob);
          kept.current.delete(prev.lid);
        }
      }
      if (!batch.length) return [];

      const lids = batch.map((file) => {
        const lid = newLid();
        const blob = blobPreview(file);
        kept.current.set(lid, { file, slot, blob });
        const item: TrayItem = {
          lid,
          slot,
          role: "",
          included: true,
          status: "uploading",
          progress: 0,
          preview: blob,
        };
        dispatch({ type: "tray/add", item });
        return lid;
      });

      const results = await Promise.all(lids.map((lid) => start(lid)));
      return results.filter((u): u is Uid => Boolean(u));
    },
    [dispatch, queue, start],
  );

  const retry = useCallback(
    (lid: string) => {
      if (!kept.current.has(lid) || queueRef.current?.has(lid)) return;
      dispatch({ type: "tray/update", lid, patch: { status: "uploading", progress: 0, errorCode: undefined } });
      void start(lid);
    },
    [dispatch, start],
  );

  const drop = useCallback(
    (lid: string) => {
      queueRef.current?.cancel(lid);
      shown.current.delete(lid);
      const k = kept.current.get(lid);
      kept.current.delete(lid);
      const item = allItems(live.current.state.composer).find((i) => i.lid === lid);
      dispatch({ type: "tray/remove", lid });
      revoke(k?.blob);
      revoke(item?.preview);
    },
    [dispatch],
  );

  const canRetry = useCallback((lid: string) => kept.current.has(lid), []);

  // Композер ушёл со страницы: незаконченные загрузки прерываем, их чипы (и
  // неудачные без uid) убираем — файлов больше нет, повторить было бы нечего.
  // Так у любого красного чипа без uid на экране «Повторить» всегда работает.
  useEffect(() => {
    const keptMap = kept.current;
    return () => {
      const q = queueRef.current;
      queueRef.current = null;
      q?.cancelAll();
      for (const [lid, k] of keptMap) {
        const item = allItems(live.current.state.composer).find((i) => i.lid === lid);
        if (item && !item.assetUid) dispatch({ type: "tray/remove", lid });
        revoke(k.blob);
      }
      keptMap.clear();
    };
  }, [dispatch]);

  return { addFiles, retry, cancel: drop, remove: drop, canRetry };
}

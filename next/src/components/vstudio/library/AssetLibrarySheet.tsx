"use client";

/**
 * Видеостудия: «Мои материалы» — нижняя шторка библиотеки (§9.3, §9.6).
 *
 * Сетка фото с фильтрами «Все / Загруженные / Созданные / Кадры», дозагрузка
 * по курсору, удаление (мягкое: в готовых генерациях фото остаётся, а в
 * текущем запросе его чип краснеет — «удалено»). Тап по фото кладёт его в
 * запрос: в лоток как @Image N, а если шторку открыли из пустого слота кадра
 * («Из моих материалов») — в этот слот.
 *
 * Открыта ли — state.ui.panels.library (actions.openLibrary: гостю — вход).
 * useLibrary грузит первую страницу и для выбора по «@» (раздел «Мои
 * материалы»), поэтому композер зовёт его тоже; запрос уходит один.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";
import { FiAlertTriangle, FiCheck, FiImage, FiLoader, FiRefreshCw, FiTrash2, FiUpload } from "react-icons/fi";
import { ConfirmationModal } from "@/components/dialog/Dialog";
import { LIBRARY_FILTER_SOURCE, deleteAsset, listAssets } from "@/lib/vstudio/api";
import { errorText } from "@/lib/vstudio/errors";
import { UPLOAD_ACCEPT } from "@/lib/vstudio/upload";
import type { AssetJSON, FrameSlot, LibraryFilter, VsError } from "@/lib/vstudio/types";
import BottomSheet from "../BottomSheet";
import { useVStudio } from "../context";
import { useIsMobile } from "../settings/SettingsSheet";
import {
  composerHandlers,
  composerPresent,
  getLibraryTarget,
  setLibraryTarget,
  subscribeComposerBus,
} from "../composer/composerBus";
import { hasAssetIn, trayItemFromAsset } from "../composer/composerLogic";
import { ct, type ComposerTextKey } from "../composer/composerText";

export const LIBRARY_PAGE = 60;
const FILTERS: readonly LibraryFilter[] = ["all", "uploads", "generated", "frames"];

/* ------------------------------------------------------------------ */
/* Загрузка страниц                                                    */
/* ------------------------------------------------------------------ */

/** Один запрос на вкладку: шторка и композер могут попросить одно и то же одновременно. */
let inflight: { filter: LibraryFilter; cursor: string | null } | null = null;
let seq = 0;

export type UseLibrary = {
  loadMore: () => void;
  reload: () => void;
  error: VsError | null;
};

/**
 * Первая страница «Моих материалов» — как только она нужна (enabled) и ещё не
 * загружена; смена фильтра (library/filter) сбрасывает список — грузим заново.
 */
export function useLibrary(enabled: boolean): UseLibrary {
  const { state, dispatch, authed } = useVStudio();
  const lib = state.library;
  const [error, setError] = useState<VsError | null>(null);
  const live = useRef(lib);
  useLayoutEffect(() => {
    live.current = lib;
  });

  const fetchPage = useCallback(
    async (cursor: string | null) => {
      const filter = live.current.filter;
      if (inflight && inflight.filter === filter && inflight.cursor === cursor) return;
      const my = ++seq;
      inflight = { filter, cursor };
      setError(null);
      dispatch({ type: "library/loading" });
      const res = await listAssets({ kind: "image", source: LIBRARY_FILTER_SOURCE[filter], before: cursor, limit: LIBRARY_PAGE });
      if (my === seq) inflight = null;
      // Пока ждали, сменили фильтр — ответ не про этот список.
      if (live.current.filter !== filter) return;
      if (res.ok) {
        dispatch({ type: "library/loaded", page: res.data, append: Boolean(cursor) });
        return;
      }
      setError(res.error);
      const cur = live.current;
      // Снять «загрузку», оставив то, что уже было.
      dispatch({ type: "library/loaded", page: { items: [], next: cursor ? cur.next : null }, append: true });
    },
    [dispatch],
  );

  useEffect(() => {
    if (!enabled || authed !== true) return;
    if (lib.loaded || lib.loading || error) return;
    void fetchPage(null);
  }, [enabled, authed, lib.loaded, lib.loading, lib.filter, error, fetchPage]);

  const loadMore = useCallback(() => {
    const cur = live.current;
    if (!cur.next || cur.loading) return;
    void fetchPage(cur.next);
  }, [fetchPage]);

  const reload = useCallback(() => {
    setError(null);
    void fetchPage(null);
  }, [fetchPage]);

  return { loadMore, reload, error };
}

/* ------------------------------------------------------------------ */
/* Плитка                                                              */
/* ------------------------------------------------------------------ */

const SOURCE_KEY: Partial<Record<AssetJSON["source"], ComposerTextKey>> = {
  upload: "library.source.upload",
  generated_image: "library.source.generated_image",
  frame: "library.source.frame",
};

function Tile({
  asset,
  inRequest,
  onPick,
  onDelete,
}: {
  asset: AssetJSON;
  inRequest: boolean;
  onPick: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const [broken, setBroken] = useState(false);
  const src = asset.thumb_url || asset.url;
  const pending = asset.status === "pending";
  const failed = asset.status === "failed";
  const sourceKey = SOURCE_KEY[asset.source];
  const name = sourceKey ? ct(t, sourceKey) : "";
  return (
    <li className="group relative">
      <button
        type="button"
        onClick={onPick}
        disabled={failed}
        aria-label={[ct(t, "library.pick"), name, inRequest ? ct(t, "library.inRequest") : ""].filter(Boolean).join(" · ")}
        className={`relative block aspect-square w-full overflow-hidden rounded-xl border bg-surface-2 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${
          inRequest ? "border-accent" : "border-border hover:border-border-strong"
        } ${failed ? "cursor-not-allowed" : "cursor-pointer"}`}
      >
        {src && !broken ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={src} alt="" loading="lazy" onError={() => setBroken(true)} className="size-full object-cover" />
        ) : (
          <span className="grid size-full place-items-center text-2xl text-muted-2">
            <FiImage aria-hidden />
          </span>
        )}
        {pending && (
          <span className="absolute inset-0 grid place-items-center bg-black/40 text-white">
            <span className="flex flex-col items-center gap-1 text-[11px]">
              <FiLoader className="size-5 animate-spin" aria-hidden />
              {ct(t, "library.pending")}
            </span>
          </span>
        )}
        {failed && (
          <span className="absolute inset-0 grid place-items-center bg-status-fail/40 text-white">
            <span className="flex flex-col items-center gap-1 text-[11px]">
              <FiAlertTriangle className="size-5" aria-hidden />
              {ct(t, "library.failed")}
            </span>
          </span>
        )}
        {name && (
          <span className="absolute bottom-1 left-1 rounded-md bg-black/55 px-1.5 py-0.5 text-[10px] font-medium text-white">{name}</span>
        )}
        {inRequest && (
          <span className="absolute right-1 top-1 grid size-6 place-items-center rounded-full bg-accent text-on-accent" title={ct(t, "library.inRequest")}>
            <FiCheck className="size-3.5" aria-hidden />
          </span>
        )}
      </button>
      <button
        type="button"
        onClick={onDelete}
        aria-label={ct(t, "library.delete")}
        title={ct(t, "library.delete")}
        className="absolute left-1 top-1 grid size-9 place-items-center rounded-lg bg-black/55 text-white transition-opacity hover:bg-status-fail focus-visible:opacity-100 md:size-8 md:opacity-0 md:group-hover:opacity-100 cursor-pointer"
      >
        <FiTrash2 className="size-4" aria-hidden />
      </button>
    </li>
  );
}

/* ------------------------------------------------------------------ */
/* Шторка                                                              */
/* ------------------------------------------------------------------ */

export default function AssetLibrarySheet() {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { state, dispatch, actions } = useVStudio();
  const mobile = useIsMobile();
  const open = state.ui.panels.library;
  const lib = state.library;
  const { loadMore, reload, error } = useLibrary(open);
  const target = useSyncExternalStore(subscribeComposerBus, getLibraryTarget, () => null);
  const canUpload = useSyncExternalStore(subscribeComposerBus, composerPresent, () => false);
  const [confirm, setConfirm] = useState<AssetJSON | null>(null);
  const [deleting, setDeleting] = useState(false);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const sentinel = useRef<HTMLDivElement | null>(null);

  const close = useCallback(() => {
    dispatch({ type: "ui/panel", panel: "library", open: false });
    setLibraryTarget(null);
  }, [dispatch]);

  // Дозагрузка, когда низ сетки показался.
  useEffect(() => {
    const node = sentinel.current;
    if (!open || !node || !lib.next || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) loadMore();
    });
    io.observe(node);
    return () => io.disconnect();
  }, [open, lib.next, lib.items.length, loadMore]);

  const pick = (asset: AssetJSON) => {
    const slot: FrameSlot | "reference" = target ?? "reference";
    if (hasAssetIn(state.composer, asset.uid, slot)) {
      actions.toast(ct(t, "composer.alreadyInRequest"), "info");
      close();
      return;
    }
    const h = composerHandlers();
    if (h) h.pick(asset, slot);
    else dispatch({ type: "tray/add", item: trayItemFromAsset(asset, slot) });
    close();
  };

  const doDelete = async () => {
    const asset = confirm;
    if (!asset || deleting) return;
    setDeleting(true);
    const res = await deleteAsset(asset.uid);
    setDeleting(false);
    setConfirm(null);
    if (!res.ok) {
      const r = actions.handleError(res.error, { silent: true });
      if (r.kind === "not_found") dispatch({ type: "library/remove", uid: asset.uid });
      else if (r.kind !== "auth" && r.kind !== "paywall" && r.kind !== "disabled") actions.toast(errorText(t, res.error), "error");
      return;
    }
    dispatch({ type: "library/remove", uid: asset.uid });
    actions.toast(ct(t, "library.deleted"), "ok");
  };

  const subject = target === "first_frame" ? ct(t, "tray.firstFrame") : target === "last_frame" ? ct(t, "tray.lastFrame") : "";
  const title = target ? ct(t, "library.titleFrame", { subject: subject.toLowerCase() }) : ct(t, "library.title");
  const firstLoad = lib.loading && !lib.items.length;

  return (
    <>
      <BottomSheet
        open={open}
        onClose={close}
        title={title}
        size={mobile ? "full" : "half"}
        className="md:max-w-[880px]"
      >
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex flex-wrap gap-1.5" role="tablist" aria-label={ct(t, "library.title")}>
              {FILTERS.map((f) => (
                <button
                  key={f}
                  type="button"
                  role="tab"
                  aria-selected={lib.filter === f}
                  onClick={() => dispatch({ type: "library/filter", filter: f })}
                  className={`min-h-11 rounded-full border px-3.5 text-xs font-semibold transition-colors md:min-h-9 cursor-pointer ${
                    lib.filter === f
                      ? "border-accent bg-accent-soft text-foreground"
                      : "border-border bg-surface-2 text-muted hover:text-foreground"
                  }`}
                >
                  {ct(t, `library.filter.${f}` as ComposerTextKey)}
                </button>
              ))}
            </div>
            {canUpload && (
              <>
                <button
                  type="button"
                  onClick={() => fileInput.current?.click()}
                  className="ml-auto inline-flex min-h-11 items-center gap-1.5 rounded-xl border border-border bg-surface-2 px-3 text-xs font-semibold text-foreground hover:border-border-strong md:min-h-9 cursor-pointer"
                >
                  <FiUpload aria-hidden />
                  {ct(t, "library.upload")}
                </button>
                <input
                  ref={fileInput}
                  type="file"
                  accept={UPLOAD_ACCEPT}
                  multiple={!target}
                  className="hidden"
                  tabIndex={-1}
                  aria-hidden
                  onChange={(e) => {
                    const files = Array.from(e.target.files || []);
                    e.target.value = "";
                    if (!files.length) return;
                    void composerHandlers()?.upload(files, { slot: target ?? "reference", via: "picker" });
                    close();
                  }}
                />
              </>
            )}
          </div>

          {error && !lib.items.length ? (
            <div className="flex flex-col items-center gap-3 py-10 text-center">
              <p className="text-sm text-muted">{ct(t, "library.loadError")}</p>
              <button
                type="button"
                onClick={reload}
                className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-border bg-surface-2 px-4 text-sm font-medium hover:border-border-strong cursor-pointer"
              >
                <FiRefreshCw aria-hidden />
                {ct(t, "library.retry")}
              </button>
            </div>
          ) : firstLoad ? (
            <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-5" aria-busy="true">
              {Array.from({ length: 10 }, (_, i) => (
                <li key={i} className="aspect-square animate-pulse rounded-xl bg-surface-2" />
              ))}
            </ul>
          ) : lib.items.length === 0 && lib.loaded ? (
            <p className="py-10 text-center text-sm text-muted">
              {lib.filter === "all" ? ct(t, "library.empty") : ct(t, "library.emptyFilter")}
            </p>
          ) : (
            <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-5">
              {lib.items.map((asset) => (
                <Tile
                  key={asset.uid}
                  asset={asset}
                  inRequest={hasAssetIn(state.composer, asset.uid)}
                  onPick={() => pick(asset)}
                  onDelete={() => setConfirm(asset)}
                />
              ))}
            </ul>
          )}

          {lib.next && lib.items.length > 0 && (
            <div ref={sentinel} className="flex justify-center py-2">
              <button
                type="button"
                onClick={loadMore}
                disabled={lib.loading}
                className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-border bg-surface-2 px-4 text-sm font-medium hover:border-border-strong disabled:opacity-60 md:min-h-9 cursor-pointer"
              >
                {lib.loading && <FiLoader className="animate-spin" aria-hidden />}
                {ct(t, "library.more")}
              </button>
            </div>
          )}
        </div>
      </BottomSheet>
      <ConfirmationModal
        isOpen={Boolean(confirm)}
        title={ct(t, "library.deleteTitle")}
        description={ct(t, "library.deleteConfirm")}
        confirmText={ct(t, "library.delete")}
        cancelText={ct(t, "library.deleteCancel")}
        confirmDisabled={deleting}
        onConfirm={() => void doDelete()}
        onCancel={() => setConfirm(null)}
      />
    </>
  );
}

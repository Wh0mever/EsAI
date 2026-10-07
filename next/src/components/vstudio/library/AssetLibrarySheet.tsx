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
import { VS_BTN_GHOST, VS_FOCUS, VS_PILL, VS_PILL_ON, vx } from "../ui/skin";

export const LIBRARY_PAGE = 60;
const FILTERS: readonly LibraryFilter[] = ["all", "uploads", "generated", "frames"];

/** Сетка фото: три в ряд на телефоне, пять на компьютере. Та же — у заглушки, чтобы плитки не прыгали. */
const GRID = "grid grid-cols-3 gap-2 sm:grid-cols-4 sm:gap-2.5 md:grid-cols-5";
/**
 * Плашка на плитке. Вид как у VS_ON_MEDIA, но без размытия фона: плиток в
 * сетке десятки, и столько размытых слоёв при прокрутке телефон не тянет.
 */
const TILE_BADGE = "rounded-full bg-black/60 px-2 py-0.5 text-[10px] font-medium leading-4 text-white";

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
        className={vx(
          "relative block aspect-square w-full overflow-hidden rounded-xl border bg-surface-2 transition-[border-color,box-shadow] duration-200",
          VS_FOCUS,
          inRequest
            ? "border-accent/70 shadow-[0_0_0_1px_rgba(245,197,24,0.28)]"
            : "border-white/10 hover:border-white/30",
          failed ? "cursor-not-allowed" : "cursor-pointer",
        )}
      >
        {src && !broken ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={src}
            alt=""
            loading="lazy"
            decoding="async"
            onError={() => setBroken(true)}
            className="size-full object-cover"
          />
        ) : (
          <span className="grid size-full place-items-center text-2xl text-muted-2">
            <FiImage aria-hidden />
          </span>
        )}
        {pending && (
          <span className="absolute inset-0 grid place-items-center bg-black/50 text-white">
            <span className="flex flex-col items-center gap-1 text-[11px]">
              <FiLoader className="size-5 motion-safe:animate-spin" aria-hidden />
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
        {name && <span className={vx(TILE_BADGE, "absolute bottom-1.5 left-1.5")}>{name}</span>}
        {inRequest && (
          <span
            className="absolute right-1.5 top-1.5 grid size-6 place-items-center rounded-full bg-accent text-on-accent"
            title={ct(t, "library.inRequest")}
          >
            <FiCheck className="size-3.5" aria-hidden />
          </span>
        )}
      </button>
      <button
        type="button"
        onClick={onDelete}
        aria-label={ct(t, "library.delete")}
        title={ct(t, "library.delete")}
        className={vx(
          "absolute left-1.5 top-1.5 grid size-9 cursor-pointer place-items-center rounded-full bg-black/60 text-white transition-[opacity,background-color] hover:bg-status-fail focus-visible:opacity-100 md:size-8 md:opacity-0 md:group-hover:opacity-100",
          VS_FOCUS,
        )}
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
                  className={vx(VS_PILL, "max-md:h-11", lib.filter === f && VS_PILL_ON)}
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
                  className={vx(VS_BTN_GHOST, "ml-auto md:!min-h-9")}
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
            <div className="flex flex-col items-center gap-4 py-12 text-center">
              <span className="vs-card grid size-12 place-items-center rounded-full text-lg text-status-wait" aria-hidden>
                <FiAlertTriangle />
              </span>
              <p className="text-sm text-muted">{ct(t, "library.loadError")}</p>
              <button type="button" onClick={reload} className={VS_BTN_GHOST}>
                <FiRefreshCw aria-hidden />
                {ct(t, "library.retry")}
              </button>
            </div>
          ) : firstLoad ? (
            <ul className={GRID} aria-busy="true">
              {Array.from({ length: 10 }, (_, i) => (
                <li key={i} className="vs-film aspect-square rounded-xl" />
              ))}
            </ul>
          ) : lib.items.length === 0 && lib.loaded ? (
            <div className="flex flex-col items-center gap-4 py-12 text-center">
              <span className="vs-card grid size-12 place-items-center rounded-full text-lg text-muted" aria-hidden>
                <FiImage />
              </span>
              <p className="max-w-xs text-sm leading-snug text-muted">
                {lib.filter === "all" ? ct(t, "library.empty") : ct(t, "library.emptyFilter")}
              </p>
            </div>
          ) : (
            <ul className={GRID}>
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
                className={VS_BTN_GHOST}
              >
                {lib.loading && <FiLoader className="motion-safe:animate-spin" aria-hidden />}
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

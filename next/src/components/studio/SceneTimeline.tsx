"use client";

import { useTranslation } from "react-i18next";
import SaveMediaButton from "@/components/ui/SaveMediaButton";
import {
  FiAlertTriangle,
  FiArrowLeft,
  FiArrowRight,
  FiCheck,
  FiFilm,
  FiLoader,
  FiPlay,
  FiRefreshCw,
  FiTrash2,
} from "react-icons/fi";

export type StudioScene = {
  id: number;
  order: number;
  preset: {
    id: number;
    title: string;
    credits?: number;
    duration?: number;
    /** Обложка сцены из библиотеки — то, что видно у черновика. */
    poster?: string;
  };
  /** Кем снимается эта сцена: свой герой или герой всего мультфильма. */
  character?: { id: number; name: string; image: string } | null;
  keyframe: string;
  /** Готовый ролик этой пары «герой + сцена», снятый раньше кем-то, — превью в движении до съёмки. */
  preview_video?: string;
  video: string;
  status: "draft" | "new" | "keyframe" | "video" | "ready" | "failed";
  error: string;
  credits_spent: number;
};

/**
 * SceneTimeline — лента сцен будущего мультфильма.
 *
 * Кадр показывается СРАЗУ, как только нарисован, ещё до готового ролика: так
 * человек за секунды видит, что получит, а не смотрит в пустой прямоугольник
 * пару минут. Готовая сцена превращается в плеер прямо в ленте.
 *
 * Порядок меняется стрелками, а не перетаскиванием: на телефоне drag-and-drop
 * в горизонтальном списке дерётся со скроллом, а стрелки работают везде
 * одинаково.
 */

/** Ключ подписи состояния — сам текст берётся из локали (studio_ui.st_*). */
const STATUS_KEY: Record<StudioScene["status"], string> = {
  draft: "st_draft",
  new: "st_new",
  keyframe: "st_keyframe",
  video: "st_video",
  ready: "st_ready",
  failed: "st_failed",
};

export default function SceneTimeline({
  scenes,
  busyIds,
  onMove,
  onRetry,
  onDelete,
  onRender,
  characters = [],
  onPickCharacter,
}: {
  scenes: StudioScene[];
  busyIds: Set<number>;
  onMove: (scene: StudioScene, dir: -1 | 1) => void;
  onRetry: (scene: StudioScene) => void;
  onDelete: (scene: StudioScene) => void;
  onRender: (scene: StudioScene) => void;
  /** Кого можно поставить на эту сцену. */
  characters?: { id: number; name: string; image: string }[];
  onPickCharacter?: (scene: StudioScene, characterId: number) => void;
}) {
  const { t } = useTranslation("common");

  if (!scenes.length) {
    return (
      <div className="rounded-2xl border border-dashed border-border p-6 text-center text-sm text-muted">
        {t("studio_ui.timeline_empty")}
      </div>
    );
  }

  return (
    <div className="flex gap-3 overflow-x-auto pb-2">
      {scenes.map((s, i) => {
        const working = s.status === "new" || s.status === "keyframe" || s.status === "video";
        const busy = busyIds.has(s.id);
        return (
          <div
            key={s.id}
            className="flex w-56 shrink-0 flex-col gap-2 rounded-2xl border border-border bg-surface p-2.5"
          >
            <div className="flex items-center gap-1.5 text-[11px] text-muted-2">
              <span className="grid size-5 shrink-0 place-items-center rounded-full bg-accent text-[10px] font-bold text-on-accent">
                {i + 1}
              </span>
              <span className="truncate font-medium text-foreground">{s.preset.title}</span>
            </div>

            {/* Герой этой сцены. У черновика его можно сменить — так во второй
                сцене появляется другой персонаж, и история собирается из
                нескольких героев, а не одного. */}
            {s.character && (
              <div className="flex items-center gap-1.5">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={s.character.image}
                  alt=""
                  loading="lazy"
                  className="size-5 shrink-0 rounded-full object-cover"
                />
                <span className="truncate text-[11px] text-muted-2">{s.character.name}</span>
                {s.status === "draft" && characters.length > 1 && onPickCharacter && (
                  <select
                    value={s.character.id}
                    onChange={(e) => onPickCharacter(s, Number(e.target.value))}
                    title={t("studio_ui.scene_hero_change")}
                    className="ml-auto max-w-[7rem] shrink-0 rounded-md border border-border bg-surface-2 px-1.5 py-0.5 text-[11px] text-muted outline-none focus:border-accent cursor-pointer"
                  >
                    {characters.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            )}

            <div className="relative aspect-video overflow-hidden rounded-xl bg-surface-2">
              {s.video ? (
                <video
                  src={s.video}
                  controls
                  playsInline
                  preload="metadata"
                  poster={s.keyframe || undefined}
                  className="h-full w-full object-cover"
                />
              ) : s.preview_video && !working ? (
                <>
                  {/* Клиент: до съёмки человек должен видеть сцену с героем в
                      движении. Если эту пару уже снимали — показываем тот ролик,
                      он заранее готов и ничего не стоит. */}
                  <video
                    src={s.preview_video}
                    poster={s.keyframe || undefined}
                    autoPlay
                    muted
                    loop
                    playsInline
                    preload="metadata"
                    className="h-full w-full object-cover"
                  />
                  <span className="pointer-events-none absolute left-1.5 top-1.5 rounded-full bg-black/55 px-1.5 py-0.5 text-[10px] font-medium text-white backdrop-blur-sm">
                    {t("studio_ui.preview_badge")}
                  </span>
                </>
              ) : s.keyframe || s.preset.poster ? (
                <>
                  {/* Пока своего кадра нет, показываем обложку сцены: у
                      черновика ничего не грузится, и крутилка на его месте
                      читалась как зависшая загрузка (жалоба клиента).
                      Кадр с героем чуть движется камерой — это не действие
                      героя, а живой предпросмотр, и подписан он честно. */}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={s.keyframe || s.preset.poster}
                    alt=""
                    loading="lazy"
                    decoding="async"
                    className={`h-full w-full object-cover ${
                      s.keyframe ? (s.status === "draft" ? "studio-live" : "") : "opacity-70"
                    }`}
                  />
                  {s.keyframe && s.status === "draft" && (
                    <span className="pointer-events-none absolute left-1.5 top-1.5 rounded-full bg-black/55 px-1.5 py-0.5 text-[10px] font-medium text-white backdrop-blur-sm">
                      {t("studio_ui.frame_badge")}
                    </span>
                  )}
                  {working && (
                    <span className="absolute inset-0 grid place-items-center bg-black/45 text-white">
                      <FiLoader className="animate-spin text-2xl" />
                    </span>
                  )}
                  {s.status === "failed" && (
                    <span className="absolute inset-0 grid place-items-center bg-black/45">
                      <FiAlertTriangle className="text-2xl text-red-400" />
                    </span>
                  )}
                </>
              ) : (
                <span className="grid h-full w-full place-items-center text-muted-2">
                  {s.status === "failed" ? (
                    <FiAlertTriangle className="text-2xl text-red-400" />
                  ) : working ? (
                    <FiLoader className="animate-spin text-2xl" />
                  ) : (
                    <FiFilm className="text-2xl" />
                  )}
                </span>
              )}
            </div>

            <div className="flex items-center gap-1 text-[11px]">
              {s.status === "ready" ? (
                <span className="inline-flex items-center gap-1 text-emerald-400">
                  <FiCheck /> {t("studio_ui.st_ready")}
                </span>
              ) : s.status === "failed" ? (
                <span className="truncate text-red-400" title={s.error}>
                  {t("studio_ui.st_failed")}
                </span>
              ) : s.status === "draft" ? (
                <span className="text-muted-2">
                  {s.preset.credits ? `${s.preset.credits} ${t("studio_ui.credits_short")}` : ""}
                </span>
              ) : (
                <span className="text-muted">{t(`studio_ui.${STATUS_KEY[s.status]}`)}…</span>
              )}
              {s.credits_spent > 0 && (
                <span className="ml-auto shrink-0 text-muted-2">{s.credits_spent} {t("studio_ui.credits_short")}</span>
              )}
            </div>

            {/* Черновик снимается отсюда: клиент просил, чтобы человек сначала
                набирал ленту, а потом генерировал любую сцену из неё. */}
            {s.status === "draft" && (
              <button
                type="button"
                onClick={() => onRender(s)}
                disabled={busy}
                className="mb-1 inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-xs font-bold text-on-accent transition-colors hover:bg-accent-strong disabled:opacity-60 cursor-pointer"
              >
                {busy ? <FiLoader className="animate-spin" /> : <FiPlay />}
                {t("studio_ui.render_scene")}
              </button>
            )}

            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => onMove(s, -1)}
                disabled={i === 0 || busy}
                title={t("studio_ui.move_up")}
                className="grid size-7 place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-foreground disabled:opacity-30 cursor-pointer"
              >
                <FiArrowLeft />
              </button>
              <button
                type="button"
                onClick={() => onMove(s, 1)}
                disabled={i === scenes.length - 1 || busy}
                title={t("studio_ui.move_down")}
                className="grid size-7 place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-foreground disabled:opacity-30 cursor-pointer"
              >
                <FiArrowRight />
              </button>
              {(s.status === "failed" || s.status === "ready") && (
                <button
                  type="button"
                  onClick={() => onRetry(s)}
                  disabled={busy}
                  // Кадр не трогаем: пересобираем только ролик, поэтому герой и
                  // композиция остаются прежними, а платим лишь за видео.
                  title={t(s.status === "failed" ? "studio_ui.retry_failed" : "studio_ui.retry")}
                  className="grid size-7 place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-accent disabled:opacity-40 cursor-pointer"
                >
                  <FiRefreshCw className={busy ? "animate-spin" : ""} />
                </button>
              )}
              {/* Скачать отдельную сцену: клиент просил забирать не только
                  готовый мультфильм, но и каждый ролик по отдельности —
                  сцену часто выкладывают саму по себе. */}
              {s.video && (
                <SaveMediaButton
                  url={s.video}
                  filename={`esai-scene-${s.order + 1}.mp4`}
                  label={t("studio_ui.download_scene")}
                  iconClassName=""
                  className="grid size-7 place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-accent cursor-pointer"
                />
              )}
              <button
                type="button"
                onClick={() => onDelete(s)}
                disabled={busy}
                title={t("studio_ui.remove")}
                className="ml-auto grid size-7 place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-red-400 disabled:opacity-40 cursor-pointer"
              >
                <FiTrash2 />
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

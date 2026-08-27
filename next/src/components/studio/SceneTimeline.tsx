"use client";

import {
  FiAlertTriangle,
  FiArrowLeft,
  FiArrowRight,
  FiCheck,
  FiLoader,
  FiRefreshCw,
  FiTrash2,
} from "react-icons/fi";

export type StudioScene = {
  id: number;
  order: number;
  preset: { id: number; title: string };
  keyframe: string;
  video: string;
  status: "new" | "keyframe" | "video" | "ready" | "failed";
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

const STATUS_LABEL: Record<StudioScene["status"], string> = {
  new: "В очереди",
  keyframe: "Рисуется кадр",
  video: "Оживляется",
  ready: "Готова",
  failed: "Не получилось",
};

export default function SceneTimeline({
  scenes,
  busyIds,
  onMove,
  onRetry,
  onDelete,
}: {
  scenes: StudioScene[];
  busyIds: Set<number>;
  onMove: (scene: StudioScene, dir: -1 | 1) => void;
  onRetry: (scene: StudioScene) => void;
  onDelete: (scene: StudioScene) => void;
}) {
  if (!scenes.length) {
    return (
      <div className="rounded-2xl border border-dashed border-border p-6 text-center text-sm text-muted">
        Сцен пока нет. Выберите сцену выше — она появится здесь.
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
              ) : s.keyframe ? (
                <>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={s.keyframe} alt="" className="h-full w-full object-cover" />
                  {working && (
                    <span className="absolute inset-0 grid place-items-center bg-black/45 text-white">
                      <FiLoader className="animate-spin text-2xl" />
                    </span>
                  )}
                </>
              ) : (
                <span className="grid h-full w-full place-items-center text-muted-2">
                  {s.status === "failed" ? (
                    <FiAlertTriangle className="text-2xl text-red-400" />
                  ) : (
                    <FiLoader className="animate-spin text-2xl" />
                  )}
                </span>
              )}
            </div>

            <div className="flex items-center gap-1 text-[11px]">
              {s.status === "ready" ? (
                <span className="inline-flex items-center gap-1 text-emerald-400">
                  <FiCheck /> {STATUS_LABEL.ready}
                </span>
              ) : s.status === "failed" ? (
                <span className="truncate text-red-400" title={s.error}>
                  {STATUS_LABEL.failed}
                </span>
              ) : (
                <span className="text-muted">{STATUS_LABEL[s.status]}…</span>
              )}
              {s.credits_spent > 0 && (
                <span className="ml-auto shrink-0 text-muted-2">{s.credits_spent} кр</span>
              )}
            </div>

            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => onMove(s, -1)}
                disabled={i === 0 || busy}
                title="Раньше"
                className="grid size-7 place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-foreground disabled:opacity-30 cursor-pointer"
              >
                <FiArrowLeft />
              </button>
              <button
                type="button"
                onClick={() => onMove(s, 1)}
                disabled={i === scenes.length - 1 || busy}
                title="Позже"
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
                  title={s.status === "failed" ? "Попробовать снова" : "Переснять ролик"}
                  className="grid size-7 place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-accent disabled:opacity-40 cursor-pointer"
                >
                  <FiRefreshCw className={busy ? "animate-spin" : ""} />
                </button>
              )}
              <button
                type="button"
                onClick={() => onDelete(s)}
                disabled={busy}
                title="Убрать сцену"
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

"use client";

/**
 * Видеостудия, композер: слоты «Первый кадр» и «Последний кадр» (§0 п. 9).
 *
 * Кадры и фото-референсы — разные режимы API: кадр задаёт начало (конец)
 * ролика, @Image N — «кто и что в кадре». Поэтому слоты стоят отдельно от
 * лотка. Показываются у видео, если модель умеет кадры (caps.frames), — и
 * всегда, когда кадр уже задан: чтобы его можно было убрать, если новая
 * модель кадры не принимает (компилятор объяснит, почему).
 * Пустой слот: «Загрузить фото» или «Из моих материалов». Чего модель не
 * умеет — видно словами, а не только серым (§9.8).
 */
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiFolder, FiPlus, FiUpload } from "react-icons/fi";
import type { ComposerFrames, FrameSlot, ModelJSON, RefLabels, Uid } from "@/lib/vstudio/types";
import AssetChip from "./AssetChip";
import type { ChipHandlers } from "./AssetTray";
import { ct } from "./composerText";
import AnchoredPopover from "./Popover";

const SLOTS: readonly FrameSlot[] = ["first_frame", "last_frame"];

export type FrameSlotsProps = {
  frames: ComposerFrames;
  model: ModelJSON | null;
  labels: RefLabels;
  flagged: ReadonlySet<Uid>;
  handlers: ChipHandlers;
  onUpload: (slot: FrameSlot) => void;
  onLibrary: (slot: FrameSlot) => void;
  /** Телефон: без подписи «Кадры», слоты в полосе лотка. */
  compact?: boolean;
};

/** Показывать ли слоты вообще. */
export function showFrameSlots(kind: string, model: ModelJSON | null, frames: ComposerFrames): boolean {
  if (frames.first_frame || frames.last_frame) return true;
  return kind === "video" && Boolean(model && (model.caps.frames || []).length);
}

function EmptySlot({
  slot,
  supported,
  compact,
  onUpload,
  onLibrary,
}: {
  slot: FrameSlot;
  supported: boolean;
  compact?: boolean;
  onUpload: () => void;
  onLibrary: () => void;
}) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLButtonElement | null>(null);
  const name = slot === "first_frame" ? ct(t, "tray.firstFrame") : ct(t, "tray.lastFrame");
  if (!supported) return null;
  return (
    <>
      <button
        ref={anchor}
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        className={`inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-xl border border-dashed border-border-strong px-3 text-xs font-medium text-muted transition-colors hover:border-accent hover:text-foreground cursor-pointer ${
          compact ? "px-2.5" : ""
        }`}
      >
        <FiPlus aria-hidden className="shrink-0" />
        <span className="whitespace-nowrap">{name}</span>
      </button>
      <AnchoredPopover anchor={anchor} open={open} onClose={() => setOpen(false)} role="menu" ariaLabel={name} autoFocus>
        <div className="flex w-56 flex-col p-1.5">
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onUpload();
            }}
            className="flex min-h-11 items-center gap-2.5 rounded-lg px-2.5 text-left text-sm hover:bg-surface-2 focus-visible:bg-surface-2 focus-visible:outline-none md:min-h-9 cursor-pointer"
          >
            <FiUpload className="size-4 text-muted" aria-hidden />
            {ct(t, "tray.upload")}
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onLibrary();
            }}
            className="flex min-h-11 items-center gap-2.5 rounded-lg px-2.5 text-left text-sm hover:bg-surface-2 focus-visible:bg-surface-2 focus-visible:outline-none md:min-h-9 cursor-pointer"
          >
            <FiFolder className="size-4 text-muted" aria-hidden />
            {ct(t, "tray.fromLibrary")}
          </button>
        </div>
      </AnchoredPopover>
    </>
  );
}

export default function FrameSlots({ frames, model, labels, flagged, handlers, onUpload, onLibrary, compact }: FrameSlotsProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const caps = model?.caps.frames || [];
  const modelName = model?.name || "";
  const reasons: string[] = [];
  if (model && !caps.includes("first_frame")) reasons.push(ct(t, "tray.frameUnsupported", { model: modelName }));
  else if (model && !caps.includes("last_frame")) reasons.push(ct(t, "tray.lastFrameUnsupported", { model: modelName }));

  const slots = SLOTS.map((slot) => {
    const item = frames[slot];
    if (item) {
      const label = item.assetUid ? labels[item.assetUid] ?? null : null;
      return (
        <AssetChip
          key={slot}
          item={item}
          label={label}
          compact={compact}
          flagged={Boolean((item.assetUid && flagged.has(item.assetUid)) || (model && !caps.includes(slot)))}
          retryable={item.status === "failed" && !item.assetUid}
          onRetry={() => handlers.retry(item.lid)}
          onCancel={() => handlers.cancel(item.lid)}
          onRemove={() => handlers.remove(item.lid)}
          onInclude={(v) => handlers.include(item.lid, v)}
          onSlot={(s) => handlers.slot(item.lid, s)}
          onInsert={() => handlers.insert(item.lid)}
        />
      );
    }
    return (
      <EmptySlot
        key={slot}
        slot={slot}
        supported={caps.includes(slot)}
        compact={compact}
        onUpload={() => onUpload(slot)}
        onLibrary={() => onLibrary(slot)}
      />
    );
  });

  if (compact) {
    return (
      <div className="flex shrink-0 items-center gap-2 border-l border-border pl-2" role="group" aria-label={ct(t, "composer.frames")}>
        {slots}
      </div>
    );
  }
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1" role="group" aria-label={ct(t, "composer.frames")}>
      <span className="text-[11px] font-semibold uppercase tracking-wide text-muted">{ct(t, "composer.frames")}</span>
      {slots}
      {reasons.length > 0 && <span className="min-w-0 text-[11px] leading-snug text-muted-2">{reasons[0]}</span>}
    </div>
  );
}

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
import { FiFolder, FiSkipBack, FiSkipForward, FiUpload } from "react-icons/fi";
import type { ComposerFrames, FrameSlot, ModelJSON, RefLabels, Uid } from "@/lib/vstudio/types";
import { VS_FOCUS, VS_MENU_ITEM, vx } from "../ui/skin";
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
  /** Телефон: слоты в полосе лотка, причина — в подсказках компилятора. */
  compact?: boolean;
  /** Подсветить пустые слоты: сюда привела карточка «Первый и последний кадр». */
  pulse?: boolean;
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
  pulse,
  onUpload,
  onLibrary,
}: {
  slot: FrameSlot;
  supported: boolean;
  compact?: boolean;
  pulse?: boolean;
  onUpload: () => void;
  onLibrary: () => void;
}) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLButtonElement | null>(null);
  const name = slot === "first_frame" ? ct(t, "tray.firstFrame") : ct(t, "tray.lastFrame");
  const Icon = slot === "first_frame" ? FiSkipBack : FiSkipForward;
  if (!supported) return null;
  return (
    <>
      <button
        ref={anchor}
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        className={vx(
          "inline-flex min-h-11 shrink-0 cursor-pointer items-center gap-1.5 rounded-xl border border-dashed text-xs font-medium transition-colors hover:border-vs-accent/60 hover:text-foreground md:min-h-10",
          VS_FOCUS,
          compact ? "px-2.5" : "px-3",
          // Кольцо vs-ready расходится от слота, пока подсветка включена; без анимации остаётся золотая кромка.
          // Пунктир на белом бледнее сплошной линии той же плотности — в светлой теме он плотнее.
          pulse
            ? "vs-ready border-vs-accent/70 text-foreground"
            : open
              ? "border-vs-ink/45 text-foreground dark:border-vs-ink/30"
              : "border-vs-ink/25 text-muted dark:border-vs-ink/15",
        )}
      >
        <Icon aria-hidden className="size-3.5 shrink-0" />
        <span className="whitespace-nowrap">{name}</span>
      </button>
      <AnchoredPopover anchor={anchor} open={open} onClose={() => setOpen(false)} role="menu" ariaLabel={name} autoFocus closeOnTabOut>
        <div className="flex w-56 flex-col p-1.5">
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onUpload();
            }}
            className={VS_MENU_ITEM}
          >
            <FiUpload className="size-4 shrink-0 text-muted" aria-hidden />
            {ct(t, "tray.upload")}
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onLibrary();
            }}
            className={VS_MENU_ITEM}
          >
            <FiFolder className="size-4 shrink-0 text-muted" aria-hidden />
            {ct(t, "tray.fromLibrary")}
          </button>
        </div>
      </AnchoredPopover>
    </>
  );
}

export default function FrameSlots({ frames, model, labels, flagged, handlers, onUpload, onLibrary, compact, pulse }: FrameSlotsProps) {
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
          compact
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
        pulse={pulse}
        onUpload={() => onUpload(slot)}
        onLibrary={() => onLibrary(slot)}
      />
    );
  });

  // data-vs-frames — по нему композер находит слоты, когда к ним ведёт первый экран (composerBus.focusFrames).
  if (compact) {
    return (
      <div
        className="flex shrink-0 items-center gap-1.5 border-l border-vs-ink/10 pl-2"
        role="group"
        aria-label={ct(t, "composer.frames")}
        data-vs-frames=""
      >
        {slots}
      </div>
    );
  }
  return (
    <div className="flex shrink-0 flex-col items-end gap-1" role="group" aria-label={ct(t, "composer.frames")} data-vs-frames="">
      <div className="flex items-center gap-1.5">{slots}</div>
      {reasons.length > 0 && <span className="max-w-[20rem] text-right text-[11px] leading-snug text-muted-2">{reasons[0]}</span>}
    </div>
  );
}

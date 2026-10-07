"use client";

/**
 * Видеостудия, композер: лоток материалов (§9.2, §9.7).
 *
 * Фото-референсы по порядку — их номера и есть @Image N (§4.2), поэтому
 * перестановка сразу перенумеровывает чипы и в лотке, и в тексте. На
 * компьютере чип перетаскивается мышью (его же можно бросить в текст — станет
 * тегом), на телефоне — «Сдвинуть влево/вправо» в меню чипа.
 * Рядом кнопки «+ Фото» (загрузить), «✨ Картинка» (создать) и «Мои материалы».
 */
import { useState, type DragEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { FiFolder, FiPlus } from "react-icons/fi";
import { IoSparklesOutline } from "react-icons/io5";
import { copyTagFor } from "@/lib/vstudio/labels";
import type { FrameSlot, InputSlot, RefLabels, TrayItem, Uid } from "@/lib/vstudio/types";
import { VS_PILL, VS_PILL_ON, vx } from "../ui/skin";
import AssetChip from "./AssetChip";
import { ct } from "./composerText";

/** Действия над чипом по lid — их даёт композер. */
export type ChipHandlers = {
  retry: (lid: string) => void;
  cancel: (lid: string) => void;
  remove: (lid: string) => void;
  include: (lid: string, included: boolean) => void;
  role: (lid: string, role: string) => void;
  slot: (lid: string, slot: InputSlot) => void;
  move: (lid: string, delta: -1 | 1) => void;
  moveTo: (lid: string, to: number) => void;
  insert: (lid: string) => void;
};

export type AssetTrayProps = {
  items: TrayItem[];
  labels: RefLabels;
  flagged: ReadonlySet<Uid>;
  /** Какие кадры умеет модель — для «Сделать первым кадром» в меню. */
  frameSlots: readonly FrameSlot[];
  handlers: ChipHandlers;
  mobile: boolean;
  onAdd: () => void;
  onGenerate: () => void;
  onLibrary: () => void;
  /** Слоты кадров в той же полосе (телефон). */
  trailing?: ReactNode;
  /** Есть ли модели картинок (иначе «Создать картинку» не показываем). */
  canGenerate: boolean;
};

const LID_TYPE = "application/x-vs-lid";

function ToolButton({
  onClick,
  icon,
  label,
  short,
  showLabel,
  accent,
}: {
  onClick: () => void;
  icon: ReactNode;
  /** Полное название — подсказка и имя для экранного диктора. */
  label: string;
  /** Короткая подпись на самой кнопке; без неё — полное название. */
  short?: string;
  showLabel: boolean;
  accent?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={vx(
        VS_PILL,
        // Телефон — 44 px под палец; с 768 px — 40 px, в рост чипов материалов.
        "max-md:!h-11 md:!h-10",
        accent && VS_PILL_ON,
        !showLabel && "w-10 justify-center !px-0 max-md:w-11",
      )}
    >
      <span className="text-[15px]">{icon}</span>
      {showLabel && <span className="whitespace-nowrap">{short || label}</span>}
    </button>
  );
}

export default function AssetTray({
  items,
  labels,
  flagged,
  frameSlots,
  handlers,
  mobile,
  onAdd,
  onGenerate,
  onLibrary,
  trailing,
  canGenerate,
}: AssetTrayProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const [drag, setDrag] = useState<{ lid: string; over: number | null; after: boolean } | null>(null);
  const empty = items.length === 0;

  const onOver = (index: number) => (e: DragEvent<HTMLDivElement>) => {
    if (!drag || !e.dataTransfer.types.includes(LID_TYPE)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    const r = e.currentTarget.getBoundingClientRect();
    const after = e.clientX > r.left + r.width / 2;
    if (drag.over !== index || drag.after !== after) setDrag({ ...drag, over: index, after });
  };

  const onDrop = (index: number) => (e: DragEvent<HTMLDivElement>) => {
    if (!drag || !e.dataTransfer.types.includes(LID_TYPE)) return;
    e.preventDefault();
    e.stopPropagation();
    const from = items.findIndex((i) => i.lid === drag.lid);
    let to = index + (drag.after ? 1 : 0);
    if (from >= 0 && from < to) to -= 1;
    if (from >= 0 && to !== from) handlers.moveTo(drag.lid, to);
    setDrag(null);
  };

  return (
    // Поля 2 px: полоса прокручивается, и кольцо фокуса у кнопок и чипов иначе обрезалось бы.
    <div
      className="-m-0.5 flex min-w-0 items-center gap-1.5 overflow-x-auto overscroll-x-contain p-0.5 [scrollbar-color:var(--border-strong)_transparent] [scrollbar-width:thin] max-md:[scrollbar-width:none]"
      role="group"
      aria-label={ct(t, "composer.materials")}
    >
      <ToolButton
        onClick={onAdd}
        icon={<FiPlus />}
        label={ct(t, "composer.attach")}
        short={ct(t, "dock.photo")}
        showLabel={!mobile && empty}
      />
      {canGenerate && (
        <ToolButton
          onClick={onGenerate}
          icon={<IoSparklesOutline />}
          label={ct(t, "composer.generate")}
          short={ct(t, "dock.image")}
          showLabel={!mobile}
          accent
        />
      )}
      {!mobile && <ToolButton onClick={onLibrary} icon={<FiFolder />} label={ct(t, "composer.library")} showLabel={empty} />}

      {items.length > 0 && (
        <ul className="flex items-center gap-1.5" aria-label={ct(t, "composer.materials")}>
          {items.map((item, index) => {
            const label = item.assetUid ? labels[item.assetUid] ?? null : null;
            const loading = item.status === "uploading" || item.status === "processing";
            const canDrag = !mobile && !loading && items.length > 1;
            const over = drag && drag.over === index && drag.lid !== item.lid;
            return (
              <li
                key={item.lid}
                className={`relative flex ${over ? (drag?.after ? "after:absolute after:-right-1 after:inset-y-1 after:w-0.5 after:rounded after:bg-accent" : "before:absolute before:-left-1 before:inset-y-1 before:w-0.5 before:rounded before:bg-accent") : ""} ${
                  drag?.lid === item.lid ? "opacity-50" : ""
                }`}
              >
                <AssetChip
                  item={item}
                  label={label}
                  flagged={Boolean(item.assetUid && flagged.has(item.assetUid))}
                  frameSlots={frameSlots}
                  canMoveLeft={index > 0}
                  canMoveRight={index < items.length - 1}
                  retryable={item.status === "failed" && !item.assetUid}
                  onRetry={() => handlers.retry(item.lid)}
                  onCancel={() => handlers.cancel(item.lid)}
                  onRemove={() => handlers.remove(item.lid)}
                  onInclude={(v) => handlers.include(item.lid, v)}
                  onRole={(r) => handlers.role(item.lid, r)}
                  onSlot={(s) => handlers.slot(item.lid, s)}
                  onMove={(d) => handlers.move(item.lid, d)}
                  onInsert={() => handlers.insert(item.lid)}
                  dragProps={{
                    draggable: canDrag,
                    onDragStart: canDrag
                      ? (e) => {
                          e.dataTransfer.effectAllowed = "copyMove";
                          e.dataTransfer.setData(LID_TYPE, item.lid);
                          // Бросили в текст — встанет тегом (вставка «@Image 1» превращается в чип).
                          if (label && label.n) e.dataTransfer.setData("text/plain", `${copyTagFor(label)} `);
                          setDrag({ lid: item.lid, over: null, after: false });
                        }
                      : undefined,
                    onDragEnd: () => setDrag(null),
                    onDragOver: onOver(index),
                    onDrop: onDrop(index),
                  }}
                />
              </li>
            );
          })}
        </ul>
      )}
      {trailing}
    </div>
  );
}

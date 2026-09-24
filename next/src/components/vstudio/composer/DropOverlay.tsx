"use client";

/**
 * Видеостудия: зона перетаскивания на всю центральную колонку (§9.6).
 *
 * Ставится оболочкой поверх ленты и композера (VStudioShell.centerOverlay).
 * Пока над окном тащат файлы, колонка подсвечивается: «Отпустите, чтобы
 * добавить фото в запрос». Брошенное в колонку уходит в лоток через
 * композер (composerBus). Брошенное прямо в текст забирает редактор — там
 * тег встанет в точку броска, а сюда событие доходит с defaultPrevented:
 * зона только снимает подсветку и второй раз файл не загружает.
 * Бросок мимо колонки гасим: иначе браузер открыл бы картинку вместо студии.
 * Композера нет на странице («Проект не найден») — зона не включается.
 */
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";
import { FiUploadCloud } from "react-icons/fi";
import { imageFiles } from "../editor/inputHelpers";
import { composerHandlers, composerPresent, subscribeComposerBus } from "./composerBus";
import { ct } from "./composerText";

function hasFiles(e: DragEvent): boolean {
  const types = e.dataTransfer?.types;
  return Boolean(types && Array.from(types).includes("Files"));
}

export default function DropOverlay() {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const present = useSyncExternalStore(subscribeComposerBus, composerPresent, () => false);
  const [active, setActive] = useState(false);
  const zoneRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!present) return;
    let depth = 0;
    const inColumn = (e: DragEvent) => {
      const column = zoneRef.current?.parentElement;
      return Boolean(column && e.target instanceof Node && column.contains(e.target));
    };
    const onEnter = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      depth += 1;
      setActive(true);
    };
    const onOver = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = inColumn(e) ? "copy" : "none";
    };
    const onLeave = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) setActive(false);
    };
    const onDrop = (e: DragEvent) => {
      depth = 0;
      setActive(false);
      if (!hasFiles(e) || e.defaultPrevented) return;
      e.preventDefault();
      if (!inColumn(e)) return;
      const files = imageFiles(e.dataTransfer);
      const all = Array.from(e.dataTransfer?.files || []);
      // Не картинки (видео, PDF) тоже отдаём: композер объяснит, почему не подошло.
      const list = files.length ? files : all;
      if (list.length) void composerHandlers()?.upload(list, { via: "drop" });
    };
    const reset = () => {
      depth = 0;
      setActive(false);
    };
    window.addEventListener("dragenter", onEnter);
    window.addEventListener("dragover", onOver);
    window.addEventListener("dragleave", onLeave);
    window.addEventListener("drop", onDrop);
    // Подсветку снимаем на любом броске, даже если его кто-то остановит по
    // дороге (stopPropagation): иначе панель «Отпустите…» зависала поверх ленты.
    window.addEventListener("drop", reset, true);
    window.addEventListener("dragend", reset);
    window.addEventListener("blur", reset);
    return () => {
      window.removeEventListener("dragenter", onEnter);
      window.removeEventListener("dragover", onOver);
      window.removeEventListener("dragleave", onLeave);
      window.removeEventListener("drop", onDrop);
      window.removeEventListener("drop", reset, true);
      window.removeEventListener("dragend", reset);
      window.removeEventListener("blur", reset);
    };
  }, [present]);

  return (
    <div
      ref={zoneRef}
      aria-hidden={!active}
      className={`pointer-events-none absolute inset-2 z-30 flex items-center justify-center rounded-2xl border-2 border-dashed transition-opacity duration-150 ${
        active && present ? "border-accent bg-background/80 opacity-100 backdrop-blur-[2px]" : "border-transparent opacity-0"
      }`}
    >
      {active && present && (
        <div className="flex flex-col items-center gap-2 px-6 text-center" role="status">
          <FiUploadCloud className="size-10 text-accent-strong" aria-hidden />
          <div className="text-base font-semibold text-foreground">{ct(t, "tray.dropHere")}</div>
          <div className="text-xs text-muted">{ct(t, "tray.dropHint")}</div>
        </div>
      )}
    </div>
  );
}

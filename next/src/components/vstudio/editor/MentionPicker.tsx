"use client";

/**
 * Видеостудия: выбор материала по «@» (§9.5, §9.7).
 *
 * Компьютер — всплывающий список у курсора, телефон — нижняя шторка с сеткой
 * в 3 колонки над клавиатурой (высота из visualViewport). Разделы: «В этом
 * запросе», «Мои материалы», «Загрузить фото», «Создать картинку». Фильтр —
 * текст после «@» («@фо», «@im», «@2»). Клавиши ↑↓ Enter Esc приходят из
 * редактора через handle.keyDown: фокус остаётся в тексте, человек продолжает
 * печатать. Нажатия внутри списка не уводят фокус из редактора.
 */
import { autoUpdate, computePosition, flip, offset, shift, size } from "@floating-ui/dom";
import { useCallback, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState, type Ref, type RefObject } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { IoClose, IoCloudUploadOutline, IoImageOutline, IoSparklesOutline } from "react-icons/io5";
import { BACKEND } from "@/tools/fetchData";
import { filterPickerItems } from "@/lib/vstudio/labels";
import type { PickerItem, RefLabels } from "@/lib/vstudio/types";
import { VS_FOCUS, VS_LABEL, VS_MENU } from "../ui/skin";
import { chipClassName } from "./chipStyle";

export type PickerAction = "upload" | "generate";

export type MentionPickerHandle = {
  /** Клавиша из редактора; true — список её обработал. */
  keyDown: (event: KeyboardEvent) => boolean;
};

export type MentionPickerProps = {
  open: boolean;
  query: string;
  items: PickerItem[];
  labels: RefLabels;
  /** Прямоугольник курсора / «@» (компьютер). */
  anchor: () => DOMRect | null;
  mobile: boolean;
  onPick: (item: PickerItem) => void;
  onAction: (action: PickerAction) => void;
  onClose: () => void;
  /** Нажатия внутри этого элемента (редактор) — не «снаружи». */
  insideRef?: RefObject<HTMLElement | null>;
  handleRef?: Ref<MentionPickerHandle>;
  /** Не больше стольких материалов библиотеки в списке (остальное — фильтром). */
  libraryLimit?: number;
  /**
   * Поле ввода, в котором остаётся фокус (редактор или textarea). Пока список
   * открыт, на нём aria-controls / aria-activedescendant: фокус из текста не
   * уходит, и без этого экранный диктор не слышит, какой пункт выбран ↑↓.
   */
  owner?: () => HTMLElement | null;
};

type Row =
  | { kind: "item"; item: PickerItem }
  | { kind: "action"; action: PickerAction };

/** id списка: на него ссылается поле ввода (aria-controls), пункты — `${id}-${n}`. */
const PICKER_LIST_ID = "vs-mention-list";

/**
 * Строка списка — та же форма, что у пунктов меню студии (VS_MENU_ITEM), но
 * подсветка не по наведению, а по выбранному пункту: его двигают ↑↓ из текста.
 */
const ROW = "flex cursor-pointer items-center gap-2.5 rounded-xl px-2 text-sm text-foreground/85 transition-colors";
const ROW_ACTIVE = "bg-white/[0.08] text-foreground";

const abs = (url: string | null | undefined) => (url && url.startsWith("/") ? `${BACKEND}${url}` : url || "");

/** Высота клавиатуры телефона: насколько visualViewport короче окна. */
function useKeyboardInset(active: boolean): number {
  const [inset, setInset] = useState(0);
  useEffect(() => {
    if (!active || typeof window === "undefined") return;
    const vv = window.visualViewport;
    if (!vv) return;
    const read = () => setInset(Math.max(0, Math.round(window.innerHeight - vv.height - vv.offsetTop)));
    read();
    vv.addEventListener("resize", read);
    vv.addEventListener("scroll", read);
    return () => {
      vv.removeEventListener("resize", read);
      vv.removeEventListener("scroll", read);
    };
  }, [active]);
  return inset;
}

export default function MentionPicker({
  open,
  query,
  items,
  labels,
  anchor,
  mobile,
  onPick,
  onAction,
  onClose,
  insideRef,
  handleRef,
  libraryLimit = 60,
  owner,
}: MentionPickerProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const tx = useCallback(
    (key: string, ru: string, opts?: Record<string, unknown>) => String(t(key, { defaultValue: ru, ...(opts || {}) })),
    [t],
  );
  const boxRef = useRef<HTMLDivElement | null>(null);
  const anchorRef = useRef(anchor);
  const [active, setActive] = useState(0);
  const inset = useKeyboardInset(open && mobile);

  // Новый фильтр или новое открытие — снова первый пункт.
  const resetKey = `${open ? 1 : 0}|${query}`;
  const [seenKey, setSeenKey] = useState(resetKey);
  if (seenKey !== resetKey) {
    setSeenKey(resetKey);
    setActive(0);
  }

  const filtered = useMemo(() => filterPickerItems(items, labels, query), [items, labels, query]);
  const inRequest = useMemo(() => filtered.filter((i) => i.section === "in_request"), [filtered]);
  const library = useMemo(() => filtered.filter((i) => i.section === "library").slice(0, libraryLimit), [filtered, libraryLimit]);
  const rows: Row[] = useMemo(
    () => [
      ...inRequest.map((item) => ({ kind: "item" as const, item })),
      ...library.map((item) => ({ kind: "item" as const, item })),
      { kind: "action" as const, action: "upload" as const },
      { kind: "action" as const, action: "generate" as const },
    ],
    [inRequest, library],
  );

  const activate = useCallback(
    (row: Row | undefined) => {
      if (!row) return;
      if (row.kind === "item") onPick(row.item);
      else onAction(row.action);
    },
    [onPick, onAction],
  );

  const rowsRef = useRef(rows);
  const activeRef = useRef(active);
  // Клавиши приходят из редактора между рендерами — им нужны свежие значения.
  useLayoutEffect(() => {
    anchorRef.current = anchor;
    rowsRef.current = rows;
    activeRef.current = active;
  });

  useImperativeHandle(
    handleRef,
    () => ({
      keyDown(event: KeyboardEvent) {
        const list = rowsRef.current;
        const n = list.length;
        if (!n) return false;
        if (event.key === "ArrowDown") {
          setActive((i) => (i + 1) % n);
          return true;
        }
        if (event.key === "ArrowUp") {
          setActive((i) => (i - 1 + n) % n);
          return true;
        }
        if (event.key === "Enter" || event.key === "Tab") {
          if (event.isComposing) return false;
          activate(list[Math.min(activeRef.current, n - 1)]);
          return true;
        }
        return false;
      },
    }),
    [activate],
  );

  // Доступность: фокус остаётся в поле ввода, поэтому связь со списком и
  // выбранный пункт объявляем на нём (ARIA 1.2: textbox + listbox «всплывашка»).
  const ownerRef = useRef(owner);
  useLayoutEffect(() => {
    ownerRef.current = owner;
  });
  useEffect(() => {
    const el = ownerRef.current?.() ?? null;
    if (!open || !el) return;
    el.setAttribute("aria-controls", PICKER_LIST_ID);
    el.setAttribute("aria-autocomplete", "list");
    el.setAttribute("aria-haspopup", "listbox");
    return () => {
      el.removeAttribute("aria-controls");
      el.removeAttribute("aria-activedescendant");
      el.removeAttribute("aria-autocomplete");
      el.removeAttribute("aria-haspopup");
    };
  }, [open]);
  const activeIsOption = rows[active]?.kind === "item" || !mobile;
  useEffect(() => {
    const el = ownerRef.current?.() ?? null;
    if (!open || !el) return;
    if (rows.length && activeIsOption) el.setAttribute("aria-activedescendant", `${PICKER_LIST_ID}-${active}`);
    else el.removeAttribute("aria-activedescendant");
  }, [open, active, rows.length, activeIsOption]);

  // Активный пункт всегда виден.
  useEffect(() => {
    if (!open) return;
    const el = boxRef.current?.querySelector<HTMLElement>(`[data-row="${active}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  // Клик мимо списка и мимо редактора — закрыть.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      const target = e.target as Node | null;
      if (!target) return;
      if (boxRef.current?.contains(target) || insideRef?.current?.contains(target)) return;
      onClose();
    };
    document.addEventListener("pointerdown", onDown, true);
    return () => document.removeEventListener("pointerdown", onDown, true);
  }, [open, onClose, insideRef]);

  // Компьютер: список у курсора, переворачивается вверх, если снизу мало места.
  useLayoutEffect(() => {
    const el = boxRef.current;
    if (!open || mobile || !el) return;
    const reference = {
      getBoundingClientRect: () =>
        anchorRef.current() || insideRef?.current?.getBoundingClientRect() || new DOMRect(8, 8, 0, 0),
      contextElement: insideRef?.current ?? undefined,
    };
    const update = () => {
      computePosition(reference, el, {
        strategy: "fixed",
        placement: "bottom-start",
        middleware: [
          offset(6),
          flip({ padding: 8 }),
          shift({ padding: 8 }),
          size({
            padding: 8,
            apply({ availableHeight }) {
              el.style.maxHeight = `${Math.max(160, Math.min(380, Math.floor(availableHeight)))}px`;
            },
          }),
        ],
      }).then(({ x, y }) => {
        el.style.left = `${Math.round(x)}px`;
        el.style.top = `${Math.round(y)}px`;
        el.style.visibility = "visible";
      });
    };
    const cleanup = autoUpdate(reference, el, update);
    return cleanup;
  }, [open, mobile, insideRef, query]);

  if (!open || typeof document === "undefined") return null;

  // Нажатие внутри списка не должно забирать фокус у редактора (иначе на
  // телефоне прячется клавиатура, а на компьютере теряется курсор).
  const keepFocus = (e: React.PointerEvent | React.MouseEvent) => e.preventDefault();

  const sectionTitle = (text: string) => (
    <div className={`px-2.5 pt-2 pb-1 ${VS_LABEL}`}>{text}</div>
  );

  const actionMeta: Record<PickerAction, { icon: React.ReactNode; text: string }> = {
    upload: { icon: <IoCloudUploadOutline aria-hidden />, text: tx("picker.upload", "Загрузить фото") },
    generate: { icon: <IoSparklesOutline aria-hidden />, text: tx("picker.generate", "Создать картинку") },
  };

  const noMatches = Boolean(query) && inRequest.length + library.length === 0;
  const rowIndex = (row: Row) => rows.indexOf(row);
  const labelFor = (item: PickerItem) => labels[item.asset];

  const listId = PICKER_LIST_ID;

  if (mobile) {
    const itemRows = rows.filter((r): r is Extract<Row, { kind: "item" }> => r.kind === "item");
    const tile = (row: Extract<Row, { kind: "item" }>) => {
      const i = rowIndex(row);
      const label = labelFor(row.item);
      return (
        <button
          key={`${row.item.section}-${row.item.asset}`}
          id={`${listId}-${i}`}
          type="button"
          role="option"
          aria-selected={i === active}
          aria-label={label?.aria || row.item.label || tx("tray.photo", "Фото")}
          data-row={i}
          onPointerDown={keepFocus}
          onMouseDown={keepFocus}
          onClick={() => activate(row)}
          className={`relative aspect-square overflow-hidden rounded-xl border bg-surface-3 ${
            i === active ? "border-accent/70" : "border-white/10"
          }`}
        >
          {row.item.thumb ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={abs(row.item.thumb)} alt="" className="h-full w-full object-cover" loading="lazy" draggable={false} />
          ) : (
            <span className="grid h-full w-full place-items-center text-2xl text-muted-2">
              <IoImageOutline aria-hidden />
            </span>
          )}
          {label && (
            <span className={`absolute bottom-1 left-1 max-w-[calc(100%-0.5rem)] truncate ${chipClassName(label.state)}`}>
              {label.text}
            </span>
          )}
        </button>
      );
    };
    const inReqRows = itemRows.filter((r) => r.item.section === "in_request");
    const libRows = itemRows.filter((r) => r.item.section === "library");
    return createPortal(
      <div
        ref={boxRef}
        role="dialog"
        aria-label={tx("picker.title", "Материалы")}
        className="vs-glass fixed inset-x-0 z-[1050] flex max-h-[min(55dvh,26rem)] flex-col rounded-t-[24px] !border-x-0 !border-b-0"
        style={{ bottom: inset, paddingBottom: inset ? 0 : "env(safe-area-inset-bottom)" }}
        onPointerDown={keepFocus}
      >
        <div className="flex items-center justify-between gap-2 px-4 pt-3 pb-2">
          <div className="text-sm font-semibold text-foreground">{tx("picker.title", "Материалы")}</div>
          <button
            type="button"
            onClick={onClose}
            className={`grid size-11 place-items-center rounded-full text-xl text-muted transition-colors hover:bg-white/[0.08] hover:text-foreground ${VS_FOCUS}`}
            aria-label={tx("mobile.close", "Закрыть")}
          >
            <IoClose aria-hidden />
          </button>
        </div>
        <div className="grid grid-cols-2 gap-2 px-4 pb-2">
          {(["upload", "generate"] as const).map((a) => {
            const row = rows.find((r) => r.kind === "action" && r.action === a) as Row;
            const i = rowIndex(row);
            return (
              <button
                key={a}
                type="button"
                data-row={i}
                onPointerDown={keepFocus}
                onMouseDown={keepFocus}
                onClick={() => activate(row)}
                className={`flex min-h-11 items-center justify-center gap-2 rounded-xl border px-2.5 text-[13px] font-medium leading-tight text-foreground ${
                  i === active ? "border-accent/60 bg-white/[0.09]" : "border-white/10 bg-white/[0.05]"
                }`}
              >
                <span className="text-lg text-accent">{actionMeta[a].icon}</span>
                {actionMeta[a].text}
              </button>
            );
          })}
        </div>
        <div id={listId} role="listbox" className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-3">
          {inReqRows.length > 0 && (
            <>
              {sectionTitle(tx("picker.inRequest", "В этом запросе"))}
              <div className="grid grid-cols-3 gap-2">{inReqRows.map(tile)}</div>
            </>
          )}
          {libRows.length > 0 && (
            <>
              {sectionTitle(tx("picker.library", "Мои материалы"))}
              <div className="grid grid-cols-3 gap-2">{libRows.map(tile)}</div>
            </>
          )}
          {noMatches && <div className="px-1 py-3 text-sm text-muted">{tx("picker.empty", "Ничего не найдено")}</div>}
        </div>
      </div>,
      document.body,
    );
  }

  const itemRow = (row: Extract<Row, { kind: "item" }>) => {
    const i = rowIndex(row);
    const label = labelFor(row.item);
    const pending = row.item.status === "pending" || label?.state === "pending";
    return (
      <div
        key={`${row.item.section}-${row.item.asset}`}
        id={`${listId}-${i}`}
        role="option"
        aria-selected={i === active}
        data-row={i}
        onMouseDown={keepFocus}
        onMouseEnter={() => setActive(i)}
        onClick={() => activate(row)}
        className={`${ROW} py-1.5 ${i === active ? ROW_ACTIVE : ""}`}
      >
        <span className="grid size-9 shrink-0 place-items-center overflow-hidden rounded-lg border border-white/10 bg-surface-3 text-lg text-muted-2">
          {row.item.thumb ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={abs(row.item.thumb)} alt="" className="h-full w-full object-cover" loading="lazy" draggable={false} />
          ) : (
            <IoImageOutline aria-hidden />
          )}
        </span>
        <span className="flex min-w-0 flex-1 flex-col">
          {label ? (
            <span className={`self-start ${chipClassName(label.state)}`}>{label.text}</span>
          ) : (
            <span className="text-sm text-foreground">{tx("tray.photo", "Фото")}</span>
          )}
          {(row.item.role || pending) && (
            <span className="truncate text-xs text-muted">
              {pending ? tx("tray.pending", "Создаётся…") : row.item.role}
            </span>
          )}
        </span>
      </div>
    );
  };

  const actionRow = (row: Extract<Row, { kind: "action" }>) => {
    const i = rowIndex(row);
    return (
      <div
        key={row.action}
        id={`${listId}-${i}`}
        role="option"
        aria-selected={i === active}
        data-row={i}
        onMouseDown={keepFocus}
        onMouseEnter={() => setActive(i)}
        onClick={() => activate(row)}
        className={`${ROW} py-1.5 ${i === active ? ROW_ACTIVE : ""}`}
      >
        <span className="grid size-9 shrink-0 place-items-center rounded-lg border border-accent/25 bg-accent/[0.08] text-lg text-accent">
          {actionMeta[row.action].icon}
        </span>
        {actionMeta[row.action].text}
      </div>
    );
  };

  const inReqRows = rows.filter((r): r is Extract<Row, { kind: "item" }> => r.kind === "item" && r.item.section === "in_request");
  const libRows = rows.filter((r): r is Extract<Row, { kind: "item" }> => r.kind === "item" && r.item.section === "library");
  const actRows = rows.filter((r): r is Extract<Row, { kind: "action" }> => r.kind === "action");

  return createPortal(
    <div
      ref={boxRef}
      id={listId}
      role="listbox"
      aria-label={tx("picker.title", "Материалы")}
      className={`${VS_MENU} fixed left-0 top-0 z-[1050] w-[19rem] max-w-[calc(100vw-1rem)] overflow-y-auto overscroll-contain`}
      style={{ visibility: "hidden", maxHeight: 380 }}
      onMouseDown={keepFocus}
    >
      {inReqRows.length > 0 && (
        <>
          {sectionTitle(tx("picker.inRequest", "В этом запросе"))}
          {inReqRows.map(itemRow)}
        </>
      )}
      {libRows.length > 0 && (
        <>
          {sectionTitle(tx("picker.library", "Мои материалы"))}
          {libRows.map(itemRow)}
        </>
      )}
      {noMatches && <div className="px-2.5 py-2 text-sm text-muted">{tx("picker.empty", "Ничего не найдено")}</div>}
      <div className={inReqRows.length + libRows.length > 0 || noMatches ? "mt-1 border-t border-white/10 pt-1" : ""}>
        {actRows.map(actionRow)}
      </div>
      {!query && inReqRows.length + libRows.length > 0 && (
        <div className="px-2.5 pb-1 pt-1.5 text-[11px] text-muted-2">
          {tx("picker.filterHint", "Печатайте после @, чтобы найти: @фо, @im, @2")}
        </div>
      )}
    </div>,
    document.body,
  );
}

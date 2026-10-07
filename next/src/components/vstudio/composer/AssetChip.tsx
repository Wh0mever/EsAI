"use client";

/**
 * Видеостудия, композер: один материал в лотке или в слоте кадра (§9.6 «Материал»).
 *
 * Состояния: загрузка N% с отменой, «Обрабатываем фото…», готов («@Image 1»
 * и роль), ошибка с причиной и «Повторить», «Создаётся…», серый «не
 * учитывается и не оплачивается» с «Учитывать снова», красный «удалено».
 * Клик, правый клик или долгое нажатие открывают действия: «Кто или что
 * это?», «Сделать первым кадром» / «Сделать референсом», ‹ ›, «Не учитывать»,
 * «Убрать». На телефоне действия — нижняя шторка, на компьютере — меню у чипа.
 */
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  FiAlertTriangle,
  FiChevronLeft,
  FiChevronRight,
  FiCornerDownLeft,
  FiEyeOff,
  FiImage,
  FiLoader,
  FiRefreshCw,
  FiRotateCcw,
  FiTrash2,
  FiX,
} from "react-icons/fi";
import { errorText } from "@/lib/vstudio/errors";
import type { FrameSlot, InputSlot, RefLabel, TrayItem } from "@/lib/vstudio/types";
import BottomSheet from "../BottomSheet";
import { useIsMobile } from "../settings/SettingsSheet";
import { MAX_ROLE_CHARS } from "../store";
import { VS_FOCUS, VS_INPUT, VS_MENU_ITEM, vx } from "../ui/skin";
import { ct } from "./composerText";
import AnchoredPopover from "./Popover";

export type ChipActions = {
  onRetry?: () => void;
  onCancel?: () => void;
  onRemove: () => void;
  onInclude: (included: boolean) => void;
  onRole?: (role: string) => void;
  onSlot?: (slot: InputSlot) => void;
  onMove?: (delta: -1 | 1) => void;
  onInsert?: () => void;
};

export type AssetChipProps = ChipActions & {
  item: TrayItem;
  /** Метка по uid (null — ещё грузится, uid нет). */
  label: RefLabel | null;
  /** Ошибка компилятора показывает на этот материал. */
  flagged?: boolean;
  canMoveLeft?: boolean;
  canMoveRight?: boolean;
  /** Какие слоты кадров умеет модель (для «Сделать первым кадром»). */
  frameSlots?: readonly FrameSlot[];
  /** Упавшую загрузку можно повторить (файл ещё в памяти). */
  retryable?: boolean;
  /** Компактный вид (слот кадра на телефоне). */
  compact?: boolean;
  /** Перетаскивание (только референсы на компьютере). */
  dragProps?: React.HTMLAttributes<HTMLDivElement> & { draggable?: boolean };
};

const LONG_PRESS_MS = 480;

/** «Влево» / «Вправо» в меню чипа: две половинки одной строки. */
const MOVE_BTN = `flex min-h-11 flex-1 cursor-pointer items-center justify-center gap-1.5 rounded-xl text-sm text-foreground/85 transition-colors hover:bg-white/[0.08] hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 md:min-h-9 ${VS_FOCUS}`;
/** Маленькая кнопка внутри чипа: отменить загрузку, повторить, учитывать снова. */
const CHIP_BTN = `grid size-8 shrink-0 cursor-pointer place-items-center rounded-full transition-colors ${VS_FOCUS}`;

function frameName(t: ReturnType<typeof useTranslation>["t"], slot: InputSlot): string {
  return slot === "first_frame" ? ct(t, "tray.firstFrame") : slot === "last_frame" ? ct(t, "tray.lastFrame") : "";
}

/** Верхняя строка чипа: «@Image 1», «@Первый кадр», «@Image —». */
function chipTitle(t: ReturnType<typeof useTranslation>["t"], item: TrayItem, label: RefLabel | null): string {
  if (label) return label.text.replace(/ · .*$/, "");
  if (item.slot !== "reference") return `@${frameName(t, item.slot)}`;
  // Номер появится, когда у фото будет uid (после загрузки).
  return "@Image …";
}

/** Нижняя строка: состояние или роль. */
function chipSub(t: ReturnType<typeof useTranslation>["t"], item: TrayItem): { text: string; tone: "muted" | "fail" | "wait" } {
  switch (item.status) {
    case "uploading":
      return { text: ct(t, "tray.uploading", { p: Math.max(0, Math.min(99, Math.round(item.progress || 0))) }), tone: "muted" };
    case "processing":
      return { text: ct(t, "tray.processing"), tone: "muted" };
    case "pending":
      return { text: ct(t, "tray.pending"), tone: "wait" };
    case "failed":
      return {
        text: item.errorCode ? errorText(t, { code: item.errorCode, message: "", context: "image" }) : ct(t, "tray.failed"),
        tone: "fail",
      };
    case "deleted":
      return { text: ct(t, "tray.deleted"), tone: "fail" };
    default:
      if (!item.included) return { text: ct(t, "tray.excluded"), tone: "muted" };
      return { text: item.role || "", tone: "muted" };
  }
}

function Thumb({ item, compact }: { item: TrayItem; compact?: boolean }) {
  const [broken, setBroken] = useState<string | null>(null);
  const src = item.preview && broken !== item.preview ? item.preview : null;
  // С 768 px чип — 40 px, в рост кнопок лотка: строка материалов не прыгает, когда появляется первое фото.
  const size = compact ? "size-9 md:size-[1.875rem]" : "size-10 md:size-[1.875rem]";
  const grey = !item.included || item.status === "deleted";
  const busy = item.status === "processing" || item.status === "pending";
  const pct = Math.max(0, Math.min(100, item.progress || 0));
  return (
    <span className={`relative ${size} shrink-0 overflow-hidden rounded-lg border border-white/10 bg-surface-3`}>
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt=""
          draggable={false}
          onError={() => setBroken(src)}
          className={`size-full object-cover ${grey ? "opacity-50 grayscale" : ""} ${item.status === "uploading" ? "opacity-60" : ""}`}
        />
      ) : (
        <span className="grid size-full place-items-center text-muted-2">
          <FiImage aria-hidden />
        </span>
      )}
      {item.status === "uploading" && (
        <svg className="absolute inset-0 m-auto size-7 -rotate-90" viewBox="0 0 36 36" aria-hidden>
          <circle cx="18" cy="18" r="15" fill="none" stroke="currentColor" strokeWidth="4" className="text-black/30" />
          <circle
            cx="18"
            cy="18"
            r="15"
            fill="none"
            stroke="currentColor"
            strokeWidth="4"
            strokeLinecap="round"
            strokeDasharray={`${(pct / 100) * 94.25} 94.25`}
            className="text-accent transition-[stroke-dasharray] duration-200"
          />
        </svg>
      )}
      {busy && (
        <span className="absolute inset-0 grid place-items-center bg-black/35 text-white">
          <FiLoader className="animate-spin motion-reduce:animate-none" aria-hidden />
        </span>
      )}
      {(item.status === "failed" || item.status === "deleted") && (
        <span className="absolute inset-0 grid place-items-center bg-status-fail/35 text-white">
          <FiAlertTriangle aria-hidden />
        </span>
      )}
    </span>
  );
}

function MenuItem({
  icon,
  children,
  onClick,
  tone,
  disabled,
}: {
  icon: ReactNode;
  children: ReactNode;
  onClick: () => void;
  tone?: "fail";
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      disabled={disabled}
      onClick={onClick}
      className={vx(VS_MENU_ITEM, "disabled:cursor-not-allowed disabled:opacity-50", tone === "fail" && "!text-status-fail")}
    >
      <span className={`shrink-0 [&>svg]:size-4 ${tone === "fail" ? "" : "text-muted"}`}>{icon}</span>
      <span className="min-w-0 flex-1">{children}</span>
    </button>
  );
}

function RoleField({ value, onSave }: { value: string; onSave: (role: string) => void }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const [draft, setDraft] = useState(value);
  const commit = () => {
    const next = draft.trim().slice(0, MAX_ROLE_CHARS);
    if (next !== value) onSave(next);
  };
  return (
    <label className="flex flex-col gap-1.5 px-3 pb-2 pt-1">
      <span className="text-xs font-medium text-muted">{ct(t, "tray.role")}</span>
      <span className="flex items-center gap-1.5">
        <input
          value={draft}
          maxLength={MAX_ROLE_CHARS}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              commit();
            }
          }}
          placeholder={ct(t, "tray.rolePlaceholder")}
          enterKeyHint="done"
          // На телефоне шрифт 16 px: мельче — и iOS приближает страницу при фокусе.
          className={`${VS_INPUT} min-w-0 flex-1 max-md:!text-base`}
        />
      </span>
    </label>
  );
}

function ChipMenuBody(props: AssetChipProps & { close: () => void; header?: boolean }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { item, label, close, header = true } = props;
  const run = (fn?: () => void) => () => {
    close();
    fn?.();
  };
  const isRef = item.slot === "reference";
  const loading = item.status === "uploading" || item.status === "processing";
  const failedUpload = item.status === "failed" && !item.assetUid;
  const canUse = Boolean(item.assetUid) && item.status !== "deleted";
  const sub = chipSub(t, item);
  return (
    <div className={`flex flex-col p-1.5 ${header ? "w-[min(19rem,calc(100vw-2rem))]" : "w-full"}`}>
      <div className="px-3 pb-1.5 pt-1.5">
        {header && <div className="text-sm font-semibold text-foreground">{label?.aria || chipTitle(t, item, label)}</div>}
        {(item.status === "failed" || item.status === "deleted" || !item.included) && (
          <div className={`mt-0.5 text-xs ${sub.tone === "fail" ? "text-status-fail" : "text-muted"}`}>{sub.text}</div>
        )}
      </div>
      {isRef && props.onRole && canUse && <RoleField value={item.role} onSave={props.onRole} />}
      {canUse && item.included && props.onInsert && (
        <MenuItem icon={<FiCornerDownLeft />} onClick={run(props.onInsert)}>
          {ct(t, "tray.insert")}
        </MenuItem>
      )}
      {failedUpload && props.retryable && props.onRetry && (
        <MenuItem icon={<FiRefreshCw />} onClick={run(props.onRetry)}>
          {ct(t, "tray.retry")}
        </MenuItem>
      )}
      {props.onSlot && canUse && isRef && (props.frameSlots || []).includes("first_frame") && (
        <MenuItem icon={<FiImage />} onClick={run(() => props.onSlot?.("first_frame"))}>
          {ct(t, "tray.makeFirstFrame")}
        </MenuItem>
      )}
      {props.onSlot && canUse && isRef && (props.frameSlots || []).includes("last_frame") && (
        <MenuItem icon={<FiImage />} onClick={run(() => props.onSlot?.("last_frame"))}>
          {ct(t, "tray.makeLastFrame")}
        </MenuItem>
      )}
      {props.onSlot && canUse && !isRef && (
        <MenuItem icon={<FiImage />} onClick={run(() => props.onSlot?.("reference"))}>
          {ct(t, "tray.makeReference")}
        </MenuItem>
      )}
      {isRef && props.onMove && (props.canMoveLeft || props.canMoveRight) && (
        // ‹ › — перестановка на телефоне (там нет перетаскивания мышью); номера @Image N пересчитаются.
        <div className="flex items-center gap-1 px-1">
          <button
            type="button"
            role="menuitem"
            disabled={!props.canMoveLeft}
            onClick={run(() => props.onMove?.(-1))}
            aria-label={ct(t, "tray.moveLeft")}
            className={MOVE_BTN}
          >
            <FiChevronLeft className="size-4 text-muted" aria-hidden />
            {ct(t, "tray.left")}
          </button>
          <button
            type="button"
            role="menuitem"
            disabled={!props.canMoveRight}
            onClick={run(() => props.onMove?.(1))}
            aria-label={ct(t, "tray.moveRight")}
            className={MOVE_BTN}
          >
            {ct(t, "tray.right")}
            <FiChevronRight className="size-4 text-muted" aria-hidden />
          </button>
        </div>
      )}
      {canUse && (
        <MenuItem
          icon={item.included ? <FiEyeOff /> : <FiRotateCcw />}
          onClick={run(() => props.onInclude(!item.included))}
        >
          {item.included ? ct(t, "tray.exclude") : ct(t, "tray.include")}
        </MenuItem>
      )}
      {loading && props.onCancel ? (
        <MenuItem icon={<FiX />} onClick={run(props.onCancel)} tone="fail">
          {ct(t, "tray.cancel")}
        </MenuItem>
      ) : (
        <MenuItem icon={<FiTrash2 />} onClick={run(props.onRemove)} tone="fail">
          {ct(t, "tray.remove")}
        </MenuItem>
      )}
    </div>
  );
}

function AssetChip(props: AssetChipProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { item, label, flagged, compact } = props;
  const mobile = useIsMobile();
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLDivElement | null>(null);
  const press = useRef<{ timer: ReturnType<typeof setTimeout> | null; x: number; y: number; fired: boolean }>({
    timer: null,
    x: 0,
    y: 0,
    fired: false,
  });
  const actionsRef = useRef(props);
  useLayoutEffect(() => {
    actionsRef.current = props;
  });
  useEffect(
    () => () => {
      if (press.current.timer) clearTimeout(press.current.timer);
    },
    [],
  );

  const title = chipTitle(t, item, label);
  const sub = chipSub(t, item);
  const loading = item.status === "uploading" || item.status === "processing";
  const failedUpload = item.status === "failed" && !item.assetUid;
  const excluded = !item.included && item.status !== "deleted";
  const aria = [label?.aria || title, sub.text].filter(Boolean).join(" · ");

  // Основа — vs-card; состояние меняет только кромку и подложку (через !: у vs-card они свои).
  const tone =
    item.status === "failed" || item.status === "deleted" || flagged
      ? "!border-status-fail/60 !bg-status-fail/10"
      : excluded
        ? "!border-dashed !border-white/15 hover:!border-white/30"
        : item.status === "ready" && item.included
          ? "!border-accent/40 !bg-accent/[0.07] hover:!border-accent/70"
          : "hover:!border-white/25";

  const close = () => setOpen(false);
  const cancelPress = () => {
    if (press.current.timer) clearTimeout(press.current.timer);
    press.current.timer = null;
  };

  return (
    <div className="relative shrink-0" {...(props.dragProps || {})}>
      <div
        ref={anchor}
        role="button"
        tabIndex={0}
        aria-label={aria}
        aria-haspopup="menu"
        aria-expanded={open}
        title={aria}
        data-vs-chip={item.lid}
        onClick={() => {
          if (press.current.fired) {
            press.current.fired = false;
            return;
          }
          setOpen((o) => !o);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " " || e.key === "ContextMenu") {
            e.preventDefault();
            setOpen(true);
          } else if ((e.key === "Delete" || e.key === "Backspace") && !loading) {
            e.preventDefault();
            actionsRef.current.onRemove();
          }
        }}
        onContextMenu={(e) => {
          e.preventDefault();
          setOpen(true);
        }}
        onPointerDown={(e) => {
          if (e.pointerType !== "touch") return;
          press.current = { timer: null, x: e.clientX, y: e.clientY, fired: false };
          press.current.timer = setTimeout(() => {
            press.current.fired = true;
            setOpen(true);
          }, LONG_PRESS_MS);
        }}
        onPointerMove={(e) => {
          if (!press.current.timer) return;
          if (Math.abs(e.clientX - press.current.x) > 8 || Math.abs(e.clientY - press.current.y) > 8) cancelPress();
        }}
        onPointerUp={cancelPress}
        onPointerCancel={cancelPress}
        className={vx(
          "vs-card group flex min-h-11 cursor-pointer select-none items-center gap-2 rounded-xl py-1 pl-1 pr-2 text-left md:min-h-10",
          VS_FOCUS,
          tone,
          flagged && "!ring-1 ring-status-fail/60",
          compact ? "max-w-[10rem]" : "max-w-[13rem]",
        )}
      >
        <Thumb item={item} compact={compact} />
        <span className="flex min-w-0 flex-col leading-tight">
          <span
            className={`truncate text-xs font-semibold ${
              excluded ? "text-muted-2" : item.status === "deleted" ? "text-status-fail line-through" : "text-foreground"
            }`}
          >
            {title}
          </span>
          {sub.text && (
            <span
              className={`text-[11px] ${
                // «Не учитывается и не оплачивается» и причина ошибки важны целиком — в две строки.
                excluded || item.status === "failed" ? "line-clamp-2 leading-tight" : "truncate"
              } ${sub.tone === "fail" ? "text-status-fail" : sub.tone === "wait" ? "text-status-wait" : "text-muted"}`}
            >
              {sub.text}
            </span>
          )}
        </span>
        {loading && props.onCancel && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              props.onCancel?.();
            }}
            className={`${CHIP_BTN} text-muted hover:bg-white/[0.1] hover:text-foreground`}
            aria-label={ct(t, "tray.cancel")}
            title={ct(t, "tray.cancel")}
          >
            <FiX aria-hidden />
          </button>
        )}
        {failedUpload && props.retryable && props.onRetry && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              props.onRetry?.();
            }}
            className={`${CHIP_BTN} text-status-fail hover:bg-status-fail/15`}
            aria-label={ct(t, "tray.retry")}
            title={ct(t, "tray.retry")}
          >
            <FiRefreshCw aria-hidden />
          </button>
        )}
        {excluded && item.assetUid && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              props.onInclude(true);
            }}
            className={`${CHIP_BTN} text-muted hover:bg-white/[0.1] hover:text-foreground`}
            aria-label={ct(t, "tray.include")}
            title={ct(t, "tray.include")}
          >
            <FiRotateCcw aria-hidden />
          </button>
        )}
      </div>

      {mobile ? (
        <BottomSheet open={open} onClose={close} title={label?.aria || title} size="auto" zIndex={1045}>
          <ChipMenuBody {...props} close={close} header={false} />
        </BottomSheet>
      ) : (
        <AnchoredPopover
          anchor={anchor}
          open={open}
          onClose={close}
          role="menu"
          ariaLabel={ct(t, "tray.menu")}
          autoFocus
          closeOnTabOut
        >
          <ChipMenuBody {...props} close={close} />
        </AnchoredPopover>
      )}
    </div>
  );
}

export default AssetChip;

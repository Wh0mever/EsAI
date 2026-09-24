"use client";

import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { FiChevronDown, FiEdit2, FiArchive, FiMenu, FiMoreHorizontal, FiSliders, FiZap, FiLogIn } from "react-icons/fi";
import { ConfirmationModal } from "@/components/dialog/Dialog";
import { rememberReturnPath } from "@/tools/authNext";
import { useVStudio } from "./context";
import { selectModel } from "./store";
import type { ModelJSON, ProjectJSON, ShotParams, VsKind } from "@/lib/vstudio/types";

/**
 * Верх студии.
 *
 * - StudioTopBar — телефон и планшет (<1024): ☰ (история и материалы
 *   шторкой), название проекта, баланс, чип параметров (§9.7).
 * - StudioHeader — компьютер (≥1024): над лентой название проекта с
 *   переименованием, вкладки «Видео | Картинка», меню «⋯» и кнопка панели
 *   параметров (§9.2).
 * - BalanceChip — баланс из useBalance и резерв «N кр ждут результата»; у
 *   гостя вместо него «Войти».
 */

const fmt = (n: number) => Math.max(0, Math.round(n)).toLocaleString("ru-RU");

type T = (key: string, options?: Record<string, unknown>) => string;

/** «Seedance 2.0 · 9:16 · 10 с» — сводка параметров для чипа. */
export function paramsSummary(t: T, model: ModelJSON | null, kind: VsKind, params: ShotParams): string {
  if (!model) return t("top.settings", { defaultValue: "Параметры" });
  const parts = [model.name];
  const ar = params.aspect_ratio;
  if (ar) parts.push(ar === "auto" ? t("settings.aspectAuto", { defaultValue: "Авто" }) : ar);
  if (kind === "video" && typeof params.duration === "number") {
    parts.push(t("settings.seconds", { defaultValue: "{{n}} с", n: params.duration }));
  }
  return parts.join(" · ");
}

/* ------------------------------------------------------------------ */
/* Баланс                                                              */
/* ------------------------------------------------------------------ */

export function BalanceChip({ variant = "chip" }: { variant?: "chip" | "rail" | "compact" }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { authed, balance, reserved, actions, routeProject } = useVStudio();

  if (authed === false) {
    const back = routeProject ? `/video-studio/${routeProject}` : "/video-studio";
    return (
      <a
        href={`/auth/signin?next=${encodeURIComponent(back)}`}
        onClick={() => rememberReturnPath(back)}
        className={
          variant === "compact"
            ? "grid h-11 w-11 place-items-center rounded-xl bg-accent text-on-accent hover:bg-accent-strong"
            : "inline-flex min-h-9 items-center justify-center gap-1.5 rounded-full bg-accent px-4 text-sm font-semibold text-on-accent transition-colors hover:bg-accent-strong"
        }
        title={t("top.signin", { defaultValue: "Войти" })}
        aria-label={variant === "compact" ? t("top.signin", { defaultValue: "Войти" }) : undefined}
      >
        {variant === "compact" ? <FiLogIn className="text-lg" /> : t("top.signin", { defaultValue: "Войти" })}
      </a>
    );
  }

  const amount = balance == null ? "…" : t("top.balance", { defaultValue: "{{n}} кр", n: fmt(balance) });
  const waiting = reserved > 0 ? t("top.reserved", { defaultValue: "{{n}} кр ждут результата", n: fmt(reserved) }) : "";
  const topupLabel = t("top.topup", { defaultValue: "Пополнить" });

  if (variant === "compact") {
    // Колонка 64 px: только значок и короткое число, подробности — в подсказке.
    const short = balance == null ? "…" : balance >= 10000 ? `${Math.floor(balance / 1000)}k` : fmt(balance);
    return (
      <button
        type="button"
        onClick={actions.openTopUp}
        className="flex w-11 flex-col items-center gap-0.5 rounded-xl py-1.5 text-muted transition-colors hover:bg-surface-2 hover:text-foreground cursor-pointer"
        title={[amount, waiting, topupLabel].filter(Boolean).join(" · ")}
        aria-label={[amount, waiting, topupLabel].filter(Boolean).join(". ")}
      >
        <FiZap className="text-accent" />
        <span className="text-[11px] font-medium leading-none">{short}</span>
      </button>
    );
  }

  return (
    <div className={variant === "rail" ? "flex flex-col gap-1" : "flex flex-col items-end gap-0.5"}>
      <button
        type="button"
        onClick={actions.openTopUp}
        className={
          "inline-flex min-h-9 items-center gap-1.5 rounded-full border border-border bg-surface-2 px-3 text-sm transition-colors hover:border-accent/60 cursor-pointer" +
          (variant === "rail" ? " w-full justify-between" : "")
        }
        title={topupLabel}
      >
        <span className="inline-flex items-center gap-1.5">
          <FiZap className="text-accent" />
          <span className="font-medium">{amount}</span>
        </span>
        {variant === "rail" && <span className="text-xs text-accent">{topupLabel}</span>}
      </button>
      {waiting && (
        <span className="text-xs leading-tight text-muted" aria-live="polite">
          {waiting}
        </span>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Название проекта с переименованием                                   */
/* ------------------------------------------------------------------ */

export const MAX_TITLE_CHARS = 140;

export function ProjectTitle({
  className = "",
  editing: editingProp,
  onEditingChange,
}: {
  className?: string;
  /** Управляемый режим: переименование можно начать и из меню «⋯». */
  editing?: boolean;
  onEditingChange?: (editing: boolean) => void;
}) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { state, actions } = useVStudio();
  const project = state.project;
  const [editingLocal, setEditingLocal] = useState(false);
  const editing = Boolean(project) && (editingProp ?? editingLocal);
  const setEditing = (v: boolean) => (onEditingChange ? onEditingChange(v) : setEditingLocal(v));
  const inputRef = useRef<HTMLInputElement>(null);
  // Enter закрывает поле, и следом может прийти blur — сохраняем один раз.
  const finished = useRef(false);

  useEffect(() => {
    if (!editing) return;
    finished.current = false;
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [editing]);

  const untitled = t("nav.untitled", { defaultValue: "Без названия" });
  const title = project ? project.title.trim() || untitled : t("nav.new", { defaultValue: "Новая генерация" });

  if (!project || !editing) {
    return (
      <button
        type="button"
        disabled={!project}
        onClick={() => setEditing(true)}
        className={
          "group inline-flex min-w-0 items-center gap-1.5 rounded-lg px-1.5 py-1 text-left font-semibold enabled:hover:bg-surface-2 enabled:cursor-pointer disabled:cursor-default " +
          className
        }
        title={project ? t("nav.rename", { defaultValue: "Переименовать" }) : undefined}
      >
        <span className="truncate">{title}</span>
        {project && (
          <FiEdit2 className="shrink-0 text-xs text-muted opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" />
        )}
      </button>
    );
  }

  const finish = (save: boolean) => {
    if (finished.current) return;
    finished.current = true;
    const next = (inputRef.current?.value || "").trim().slice(0, MAX_TITLE_CHARS);
    setEditing(false);
    if (save && next !== project.title) void actions.renameProject(project.uid, next);
  };

  return (
    <input
      ref={inputRef}
      defaultValue={project.title}
      maxLength={MAX_TITLE_CHARS}
      onBlur={() => finish(true)}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          finish(true);
        } else if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          finish(false);
        }
      }}
      placeholder={untitled}
      aria-label={t("nav.rename", { defaultValue: "Переименовать" })}
      className={
        "w-full min-w-0 rounded-lg border border-border-strong bg-surface-2 px-2 py-1 text-base font-semibold text-foreground outline-none focus:border-accent " +
        className
      }
    />
  );
}

/* ------------------------------------------------------------------ */
/* Подтверждение «В архив»                                               */
/* ------------------------------------------------------------------ */

/**
 * Архив убирает проект из истории, а вернуть его из интерфейса в Фазе 1
 * нельзя — поэтому и в левой колонке, и в меню над лентой сначала вопрос.
 */
export function ArchiveProjectDialog({ project, onClose }: { project: ProjectJSON | null; onClose: () => void }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { actions } = useVStudio();
  const [busy, setBusy] = useState(false);
  return (
    <ConfirmationModal
      isOpen={Boolean(project)}
      title={t("nav.archiveConfirm", { defaultValue: "Убрать проект в архив?" })}
      description={t("nav.archiveHint", {
        defaultValue: "Он пропадёт из истории. Готовые видео и картинки останутся в «Моих материалах».",
      })}
      confirmText={t("nav.archive", { defaultValue: "В архив" })}
      cancelText={t("nav.cancel", { defaultValue: "Отмена" })}
      confirmDisabled={busy}
      onCancel={() => {
        if (!busy) onClose();
      }}
      onConfirm={async () => {
        if (!project || busy) return;
        setBusy(true);
        await actions.archiveProject(project.uid);
        setBusy(false);
        onClose();
      }}
    />
  );
}

/* ------------------------------------------------------------------ */
/* Меню проекта «⋯»                                                      */
/* ------------------------------------------------------------------ */

export function ProjectMenu({ onRename }: { onRename?: () => void }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { state } = useVStudio();
  const [open, setOpen] = useState(false);
  const [archiveFor, setArchiveFor] = useState<ProjectJSON | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const project = state.project;

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // Окно подтверждения — всегда на одном месте дерева: после архива проект
  // пропадает из стора, а окно должно спокойно закрыться, не пересоздаваясь.
  return (
    <>
      {project && (
        <div ref={box} className="relative">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-haspopup="menu"
            aria-expanded={open}
            aria-label={t("nav.menu", { defaultValue: "Меню проекта" })}
            className="grid h-10 w-10 place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-foreground cursor-pointer"
          >
            <FiMoreHorizontal className="text-lg" />
          </button>
          {open && (
            <div role="menu" className="absolute right-0 top-full z-30 mt-1 w-52 overflow-hidden rounded-xl border border-border bg-surface py-1 shadow-xl">
              {onRename && (
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setOpen(false);
                    onRename();
                  }}
                  className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm hover:bg-surface-2 cursor-pointer"
                >
                  <FiEdit2 className="text-muted" />
                  {t("nav.rename", { defaultValue: "Переименовать" })}
                </button>
              )}
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setOpen(false);
                  setArchiveFor(project);
                }}
                className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm hover:bg-surface-2 cursor-pointer"
              >
                <FiArchive className="text-muted" />
                {t("nav.archive", { defaultValue: "В архив" })}
              </button>
            </div>
          )}
        </div>
      )}
      <ArchiveProjectDialog project={archiveFor} onClose={() => setArchiveFor(null)} />
    </>
  );
}

/* ------------------------------------------------------------------ */
/* Чип параметров                                                       */
/* ------------------------------------------------------------------ */

export function ParamsChip({ onClick, iconOnly = false }: { onClick: () => void; iconOnly?: boolean }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { state } = useVStudio();
  const model = selectModel(state);
  const label = paramsSummary(t, model, state.composer.kind, state.composer.params);
  const settingsLabel = t("mobile.params", { defaultValue: "Параметры" });
  if (iconOnly) {
    return (
      <button
        type="button"
        onClick={onClick}
        aria-label={`${settingsLabel}: ${label}`}
        title={label}
        className="grid h-11 w-11 shrink-0 place-items-center rounded-xl text-muted transition-colors hover:bg-surface-2 hover:text-foreground cursor-pointer"
      >
        <FiSliders className="text-lg" />
      </button>
    );
  }
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`${settingsLabel}: ${label}`}
      className="inline-flex min-h-10 max-w-[16rem] items-center gap-1.5 rounded-full border border-border bg-surface-2 px-3 text-sm transition-colors hover:border-border-strong cursor-pointer"
    >
      <FiSliders className="shrink-0 text-muted" />
      <span className="truncate">{label}</span>
      <FiChevronDown className="shrink-0 text-muted" />
    </button>
  );
}

/* ------------------------------------------------------------------ */
/* Телефон и планшет                                                    */
/* ------------------------------------------------------------------ */

export default function StudioTopBar({ onMenu, onSettings }: { onMenu: () => void; onSettings: () => void }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { breakpoint } = useVStudio();
  return (
    <header className="flex h-[calc(3.5rem_+_env(safe-area-inset-top,0px))] shrink-0 items-center gap-1 border-b border-border px-2 pt-[env(safe-area-inset-top,0px)] sm:px-3">
      <button
        type="button"
        onClick={onMenu}
        className="grid h-11 w-11 shrink-0 place-items-center rounded-xl text-muted transition-colors hover:bg-surface-2 hover:text-foreground cursor-pointer"
        aria-label={t("mobile.history", { defaultValue: "История" })}
      >
        <FiMenu className="text-xl" />
      </button>
      <div className="min-w-0 flex-1">
        <ProjectTitle className="max-w-full text-[15px]" />
      </div>
      <BalanceChip />
      {/* На телефоне чип с текстом живёт в строке композера (§9.7), здесь — только значок. */}
      <ParamsChip onClick={onSettings} iconOnly={breakpoint === "mobile"} />
    </header>
  );
}

/* ------------------------------------------------------------------ */
/* Компьютер: строка над лентой                                         */
/* ------------------------------------------------------------------ */

export function StudioHeader({
  kindTabs,
  settingsOpen,
  onToggleSettings,
}: {
  /** Вкладки «Видео | Картинка» (KindTabs трека параметров). */
  kindTabs?: ReactNode;
  settingsOpen: boolean;
  onToggleSettings: () => void;
}) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const [editing, setEditing] = useState(false);
  const settingsLabel = t("settings.title", { defaultValue: "Параметры запуска" });
  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border px-4">
      <div className="min-w-0 flex-1">
        <ProjectTitle editing={editing} onEditingChange={setEditing} className="max-w-full text-base" />
      </div>
      {kindTabs}
      <ProjectMenu onRename={() => setEditing(true)} />
      <button
        type="button"
        onClick={onToggleSettings}
        aria-pressed={settingsOpen}
        aria-label={settingsLabel}
        title={settingsLabel}
        className={
          "grid h-10 w-10 place-items-center rounded-lg transition-colors cursor-pointer " +
          (settingsOpen ? "bg-surface-2 text-foreground" : "text-muted hover:bg-surface-2 hover:text-foreground")
        }
      >
        <FiSliders className="text-lg" />
      </button>
    </header>
  );
}

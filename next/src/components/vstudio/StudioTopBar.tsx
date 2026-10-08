"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiChevronDown, FiEdit2, FiArchive, FiMenu, FiMoreHorizontal, FiSliders, FiZap, FiLogIn } from "react-icons/fi";
import { ConfirmationModal } from "@/components/dialog/Dialog";
import { rememberReturnPath } from "@/tools/authNext";
import { useVStudio } from "./context";
import { signInReturnPath } from "./deepLink";
import { selectModel } from "./store";
import { VS_FOCUS, VS_ICON_BTN, VS_MENU, VS_MENU_ITEM, VS_PILL, VS_PILL_ON, vx } from "./ui/skin";
import type { ModelJSON, ProjectJSON, ShotParams, VsKind } from "@/lib/vstudio/types";

/**
 * Верх студии.
 *
 * - StudioTopBar — телефон и планшет (<1024): ☰ (история и материалы
 *   шторкой), название проекта, баланс, чип параметров (§9.7).
 * - StudioHeader — компьютер (≥1024): над лентой название проекта с
 *   переименованием, баланс, меню «⋯» и кнопка панели параметров (§9.2). Вид
 *   («Видео | Картинка») выбирают в панели запроса и в параметрах.
 * - BalanceChip — баланс из useBalance и резерв «N кр ждут результата»; у
 *   гостя вместо него «Войти».
 *
 * Обе строки прозрачные и без своей нижней линии: линию по прокрутке ленты
 * рисует оболочка (VStudioShell), иначе на первом экране верх отрезал бы сцену.
 */

const fmt = (n: number) => Math.max(0, Math.round(n)).toLocaleString("ru-RU");

type T = (key: string, options?: Record<string, unknown>) => string;

/** Зона нажатия 44 px у контрола, который выглядит ниже: невидимое поле сверху и снизу. */
const TALL_HIT = "relative before:absolute before:inset-x-0 before:-inset-y-1";

/** Выпадающее меню вырастает из своего угла, а не возникает разом. */
export const MENU_POP =
  "origin-top-right scale-100 opacity-100 transition-[opacity,scale] duration-150 starting:scale-95 starting:opacity-0 motion-reduce:transition-none";

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
  const { state, authed, balance, reserved, actions, routeProject } = useVStudio();

  if (authed === false) {
    // С первого экрана — обратно к тем же виду и модели, а не к модели по умолчанию.
    const back = signInReturnPath("/video-studio", routeProject, state.composer);
    const signin = t("top.signin", { defaultValue: "Войти" });
    // Вход — не главное действие экрана (оно одно, «Создать»), поэтому кнопка тихая, с золотой кромкой.
    return (
      <a
        href={`/auth/signin?next=${encodeURIComponent(back)}`}
        onClick={() => rememberReturnPath(back)}
        className={
          variant === "compact"
            ? vx(VS_ICON_BTN, VS_PILL_ON)
            : vx(VS_PILL, VS_PILL_ON, "max-md:h-11 md:!h-10", variant === "rail" && "w-full justify-center")
        }
        title={signin}
        aria-label={variant === "compact" ? signin : undefined}
      >
        <FiLogIn className={variant === "compact" ? "text-lg" : "shrink-0"} aria-hidden="true" />
        {variant !== "compact" && signin}
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
        className={vx(
          "flex w-11 cursor-pointer flex-col items-center gap-1 rounded-2xl border border-vs-ink/10 bg-vs-ink/[0.05] py-2 text-muted transition-colors hover:border-vs-accent/45 hover:bg-vs-ink/[0.09] hover:text-foreground",
          VS_FOCUS,
        )}
        title={[amount, waiting, topupLabel].filter(Boolean).join(" · ")}
        aria-label={[amount, waiting, topupLabel].filter(Boolean).join(". ")}
      >
        <FiZap className="text-vs-accent" aria-hidden="true" />
        <span className="text-[11px] font-medium leading-none tabular-nums">{short}</span>
      </button>
    );
  }

  const rail = variant === "rail";
  return (
    // В строке над лентой резерв стоит слева от чипа, на телефоне — под ним:
    // вторая строка в 56 px помещается только при чипе пониже (TALL_HIT добирает зону нажатия).
    <div className={rail ? "flex flex-col gap-1" : "flex shrink-0 flex-col items-end md:flex-row-reverse md:items-center md:gap-2.5"}>
      <button
        type="button"
        onClick={actions.openTopUp}
        className={vx(
          VS_PILL,
          "hover:!border-vs-accent/45",
          rail ? "!h-11 w-full justify-between md:!h-10" : vx(TALL_HIT, "!h-9 md:!h-10"),
        )}
        title={topupLabel}
      >
        <span className="inline-flex items-center gap-1.5">
          <FiZap className="shrink-0 text-vs-accent" aria-hidden="true" />
          <span className="font-semibold tabular-nums text-foreground">{amount}</span>
        </span>
        {rail && <span className="text-xs font-semibold text-vs-accent">{topupLabel}</span>}
      </button>
      {waiting && (
        <span
          className={vx("whitespace-nowrap text-[11px] leading-[14px] text-muted", rail ? "px-3.5" : "md:text-xs")}
          aria-live="polite"
        >
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

  if (!project) {
    // Проекта нет (первый экран, «не найден», гость по ссылке): переименовывать
    // нечего — на этом месте стоит имя раздела.
    return (
      <span className={vx("block min-w-0 truncate px-1.5 font-semibold text-foreground", className)}>
        {t("meta.title", { defaultValue: "Видеостудия" })}
      </span>
    );
  }

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => setEditing(true)}
        className={vx(
          "group inline-flex min-h-11 min-w-0 cursor-pointer items-center gap-1.5 rounded-xl px-1.5 text-left font-semibold text-foreground transition-colors hover:bg-vs-ink/[0.06] md:min-h-9",
          VS_FOCUS,
          className,
        )}
        title={t("nav.rename", { defaultValue: "Переименовать" })}
      >
        <span className="truncate">{project.title.trim() || untitled}</span>
        <FiEdit2
          className="shrink-0 text-xs text-muted opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
          aria-hidden="true"
        />
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
      // На телефоне шрифт поля не меньше 16 px: иначе iOS приближает страницу при фокусе.
      className={vx(
        "w-full min-w-0 rounded-xl border border-vs-ink/10 bg-vs-ink/[0.04] px-2.5 py-1.5 font-semibold text-foreground outline-none transition-colors placeholder:text-muted-2 focus:border-vs-accent/60 max-sm:!text-base",
        className,
      )}
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
        defaultValue: "Он пропадёт из истории вместе со своими видео. Созданные картинки останутся в «Моих материалах».",
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
        <div ref={box} className="relative shrink-0">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-haspopup="menu"
            aria-expanded={open}
            aria-label={t("nav.menu", { defaultValue: "Меню проекта" })}
            className={vx(VS_ICON_BTN, open && "!border-vs-ink/22 !bg-vs-ink/[0.1] !text-foreground")}
          >
            <FiMoreHorizontal className="text-lg" aria-hidden="true" />
          </button>
          {open && (
            <div role="menu" className={vx(VS_MENU, MENU_POP, "absolute right-0 top-full z-30 mt-1.5 w-52")}>
              {onRename && (
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setOpen(false);
                    onRename();
                  }}
                  className={VS_MENU_ITEM}
                >
                  <FiEdit2 className="shrink-0 text-muted" aria-hidden="true" />
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
                className={VS_MENU_ITEM}
              >
                <FiArchive className="shrink-0 text-muted" aria-hidden="true" />
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
      <button type="button" onClick={onClick} aria-label={`${settingsLabel}: ${label}`} title={label} className={VS_ICON_BTN}>
        <FiSliders className="text-lg" aria-hidden="true" />
      </button>
    );
  }
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`${settingsLabel}: ${label}`}
      className={vx(VS_PILL, "min-w-0 max-w-[16rem] !shrink md:!h-10")}
    >
      <FiSliders className="shrink-0 text-muted" aria-hidden="true" />
      <span className="truncate">{label}</span>
      <FiChevronDown className="shrink-0 text-muted" aria-hidden="true" />
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
    <header className="flex h-[calc(3.5rem_+_env(safe-area-inset-top,0px))] shrink-0 items-center gap-1.5 px-2 pt-[env(safe-area-inset-top,0px)] sm:px-3">
      <button type="button" onClick={onMenu} className={VS_ICON_BTN} aria-label={t("mobile.history", { defaultValue: "История" })}>
        <FiMenu className="text-lg" aria-hidden="true" />
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
  settingsOpen,
  onToggleSettings,
}: {
  settingsOpen: boolean;
  onToggleSettings: () => void;
}) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { state } = useVStudio();
  const [editing, setEditing] = useState(false);
  const settingsLabel = t("settings.title", { defaultValue: "Параметры запуска" });
  return (
    <header className="flex h-14 shrink-0 items-center gap-2 px-4">
      <div className="min-w-0 flex-1">
        {/* Без проекта слева только имя раздела — тише, чем название проекта. */}
        <ProjectTitle
          editing={editing}
          onEditingChange={setEditing}
          className={state.project ? "max-w-full text-base" : "text-sm"}
        />
      </div>
      <BalanceChip />
      <ProjectMenu onRename={() => setEditing(true)} />
      <button
        type="button"
        onClick={onToggleSettings}
        aria-pressed={settingsOpen}
        aria-label={settingsLabel}
        title={settingsLabel}
        className={vx(VS_ICON_BTN, settingsOpen && VS_PILL_ON)}
      >
        <FiSliders className="text-lg" aria-hidden="true" />
      </button>
    </header>
  );
}

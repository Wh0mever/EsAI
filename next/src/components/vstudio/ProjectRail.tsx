"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent } from "react";
import { useTranslation } from "react-i18next";
import {
  FiArchive,
  FiClock,
  FiEdit2,
  FiFilm,
  FiImage,
  FiMoreHorizontal,
  FiPlus,
  FiSearch,
  FiUser,
  FiX,
} from "react-icons/fi";
import Link from "next/link";
import EsaiLogo from "@/components/brand/EsaiLogo";
import { rememberReturnPath } from "@/tools/authNext";
import { useVStudio } from "./context";
import { groupProjects } from "./store";
import { ArchiveProjectDialog, BalanceChip, MAX_TITLE_CHARS } from "./StudioTopBar";
import type { ProjectJSON, Uid } from "@/lib/vstudio/types";

/**
 * Левая колонка студии (§9.2): «+ Новая генерация», поиск, история по
 * группам «Сегодня / Вчера / Раньше» с переименованием и архивом, «Мои
 * материалы», баланс и профиль.
 *
 * variant="full" — колонка 240 px на ≥1280 и она же в выдвижной шторке;
 * variant="compact" — колонка значков 64 px на 1024–1279: клик по истории
 * или поиску разворачивает полную колонку шторкой.
 */

const SEARCH_DEBOUNCE_MS = 300;

/** Обычный клик по ссылке — переход внутри студии; Ctrl/⌘/Shift/средняя кнопка — как у браузера. */
function plainClick(e: MouseEvent) {
  return e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;
}

export type ProjectRailProps = {
  variant?: "full" | "compact";
  /** Колонка в шторке: закрыть её после перехода. */
  onNavigate?: () => void;
  /** Компактная колонка: развернуть полную (focus — сразу в поиск). */
  onExpand?: (focus?: "search") => void;
  /** Поставить фокус в поиск при появлении (развернули кнопкой поиска). */
  autoFocusSearch?: boolean;
};

export default function ProjectRail({ variant = "full", onNavigate, onExpand, autoFocusSearch }: ProjectRailProps) {
  if (variant === "compact") return <CompactRail onExpand={onExpand} />;
  return <FullRail onNavigate={onNavigate} autoFocusSearch={autoFocusSearch} />;
}

/* ------------------------------------------------------------------ */
/* Полная колонка                                                       */
/* ------------------------------------------------------------------ */

function FullRail({ onNavigate, autoFocusSearch }: { onNavigate?: () => void; autoFocusSearch?: boolean }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { state, actions, authed, routeProject } = useVStudio();
  const { projects } = state;
  const [query, setQuery] = useState(projects.q);
  const searchRef = useRef<HTMLInputElement>(null);
  const [archiveFor, setArchiveFor] = useState<ProjectJSON | null>(null);

  // Поиск с паузой: сервер ищет по названию, на каждую букву не стреляем.
  useEffect(() => {
    if (query === projects.q) return;
    const id = window.setTimeout(() => actions.searchProjects(query), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(id);
  }, [query, projects.q, actions]);

  useEffect(() => {
    if (autoFocusSearch) searchRef.current?.focus();
  }, [autoFocusSearch]);

  const groups = useMemo(() => groupProjects(projects.items), [projects.items]);
  const current = state.project?.uid ?? routeProject;
  const loadingList = authed !== false && !projects.loaded && (projects.loading || authed === null);

  const open = (uid: Uid | null) => {
    actions.openProject(uid);
    onNavigate?.();
  };

  const section = (key: "today" | "yesterday" | "earlier", title: string) => {
    const items = groups[key];
    if (!items.length) return null;
    return (
      <section key={key} aria-label={title} className="mt-3 first:mt-0">
        <h3 className="px-2 pb-1 text-xs font-medium uppercase tracking-wide text-muted-2">{title}</h3>
        <ul className="flex flex-col gap-0.5">
          {items.map((p) => (
            <ProjectItem
              key={p.uid}
              project={p}
              active={p.uid === current}
              onOpen={(e) => {
                if (!plainClick(e)) return;
                e.preventDefault();
                open(p.uid);
              }}
              onArchive={() => setArchiveFor(p)}
            />
          ))}
        </ul>
      </section>
    );
  };

  const back = routeProject ? `/video-studio/${routeProject}` : "/video-studio";

  return (
    <nav aria-label={t("nav.history", { defaultValue: "История" })} className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-2 px-3 pb-2 pt-3">
        <Link href="/" className="flex items-center" aria-label="EsAI">
          <EsaiLogo className="h-6 w-auto" />
        </Link>
        <span className="truncate text-sm font-semibold text-muted">
          {t("meta.title", { defaultValue: "Видеостудия" })}
        </span>
      </div>

      <div className="shrink-0 px-3">
        <button
          type="button"
          onClick={() => {
            actions.newSession();
            onNavigate?.();
          }}
          className={
            "flex min-h-11 w-full items-center justify-center gap-2 rounded-xl border px-3 text-sm font-semibold transition-colors cursor-pointer " +
            (current ? "border-border bg-surface-2 hover:border-border-strong" : "border-accent/50 bg-accent-soft")
          }
        >
          <FiPlus />
          {t("nav.new", { defaultValue: "Новая генерация" })}
        </button>

        {authed !== false && (
          <label className="relative mt-2 block">
            <span className="sr-only">{t("nav.search", { defaultValue: "Поиск" })}</span>
            <FiSearch className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" aria-hidden="true" />
            <input
              ref={searchRef}
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape" && query) {
                  e.stopPropagation();
                  setQuery("");
                }
              }}
              placeholder={t("nav.search", { defaultValue: "Поиск" })}
              maxLength={100}
              enterKeyHint="search"
              // Свой крестик «Очистить» ниже; встроенный крестик Chrome/Safari у type=search прячем, иначе их два.
              className="h-10 w-full rounded-xl border border-border bg-surface-2 pl-9 pr-8 text-base text-foreground outline-none placeholder:text-muted-2 focus:border-border-strong sm:text-sm [&::-webkit-search-cancel-button]:appearance-none"
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery("")}
                className="absolute right-1 top-1/2 grid h-8 w-8 -translate-y-1/2 place-items-center rounded-lg text-muted hover:text-foreground cursor-pointer"
                aria-label={t("nav.clearSearch", { defaultValue: "Очистить поиск" })}
              >
                <FiX />
              </button>
            )}
          </label>
        )}
      </div>

      <div className="mt-3 min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 pb-3">
        {authed === false ? (
          <div className="mx-1 rounded-xl border border-dashed border-border p-3 text-sm text-muted">
            <p>{t("nav.guest", { defaultValue: "Войдите — и все ваши генерации сохранятся здесь." })}</p>
            <a
              href={`/auth/signin?next=${encodeURIComponent(back)}`}
              onClick={() => rememberReturnPath(back)}
              className="mt-2 inline-flex min-h-9 items-center rounded-full bg-accent px-4 text-sm font-semibold text-on-accent hover:bg-accent-strong"
            >
              {t("top.signin", { defaultValue: "Войти" })}
            </a>
          </div>
        ) : loadingList ? (
          <RailSkeleton />
        ) : projects.items.length === 0 ? (
          <p className="px-2 py-3 text-sm text-muted">
            {projects.q
              ? t("nav.nothingFound", { defaultValue: "Ничего не нашлось" })
              : t("nav.empty", { defaultValue: "Здесь появятся ваши генерации" })}
          </p>
        ) : (
          <>
            {section("today", t("nav.today", { defaultValue: "Сегодня" }))}
            {section("yesterday", t("nav.yesterday", { defaultValue: "Вчера" }))}
            {section("earlier", t("nav.earlier", { defaultValue: "Раньше" }))}
            {projects.next && (
              <button
                type="button"
                disabled={projects.loading}
                onClick={() => void actions.loadMoreProjects()}
                className="mt-2 w-full rounded-lg px-2 py-2 text-sm text-muted hover:bg-surface-2 hover:text-foreground disabled:opacity-60 cursor-pointer"
              >
                {projects.loading
                  ? t("page.loading", { defaultValue: "Загружаем…" })
                  : t("nav.more", { defaultValue: "Показать ещё" })}
              </button>
            )}
          </>
        )}
      </div>

      <div className="shrink-0 space-y-2 border-t border-border px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3">
        <button
          type="button"
          onClick={() => {
            if (!actions.requireAuth()) return;
            actions.openLibrary();
            onNavigate?.();
          }}
          className="flex min-h-11 w-full items-center gap-2 rounded-xl px-3 text-sm transition-colors hover:bg-surface-2 cursor-pointer"
        >
          <FiImage className="text-muted" />
          {t("nav.library", { defaultValue: "Мои материалы" })}
        </button>
        <div className="flex items-center gap-2">
          <div className="min-w-0 flex-1">
            <BalanceChip variant="rail" />
          </div>
          {authed && (
            <Link
              href="/profile"
              className="grid h-10 w-10 shrink-0 place-items-center rounded-xl text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
              aria-label={t("nav.profile", { defaultValue: "Профиль" })}
              title={t("nav.profile", { defaultValue: "Профиль" })}
            >
              <FiUser />
            </Link>
          )}
        </div>
      </div>

      <ArchiveProjectDialog project={archiveFor} onClose={() => setArchiveFor(null)} />
    </nav>
  );
}

/* ------------------------------------------------------------------ */
/* Строка истории                                                       */
/* ------------------------------------------------------------------ */

function ProjectItem({
  project,
  active,
  onOpen,
  onArchive,
}: {
  project: ProjectJSON;
  active: boolean;
  onOpen: (e: MouseEvent<HTMLAnchorElement>) => void;
  onArchive: () => void;
}) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { actions } = useVStudio();
  const [menu, setMenu] = useState(false);
  const [editing, setEditing] = useState(false);
  const box = useRef<HTMLLIElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const finished = useRef(false);
  const untitled = t("nav.untitled", { defaultValue: "Без названия" });
  const title = project.title.trim() || untitled;
  const running = project.open_takes > 0;

  useEffect(() => {
    if (!menu) return;
    const onDown = (e: PointerEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setMenu(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenu(false);
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [menu]);

  useEffect(() => {
    if (!editing) return;
    finished.current = false;
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [editing]);

  const finish = (save: boolean) => {
    if (finished.current) return;
    finished.current = true;
    const next = (inputRef.current?.value || "").trim().slice(0, MAX_TITLE_CHARS);
    setEditing(false);
    if (save && next !== project.title) void actions.renameProject(project.uid, next);
  };

  if (editing) {
    return (
      <li className="px-1 py-0.5">
        <input
          ref={inputRef}
          defaultValue={project.title}
          maxLength={MAX_TITLE_CHARS}
          placeholder={untitled}
          aria-label={t("nav.rename", { defaultValue: "Переименовать" })}
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
          className="h-10 w-full rounded-lg border border-border-strong bg-surface-2 px-2 text-base text-foreground outline-none focus:border-accent sm:text-sm"
        />
      </li>
    );
  }

  return (
    <li ref={box} className="group relative">
      <a
        href={`/video-studio/${project.uid}`}
        onClick={onOpen}
        aria-current={active ? "page" : undefined}
        className={
          "flex min-h-11 items-center gap-2 rounded-lg py-1.5 pl-2 pr-10 text-sm transition-colors " +
          (active ? "bg-surface-3 text-foreground" : "text-muted hover:bg-surface-2 hover:text-foreground")
        }
      >
        {project.thumb_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={project.thumb_url} alt="" loading="lazy" className="h-7 w-7 shrink-0 rounded-md object-cover" />
        ) : (
          <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-surface-2 text-muted-2" aria-hidden="true">
            <FiFilm className="text-xs" />
          </span>
        )}
        <span className="min-w-0 flex-1 truncate">{title}</span>
        {running && (
          <span
            className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-accent"
            role="img"
            aria-label={t("nav.running", { defaultValue: "Идёт генерация" })}
            title={t("nav.running", { defaultValue: "Идёт генерация" })}
          />
        )}
      </a>
      <button
        type="button"
        onClick={() => setMenu((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={menu}
        aria-label={t("nav.menu", { defaultValue: "Меню проекта" })}
        className={
          "absolute right-1 top-1/2 grid h-9 w-9 -translate-y-1/2 place-items-center rounded-lg text-muted transition-opacity hover:bg-surface-3 hover:text-foreground focus-visible:opacity-100 cursor-pointer " +
          (menu || active ? "opacity-100" : "opacity-100 pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100")
        }
      >
        <FiMoreHorizontal />
      </button>
      {menu && (
        <div role="menu" className="absolute right-1 top-full z-30 mt-1 w-48 overflow-hidden rounded-xl border border-border bg-surface py-1 shadow-xl">
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setMenu(false);
              setEditing(true);
            }}
            className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm hover:bg-surface-2 cursor-pointer"
          >
            <FiEdit2 className="text-muted" />
            {t("nav.rename", { defaultValue: "Переименовать" })}
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setMenu(false);
              onArchive();
            }}
            className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-sm hover:bg-surface-2 cursor-pointer"
          >
            <FiArchive className="text-muted" />
            {t("nav.archive", { defaultValue: "В архив" })}
          </button>
        </div>
      )}
    </li>
  );
}

function RailSkeleton() {
  return (
    <div className="flex flex-col gap-2 px-2 py-1" aria-hidden="true">
      <div className="h-3 w-16 animate-pulse rounded bg-surface-2" />
      {[72, 56, 88, 64, 48].map((w, i) => (
        <div key={i} className="flex items-center gap-2 py-1.5">
          <div className="h-7 w-7 animate-pulse rounded-md bg-surface-2" />
          <div className="h-3 animate-pulse rounded bg-surface-2" style={{ width: `${w}%` }} />
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Компактная колонка 64 px (1024–1279)                                  */
/* ------------------------------------------------------------------ */

function CompactRail({ onExpand }: { onExpand?: (focus?: "search") => void }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { state, actions, authed, routeProject } = useVStudio();
  const current = state.project?.uid ?? routeProject;
  const btn =
    "grid h-11 w-11 place-items-center rounded-xl text-muted transition-colors hover:bg-surface-2 hover:text-foreground cursor-pointer";
  const running = state.projects.items.some((p) => p.open_takes > 0);

  return (
    <nav aria-label={t("nav.history", { defaultValue: "История" })} className="flex h-full flex-col items-center gap-1 py-3">
      <Link href="/" className="mb-2 grid h-11 w-11 place-items-center" aria-label="EsAI">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/esai-mark.svg" alt="" className="h-7 w-7" />
      </Link>
      <button
        type="button"
        onClick={() => actions.newSession()}
        className={
          "grid h-11 w-11 place-items-center rounded-xl transition-colors cursor-pointer " +
          (current ? "bg-surface-2 text-foreground hover:bg-surface-3" : "bg-accent-soft text-foreground")
        }
        aria-label={t("nav.new", { defaultValue: "Новая генерация" })}
        title={t("nav.new", { defaultValue: "Новая генерация" })}
      >
        <FiPlus className="text-lg" />
      </button>
      {authed !== false && (
        <button
          type="button"
          onClick={() => onExpand?.("search")}
          className={btn}
          aria-label={t("nav.search", { defaultValue: "Поиск" })}
          title={t("nav.search", { defaultValue: "Поиск" })}
        >
          <FiSearch className="text-lg" />
        </button>
      )}
      <button
        type="button"
        onClick={() => onExpand?.()}
        className={btn + " relative"}
        aria-label={t("nav.history", { defaultValue: "История" })}
        title={t("nav.history", { defaultValue: "История" })}
      >
        <FiClock className="text-lg" />
        {running && <span className="absolute right-2 top-2 h-2 w-2 animate-pulse rounded-full bg-accent" aria-hidden="true" />}
      </button>
      <button
        type="button"
        onClick={() => {
          if (actions.requireAuth()) actions.openLibrary();
        }}
        className={btn}
        aria-label={t("nav.library", { defaultValue: "Мои материалы" })}
        title={t("nav.library", { defaultValue: "Мои материалы" })}
      >
        <FiImage className="text-lg" />
      </button>
      <div className="flex-1" />
      <BalanceChip variant="compact" />
      {authed && (
        <Link
          href="/profile"
          className={btn}
          aria-label={t("nav.profile", { defaultValue: "Профиль" })}
          title={t("nav.profile", { defaultValue: "Профиль" })}
        >
          <FiUser className="text-lg" />
        </Link>
      )}
    </nav>
  );
}

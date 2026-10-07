"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent } from "react";
import { useTranslation } from "react-i18next";
import {
  FiArchive,
  FiArrowUpRight,
  FiClock,
  FiEdit2,
  FiFilm,
  FiImage,
  FiLogIn,
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
import { signInReturnPath } from "./deepLink";
import { groupProjects } from "./store";
import { ArchiveProjectDialog, BalanceChip, MAX_TITLE_CHARS, MENU_POP } from "./StudioTopBar";
import {
  VS_BTN_GHOST,
  VS_BTN_GOLD,
  VS_BTN_LINK,
  VS_FOCUS,
  VS_ICON_BTN,
  VS_INPUT,
  VS_LABEL,
  VS_MENU,
  VS_MENU_ITEM,
  VS_PILL,
  VS_PILL_ON,
  vx,
} from "./ui/skin";
import type { ProjectJSON, Uid } from "@/lib/vstudio/types";

/**
 * Левая колонка студии (§9.2): «+ Новая генерация», поиск, история по
 * группам «Сегодня / Вчера / Раньше» с переименованием и архивом, ссылка в
 * мультстудию, «Мои материалы», баланс и профиль.
 *
 * variant="full" — колонка 248 px на ≥1280 и она же в выдвижной шторке;
 * variant="compact" — колонка значков 64 px на 1024–1279: клик по истории
 * или поиску разворачивает полную колонку шторкой.
 */

const SEARCH_DEBOUNCE_MS = 300;
const CARTOON_STUDIO = "/studio";

/** Золотая точка «вы здесь» и «идёт генерация». */
const DOT = "size-1.5 shrink-0 rounded-full bg-accent shadow-[0_0_8px_rgba(245,197,24,0.8)]";

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
  // «Проект не найден» по кривой ссылке — не первый экран, хотя проекта и нет.
  const atHome = !current && state.ui.page !== "not_found";
  const loadingList = authed !== false && !projects.loaded && (projects.loading || authed === null);

  const open = (uid: Uid | null) => {
    actions.openProject(uid);
    onNavigate?.();
  };

  const section = (key: "today" | "yesterday" | "earlier", title: string) => {
    const items = groups[key];
    if (!items.length) return null;
    return (
      <section key={key} aria-label={title} className="mt-4 first:mt-0">
        <h3 className={vx(VS_LABEL, "px-2.5 pb-1.5")}>{title}</h3>
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

  // Гость входит с первого экрана — вернётся к тем же виду и модели.
  const back = signInReturnPath("/video-studio", routeProject, state.composer);

  return (
    <nav aria-label={t("nav.history", { defaultValue: "История" })} className="flex h-full min-h-0 flex-col">
      {/* Высота — как у строки над лентой: логотип и название проекта стоят на одной линии. */}
      <div className="flex h-14 shrink-0 items-center gap-2.5 px-4">
        <Link href="/" className={vx("flex items-center rounded-md", VS_FOCUS)} aria-label="EsAI">
          <EsaiLogo className="h-6 w-auto" />
        </Link>
        {/* На ≥1280 колонка стоит вплотную к строке над лентой, а там уже написано имя раздела или проекта. */}
        <span className="truncate text-[13px] font-medium text-muted xl:hidden">
          {t("meta.title", { defaultValue: "Видеостудия" })}
        </span>
      </div>

      <div className="shrink-0 px-3">
        {/* Открыт проект — золотая кнопка зовёт начать новый. На первом экране
            человек уже «в новой генерации»: кнопка тихая, с точкой «вы здесь». */}
        <button
          type="button"
          onClick={() => {
            actions.newSession();
            onNavigate?.();
          }}
          aria-current={atHome ? "page" : undefined}
          className={vx(atHome ? VS_BTN_GHOST : VS_BTN_GOLD, "w-full")}
        >
          {atHome ? <span className={DOT} aria-hidden="true" /> : <FiPlus aria-hidden="true" />}
          {t("nav.new", { defaultValue: "Новая генерация" })}
        </button>

        {authed !== false && (
          <label className="relative mt-2.5 block">
            <span className="sr-only">{t("nav.search", { defaultValue: "Поиск" })}</span>
            <FiSearch
              className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-2"
              aria-hidden="true"
            />
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
              // На телефоне шрифт 16 px: при меньшем iOS приближает страницу, когда поле получает фокус.
              className={vx(VS_INPUT, "pl-9 pr-10 max-sm:text-base [&::-webkit-search-cancel-button]:appearance-none")}
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery("")}
                className={vx(
                  "absolute right-1 top-1/2 grid size-9 -translate-y-1/2 cursor-pointer place-items-center rounded-full text-muted transition-colors hover:bg-white/[0.08] hover:text-foreground",
                  VS_FOCUS,
                )}
                aria-label={t("nav.clearSearch", { defaultValue: "Очистить поиск" })}
              >
                <FiX aria-hidden="true" />
              </button>
            )}
          </label>
        )}
      </div>

      <div className="mt-4 min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 pb-3">
        {authed === false ? (
          <div className="vs-card mx-1 rounded-2xl p-3.5">
            <p className="text-[13px] leading-snug text-muted">
              {t("nav.guest", { defaultValue: "Войдите — и все ваши генерации сохранятся здесь." })}
            </p>
            <a
              href={`/auth/signin?next=${encodeURIComponent(back)}`}
              onClick={() => rememberReturnPath(back)}
              className={vx(VS_PILL, VS_PILL_ON, "mt-3 max-md:h-11")}
            >
              <FiLogIn className="shrink-0" aria-hidden="true" />
              {t("top.signin", { defaultValue: "Войти" })}
            </a>
          </div>
        ) : loadingList ? (
          <RailSkeleton />
        ) : projects.items.length === 0 ? (
          <p className="px-2.5 py-2 text-[13px] leading-snug text-muted-2">
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
                className={vx(VS_BTN_LINK, "mt-2 w-full justify-center disabled:cursor-default disabled:opacity-60")}
              >
                {projects.loading
                  ? t("page.loading", { defaultValue: "Загружаем…" })
                  : t("nav.more", { defaultValue: "Показать ещё" })}
              </button>
            )}
          </>
        )}
      </div>

      <div className="shrink-0 border-t border-border px-2 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2">
        {/* Соседний раздел сайта: полный переход. Загружать его заранее незачем — код мультстудии тяжёлый. */}
        <Link href={CARTOON_STUDIO} prefetch={false} className={VS_MENU_ITEM}>
          <FiFilm className="shrink-0 text-muted" aria-hidden="true" />
          <span className="min-w-0 flex-1 truncate">{t("nav.cartoon", { defaultValue: "Мультстудия" })}</span>
          <FiArrowUpRight className="shrink-0 text-muted-2" aria-hidden="true" />
        </Link>
        <button
          type="button"
          onClick={() => {
            if (!actions.requireAuth()) return;
            actions.openLibrary();
            onNavigate?.();
          }}
          className={VS_MENU_ITEM}
        >
          <FiImage className="shrink-0 text-muted" aria-hidden="true" />
          {t("nav.library", { defaultValue: "Мои материалы" })}
        </button>
        {/* Гостю «Войти» уже предложено выше, в блоке истории, и в верхней строке — третья кнопка здесь лишняя. */}
        {authed !== false && (
          <div className="mt-2 flex items-start gap-2 px-1">
            <div className="min-w-0 flex-1">
              <BalanceChip variant="rail" />
            </div>
            {authed && (
              <Link
                href="/profile"
                className={VS_ICON_BTN}
                aria-label={t("nav.profile", { defaultValue: "Профиль" })}
                title={t("nav.profile", { defaultValue: "Профиль" })}
              >
                <FiUser aria-hidden="true" />
              </Link>
            )}
          </div>
        )}
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
      <li className="px-0.5 py-0.5">
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
          className={vx(VS_INPUT, "max-sm:text-base")}
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
        className={vx(
          "relative flex min-h-11 items-center gap-2.5 rounded-xl py-1.5 pl-2.5 pr-10 text-sm transition-colors",
          VS_FOCUS,
          active ? "bg-white/[0.06] text-foreground" : "text-foreground/70 hover:bg-white/[0.04] hover:text-foreground",
        )}
      >
        {active && <span className="absolute inset-y-2.5 left-0 w-0.5 rounded-full bg-accent" aria-hidden="true" />}
        {project.thumb_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={project.thumb_url}
            alt=""
            loading="lazy"
            decoding="async"
            className="h-[25px] w-11 shrink-0 rounded-md bg-black object-cover ring-1 ring-white/10"
          />
        ) : (
          <span
            className="grid h-[25px] w-11 shrink-0 place-items-center rounded-md bg-white/[0.05] text-muted-2 ring-1 ring-white/10"
            aria-hidden="true"
          >
            <FiFilm className="text-xs" />
          </span>
        )}
        <span className="min-w-0 flex-1 truncate">{title}</span>
        {running && (
          <span
            className={vx(DOT, "motion-safe:animate-pulse")}
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
        className={vx(
          "absolute right-1 top-1/2 grid size-9 -translate-y-1/2 cursor-pointer place-items-center rounded-full text-muted transition-[opacity,background-color,color] hover:bg-white/[0.1] hover:text-foreground focus-visible:opacity-100",
          VS_FOCUS,
          menu || active ? "opacity-100" : "opacity-100 pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100",
        )}
      >
        <FiMoreHorizontal aria-hidden="true" />
      </button>
      {menu && (
        <div role="menu" className={vx(VS_MENU, MENU_POP, "absolute right-1 top-full z-30 mt-1 w-48")}>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setMenu(false);
              setEditing(true);
            }}
            className={VS_MENU_ITEM}
          >
            <FiEdit2 className="shrink-0 text-muted" aria-hidden="true" />
            {t("nav.rename", { defaultValue: "Переименовать" })}
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setMenu(false);
              onArchive();
            }}
            className={VS_MENU_ITEM}
          >
            <FiArchive className="shrink-0 text-muted" aria-hidden="true" />
            {t("nav.archive", { defaultValue: "В архив" })}
          </button>
        </div>
      )}
    </li>
  );
}

/** Заглушка истории: те же строки — кадр 44×25 и название. Без движения: список грузится доли секунды. */
function RailSkeleton() {
  return (
    <div className="flex flex-col gap-0.5 px-2.5" aria-hidden="true">
      <div className="mb-2 h-2.5 w-16 rounded-full bg-white/[0.06]" />
      {["w-3/4", "w-1/2", "w-5/6", "w-2/3", "w-2/5"].map((w) => (
        <div key={w} className="flex min-h-11 items-center gap-2.5">
          <div className="h-[25px] w-11 shrink-0 rounded-md bg-white/[0.06]" />
          <div className={vx("h-2.5 rounded-full bg-white/[0.06]", w)} />
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
  const atHome = !(state.project?.uid ?? routeProject) && state.ui.page !== "not_found";
  const running = state.projects.items.some((p) => p.open_takes > 0);
  const newLabel = t("nav.new", { defaultValue: "Новая генерация" });
  const cartoonLabel = t("nav.cartoon", { defaultValue: "Мультстудия" });

  return (
    <nav aria-label={t("nav.history", { defaultValue: "История" })} className="flex h-full flex-col items-center gap-1.5 pb-3">
      <Link href="/" className={vx("grid h-14 w-11 shrink-0 place-items-center rounded-xl", VS_FOCUS)} aria-label="EsAI">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/esai-mark.svg" alt="" className="size-7 rounded-lg ring-1 ring-white/10" />
      </Link>
      {/* Те же два состояния, что у кнопки в полной колонке: золотая — при открытом проекте, тихая — на первом экране. */}
      <button
        type="button"
        onClick={() => actions.newSession()}
        aria-current={atHome ? "page" : undefined}
        className={vx(VS_ICON_BTN, atHome ? VS_PILL_ON : "vs-gold !border-transparent")}
        aria-label={newLabel}
        title={newLabel}
      >
        <FiPlus className="text-lg" aria-hidden="true" />
      </button>
      {authed !== false && (
        <button
          type="button"
          onClick={() => onExpand?.("search")}
          className={VS_ICON_BTN}
          aria-label={t("nav.search", { defaultValue: "Поиск" })}
          title={t("nav.search", { defaultValue: "Поиск" })}
        >
          <FiSearch className="text-lg" aria-hidden="true" />
        </button>
      )}
      <button
        type="button"
        onClick={() => onExpand?.()}
        className={vx(VS_ICON_BTN, "relative")}
        aria-label={t("nav.history", { defaultValue: "История" })}
        title={t("nav.history", { defaultValue: "История" })}
      >
        <FiClock className="text-lg" aria-hidden="true" />
        {running && <span className={vx(DOT, "absolute right-2 top-2 motion-safe:animate-pulse")} aria-hidden="true" />}
      </button>
      <Link href={CARTOON_STUDIO} prefetch={false} className={VS_ICON_BTN} aria-label={cartoonLabel} title={cartoonLabel}>
        <FiFilm className="text-lg" aria-hidden="true" />
      </Link>
      <button
        type="button"
        onClick={() => {
          if (actions.requireAuth()) actions.openLibrary();
        }}
        className={VS_ICON_BTN}
        aria-label={t("nav.library", { defaultValue: "Мои материалы" })}
        title={t("nav.library", { defaultValue: "Мои материалы" })}
      >
        <FiImage className="text-lg" aria-hidden="true" />
      </button>
      <div className="flex-1" />
      <BalanceChip variant="compact" />
      {authed && (
        <Link
          href="/profile"
          className={VS_ICON_BTN}
          aria-label={t("nav.profile", { defaultValue: "Профиль" })}
          title={t("nav.profile", { defaultValue: "Профиль" })}
        >
          <FiUser className="text-lg" aria-hidden="true" />
        </Link>
      )}
    </nav>
  );
}

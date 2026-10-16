"use client";

import { useEffect, useRef, useState } from "react";
import type { MouseEvent } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import { FiArrowUpRight, FiEdit2, FiFilm, FiLogIn, FiPlus, FiUser, FiUsers, FiVideo } from "react-icons/fi";
import EsaiLogo from "@/components/brand/EsaiLogo";
import ThemeToggle from "@/components/vstudio/ThemeToggle";
import {
  VS_BTN_GHOST,
  VS_BTN_GOLD,
  VS_FOCUS,
  VS_ICON_BTN,
  VS_INPUT,
  VS_LABEL,
  VS_MENU_ITEM,
  VS_PILL,
  VS_PILL_ON,
  vx,
} from "@/components/vstudio/ui/skin";
import { rememberReturnPath } from "@/tools/authNext";
import { BalancePill, MAX_TITLE_CHARS, signInHref } from "./CartoonTopBar";
import { VSTUDIO_NAV, WORKING, type Project } from "./cartoonTypes";
import { CS_DOT, CS_SKELETON } from "./ui/cartoonSkin";

/**
 * Левая колонка мультстудии — как история видеостудии (ProjectRail): «Новый
 * мультфильм», список своих мультфильмов, ссылка в видеостудию, «Мои герои»,
 * баланс, тема и профиль.
 *
 * variant="full" — колонка 248 px на ≥1280 и она же в шторке (☰);
 * variant="compact" — колонка значков 64 px на 1024–1279: кнопка списка
 * разворачивает полную колонку шторкой.
 *
 * Удаления нет: на сайте мультфильм не удаляют (только в боте), а новых
 * запросов эта колонка не добавляет. Переименовать можно открытый мультфильм.
 */

export type MoviesRailProps = {
  /** full — колонка 248 px и шторка; compact — колонка 64 px. */
  variant: "full" | "compact";
  loading: boolean;
  authed: boolean;
  /** Свои мультфильмы (пустые черновики — только открытый). */
  movies: Project[];
  /** Открытый мультфильм; null — новый, ещё не заведённый. */
  currentId: number | null;
  balance: number | null;
  /** Баланс не пришёл — «—» вместо «…». */
  balanceFailed?: boolean;
  onOpen: (id: number) => void;
  onNew: () => void;
  /** Переименовать открытый мультфильм. */
  onRename: (value: string) => void;
  /** Прокрутить к героям («Мои герои»). */
  onHeroes: () => void;
  /** Узкая колонка: развернуть список в шторку. */
  onExpand?: () => void;
  /** После действия закрыть шторку. */
  onNavigate?: () => void;
  /** site — /studio; tg — Mini App: без ссылок с сайта (логотип, видеостудия, профиль). */
  host?: "site" | "tg";
};

/** Адрес студии: ссылки строк и возврат после входа ведут туда же, откуда пришли. */
function studioPath(host: MoviesRailProps["host"]): string {
  return host === "tg" ? "/tg/studio" : "/studio";
}

/** Обычный клик по строке — переключение внутри студии; Ctrl/⌘/Shift/средняя кнопка — как у браузера. */
function plainClick(e: MouseEvent) {
  return e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;
}

/** Кадр строки: первая снятая сцена, иначе герой мультфильма. */
function movieThumb(m: Project): string {
  const shot = [...m.scenes].sort((a, b) => a.order - b.order).find((s) => s.status === "ready");
  return shot?.keyframe || shot?.preset.poster || m.character?.image || "";
}

/** Идёт съёмка сцены или склейка. */
function movieRunning(m: Project): boolean {
  return m.status === "assembling" || m.scenes.some((s) => WORKING.includes(s.status));
}

export default function MoviesRail(props: MoviesRailProps) {
  if (props.variant === "compact") return <CompactRail {...props} />;
  return <FullRail {...props} />;
}

/* ------------------------------------------------------------------ */
/* Полная колонка                                                       */
/* ------------------------------------------------------------------ */

function FullRail({
  loading,
  authed,
  movies,
  currentId,
  balance,
  balanceFailed,
  onOpen,
  onNew,
  onRename,
  onHeroes,
  onNavigate,
  host,
}: MoviesRailProps) {
  const { t } = useTranslation("common");
  const site = host !== "tg";
  const home = studioPath(host);
  // Мультфильм не открыт — человек уже «в новом»: кнопка тихая, с точкой «вы здесь».
  const atNew = currentId === null;
  const listLabel = t("studio_ui.my_movies");
  const profileLabel = t("studio_ui.shell_profile", { defaultValue: "Профиль" });
  const logo = <EsaiLogo tone="auto" className="h-6 w-auto" />;

  return (
    <nav aria-label={listLabel} className="flex h-full min-h-0 flex-col">
      {/* Высота — как у строки над лентой: логотип и название мультфильма стоят на одной линии. */}
      <div className="flex h-14 shrink-0 items-center gap-2.5 px-4">
        {site ? (
          <Link href="/" className={vx("flex items-center rounded-md", VS_FOCUS)} aria-label="EsAI">
            {logo}
          </Link>
        ) : (
          logo
        )}
        {/* На ≥1280 колонка стоит вплотную к строке над лентой, а там уже написано имя раздела или мультфильма. */}
        <span className="truncate text-[13px] font-medium text-muted xl:hidden">
          {t("studio_ui.shell_name", { defaultValue: "Мультстудия" })}
        </span>
      </div>

      <div className="shrink-0 px-3">
        <button
          type="button"
          onClick={() => {
            onNew();
            onNavigate?.();
          }}
          aria-current={atNew ? "page" : undefined}
          className={vx(atNew ? VS_BTN_GHOST : VS_BTN_GOLD, "w-full")}
        >
          {atNew ? <span className={CS_DOT} aria-hidden="true" /> : <FiPlus aria-hidden="true" />}
          {t("studio_ui.rail_new", { defaultValue: "Новый мультфильм" })}
        </button>
      </div>

      <div className="mt-4 min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 pb-3">
        {loading ? (
          <RailSkeleton />
        ) : !authed ? (
          <div className="vs-card mx-1 rounded-2xl p-3.5">
            <p className="text-[13px] leading-snug text-muted">
              {t("studio_ui.rail_guest", { defaultValue: "Войдите — и ваши мультфильмы сохранятся здесь." })}
            </p>
            <a
              href={signInHref(home)}
              onClick={() => rememberReturnPath(home)}
              className={vx(VS_PILL, VS_PILL_ON, "mt-3 max-md:h-11")}
            >
              <FiLogIn className="shrink-0" aria-hidden="true" />
              {t("studio_ui.shell_signin", { defaultValue: "Войти" })}
            </a>
          </div>
        ) : movies.length === 0 ? (
          <p className="px-2.5 py-2 text-[13px] leading-snug text-muted-2">
            {t("studio_ui.rail_empty", { defaultValue: "Здесь появятся ваши мультфильмы" })}
          </p>
        ) : (
          <>
            <h3 className={vx(VS_LABEL, "px-2.5 pb-1.5")}>{listLabel}</h3>
            <ul className="flex flex-col gap-0.5">
              {movies.map((m) => (
                <MovieItem
                  key={m.id}
                  movie={m}
                  active={m.id === currentId}
                  href={`${home}?project=${m.id}`}
                  onOpen={() => {
                    onOpen(m.id);
                    onNavigate?.();
                  }}
                  onRename={onRename}
                />
              ))}
            </ul>
          </>
        )}
      </div>

      <div className="shrink-0 border-t border-border px-2 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2">
        {/* Соседний раздел сайта: полный переход, заранее не грузим — код видеостудии тяжёлый.
            Только там, где видеостудия открыта всем (как пункт меню сайта), и не в Telegram. */}
        {site && VSTUDIO_NAV && (
          <Link href="/video-studio" prefetch={false} className={VS_MENU_ITEM}>
            <FiVideo className="shrink-0 text-muted" aria-hidden="true" />
            <span className="min-w-0 flex-1 truncate">{t("studio_ui.rail_vstudio", { defaultValue: "Видеостудия" })}</span>
            <FiArrowUpRight className="shrink-0 text-muted-2" aria-hidden="true" />
          </Link>
        )}
        {/* Свои герои — первые в ленте героев: ведём туда (у видеостудии здесь «Мои материалы»). */}
        <button
          type="button"
          onClick={() => {
            onHeroes();
            onNavigate?.();
          }}
          className={VS_MENU_ITEM}
        >
          <FiUsers className="shrink-0 text-muted" aria-hidden="true" />
          {t("studio_ui.rail_heroes", { defaultValue: "Мои герои" })}
        </button>
        <div className="mt-2 flex flex-col gap-2 px-1">
          {/* Гостю «Войти» уже предложено выше, в блоке списка, и в верхней строке. */}
          {(loading || authed) && (
            <BalancePill variant="rail" loading={loading} authed={authed} balance={balance} failed={balanceFailed} back={home} />
          )}
          {/* Тема и профиль — своей строкой: чипу с «Пополнить» нужна почти вся ширина колонки.
              Тема шторку не закрывает: человек видит, как меняется страница. */}
          <div className="flex items-center justify-end gap-2">
            <ThemeToggle />
            {site &&
              (loading ? (
                <span className={vx(VS_ICON_BTN, "pointer-events-none")} aria-hidden="true" />
              ) : (
                authed && (
                  <Link href="/profile" className={VS_ICON_BTN} aria-label={profileLabel} title={profileLabel}>
                    <FiUser aria-hidden="true" />
                  </Link>
                )
              ))}
          </div>
        </div>
      </div>
    </nav>
  );
}

/* ------------------------------------------------------------------ */
/* Строка мультфильма                                                   */
/* ------------------------------------------------------------------ */

function MovieItem({
  movie,
  active,
  href,
  onOpen,
  onRename,
}: {
  movie: Project;
  active: boolean;
  href: string;
  onOpen: () => void;
  onRename: (value: string) => void;
}) {
  const { t } = useTranslation("common");
  const [editing, setEditing] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  // Enter закрывает поле, и следом может прийти blur — сохраняем один раз.
  const finished = useRef(false);
  const title = movie.title.trim() || t("studio_ui.movie_fallback", { id: movie.id });
  const shot = movie.scenes.filter((s) => s.status === "ready").length;
  const thumb = movieThumb(movie);
  const running = movieRunning(movie);
  const runningLabel = t("studio_ui.rail_running", { defaultValue: "Идёт съёмка" });
  const renameLabel = t("studio_ui.shell_rename", { defaultValue: "Переименовать" });

  useEffect(() => {
    if (!editing) return;
    finished.current = false;
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [editing]);

  // Переименовать можно только открытый мультфильм (так устроен хук): ушли с него — поле закрываем.
  if (editing && active) {
    const finish = (save: boolean) => {
      if (finished.current) return;
      finished.current = true;
      const next = (inputRef.current?.value || "").replace(/\s+/g, " ").trim().slice(0, MAX_TITLE_CHARS);
      setEditing(false);
      if (save && next && next !== movie.title) onRename(next);
    };
    return (
      <li className="px-0.5 py-0.5">
        <input
          ref={inputRef}
          defaultValue={movie.title}
          maxLength={MAX_TITLE_CHARS}
          placeholder={t("studio_ui.movie_title")}
          aria-label={renameLabel}
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
    <li className="relative">
      <a
        href={href}
        onClick={(e) => {
          if (!plainClick(e)) return;
          e.preventDefault();
          onOpen();
        }}
        aria-current={active ? "page" : undefined}
        className={vx(
          "relative flex min-h-11 items-center gap-2.5 rounded-xl py-1.5 pl-2.5 text-sm transition-colors",
          VS_FOCUS,
          // У открытого справа кнопка переименования — место под неё.
          active ? "pr-11" : "pr-3",
          // На светлой колонке та же доля чернил бледнее, чем белая на тёмной: выбранной строке и наведению — чуть больше.
          active
            ? "bg-vs-ink/[0.08] text-foreground dark:bg-vs-ink/[0.06]"
            : "text-foreground/70 hover:bg-vs-ink/[0.05] hover:text-foreground dark:hover:bg-vs-ink/[0.04]",
        )}
      >
        {active && <span className="absolute inset-y-2.5 left-0 w-0.5 rounded-full bg-vs-accent" aria-hidden="true" />}
        {thumb ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={thumb}
            alt=""
            loading="lazy"
            decoding="async"
            // Подложка видна, только пока кадр грузится: на светлой колонке чёрная плитка мигала бы у каждой строки.
            className="h-[25px] w-11 shrink-0 rounded-md bg-surface-3 object-cover ring-1 ring-vs-ink/10 dark:bg-black"
          />
        ) : (
          <span
            className="grid h-[25px] w-11 shrink-0 place-items-center rounded-md bg-vs-ink/[0.05] text-muted-2 ring-1 ring-vs-ink/10"
            aria-hidden="true"
          >
            <FiFilm className="text-xs" />
          </span>
        )}
        <span className="min-w-0 flex-1">
          <span className="block truncate">{title}</span>
          <span className="block truncate text-[11px] text-muted-2">
            {t("studio_ui.rail_meta", { defaultValue: "Сцен: {{n}} · снято: {{m}}", n: movie.scenes.length, m: shot })}
            {/* Мультфильм уже склеен — как раньше в списке студии: «· готов». */}
            {movie.result_video ? ` · ${t("studio_ui.movie_ready")}` : ""}
          </span>
        </span>
        {running && (
          <span
            className={vx(CS_DOT, "motion-safe:animate-pulse")}
            role="img"
            aria-label={runningLabel}
            title={runningLabel}
          />
        )}
      </a>
      {/* Видна всегда, без наведения: в Telegram и на телефоне наведения нет. Кружок 36 px, зона 44 px. */}
      {active && (
        <button
          type="button"
          onClick={() => setEditing(true)}
          aria-label={renameLabel}
          title={renameLabel}
          className={vx(
            "absolute right-1 top-1/2 grid size-9 -translate-y-1/2 cursor-pointer place-items-center rounded-full text-muted transition-colors hover:bg-vs-ink/[0.1] hover:text-foreground before:absolute before:-inset-1",
            VS_FOCUS,
          )}
        >
          <FiEdit2 aria-hidden="true" />
        </button>
      )}
    </li>
  );
}

/** Заглушка списка: те же строки — кадр 44×25 и название. Без движения: список грузится доли секунды. */
function RailSkeleton() {
  return (
    <div className="flex flex-col gap-0.5 px-2.5" aria-hidden="true">
      <div className={vx("mb-2 h-2.5 w-16 rounded-full", CS_SKELETON)} />
      {["w-3/4", "w-1/2", "w-5/6", "w-2/3", "w-2/5"].map((w) => (
        <div key={w} className="flex min-h-11 items-center gap-2.5">
          <div className={vx("h-[25px] w-11 shrink-0 rounded-md", CS_SKELETON)} />
          <div className={vx("h-2.5 rounded-full", CS_SKELETON, w)} />
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Компактная колонка 64 px (1024–1279)                                  */
/* ------------------------------------------------------------------ */

function CompactRail({
  loading,
  authed,
  movies,
  currentId,
  balance,
  balanceFailed,
  onNew,
  onHeroes,
  onExpand,
  host,
}: MoviesRailProps) {
  const { t } = useTranslation("common");
  const site = host !== "tg";
  const atNew = currentId === null;
  const running = movies.some(movieRunning);
  const newLabel = t("studio_ui.rail_new", { defaultValue: "Новый мультфильм" });
  const listLabel = t("studio_ui.my_movies");
  const runningLabel = t("studio_ui.rail_running", { defaultValue: "Идёт съёмка" });
  const vstudioLabel = t("studio_ui.rail_vstudio", { defaultValue: "Видеостудия" });
  const heroesLabel = t("studio_ui.rail_heroes", { defaultValue: "Мои герои" });
  const profileLabel = t("studio_ui.shell_profile", { defaultValue: "Профиль" });
  // eslint-disable-next-line @next/next/no-img-element
  const mark = <img src="/esai-mark.svg" alt="" className="size-7 rounded-lg ring-1 ring-vs-ink/10" />;

  return (
    <nav aria-label={listLabel} className="flex h-full flex-col items-center gap-1.5 pb-3">
      {site ? (
        <Link href="/" className={vx("grid h-14 w-11 shrink-0 place-items-center rounded-xl", VS_FOCUS)} aria-label="EsAI">
          {mark}
        </Link>
      ) : (
        <span className="grid h-14 w-11 shrink-0 place-items-center" aria-hidden="true">
          {mark}
        </span>
      )}
      {/* Те же два состояния, что у кнопки в полной колонке: золотая — при открытом мультфильме, тихая — у нового. */}
      <button
        type="button"
        onClick={onNew}
        aria-current={atNew ? "page" : undefined}
        className={vx(VS_ICON_BTN, atNew ? VS_PILL_ON : "vs-gold !border-transparent")}
        aria-label={newLabel}
        title={newLabel}
      >
        <FiPlus className="text-lg" aria-hidden="true" />
      </button>
      <button
        type="button"
        onClick={() => onExpand?.()}
        className={vx(VS_ICON_BTN, "relative")}
        aria-label={running ? `${listLabel}. ${runningLabel}` : listLabel}
        title={listLabel}
      >
        <FiFilm className="text-lg" aria-hidden="true" />
        {running && <span className={vx(CS_DOT, "absolute right-2 top-2 motion-safe:animate-pulse")} aria-hidden="true" />}
      </button>
      {site && VSTUDIO_NAV && (
        <Link href="/video-studio" prefetch={false} className={VS_ICON_BTN} aria-label={vstudioLabel} title={vstudioLabel}>
          <FiVideo className="text-lg" aria-hidden="true" />
        </Link>
      )}
      <button type="button" onClick={onHeroes} className={VS_ICON_BTN} aria-label={heroesLabel} title={heroesLabel}>
        <FiUsers className="text-lg" aria-hidden="true" />
      </button>
      <div className="flex-1" />
      <BalancePill
        variant="compact"
        loading={loading}
        authed={authed}
        balance={balance}
        failed={balanceFailed}
        back={studioPath(host)}
      />
      <ThemeToggle variant="compact" />
      {site &&
        (loading ? (
          <span className={vx(VS_ICON_BTN, "pointer-events-none")} aria-hidden="true" />
        ) : (
          authed && (
            <Link href="/profile" className={VS_ICON_BTN} aria-label={profileLabel} title={profileLabel}>
              <FiUser className="text-lg" aria-hidden="true" />
            </Link>
          )
        ))}
    </nav>
  );
}

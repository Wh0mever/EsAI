"use client";

import { useEffect, useRef, useState, type MouseEvent } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import {
  FiArrowUpRight,
  FiFilm,
  FiLogIn,
  FiMoreHorizontal,
  FiPlus,
  FiRefreshCw,
  FiScissors,
  FiTrash2,
  FiUser,
  FiVideo,
} from "react-icons/fi";
import EsaiLogo from "@/components/brand/EsaiLogo";
import ThemeToggle from "@/components/vstudio/ThemeToggle";
import {
  VS_BTN_GHOST,
  VS_BTN_GOLD,
  VS_BTN_LINK,
  VS_FOCUS,
  VS_ICON_BTN,
  VS_LABEL,
  VS_MENU,
  VS_MENU_ITEM,
  VS_PILL,
  VS_PILL_ON,
  vx,
} from "@/components/vstudio/ui/skin";
import { CS_DOT, CS_MENU_POP, CS_SKELETON } from "@/components/studio/ui/cartoonSkin";
import { rememberReturnPath } from "@/tools/authNext";
import { MERGE_PATH, VSTUDIO_NAV, isActive, shortDate } from "./mergeLogic";
import { MergeBalance, signInHref } from "./MergeTopBar";
import type { MergeProjectBrief, MergeStatus } from "./mergeTypes";
import type { ListState } from "./useMerge";

/**
 * Левая колонка склейки — как история видеостудии и «Мои мультфильмы»:
 * «Новая склейка», «Мои склейки» с состоянием и сроком хранения, ссылки в
 * видеостудию и мультстудию, баланс, тема, профиль.
 *
 * variant="full" — колонка 248 px на ≥1280 и она же в шторке (☰);
 * variant="compact" — колонка значков 64 px на 1024–1279.
 */

const STATUS_RU: Record<MergeStatus, string> = {
  draft: "Черновик",
  queued: "В очереди",
  rendering: "Склеивается",
  ready: "Готово",
  failed: "Не получилось",
  expired: "Срок хранения истёк",
};

/** Обычный клик по строке — переключение на месте; Ctrl/⌘/Shift/средняя кнопка — как у браузера. */
function plainClick(e: MouseEvent) {
  return e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;
}

export type MergeRailProps = {
  variant: "full" | "compact";
  loading: boolean;
  authed: boolean | null;
  list: ListState;
  openId: string | null;
  balance: number | null;
  balanceFailed: boolean;
  /** Куда вернуть гостя после входа. */
  back: string;
  onOpen: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onMore: () => void;
  /** Список не загрузился — «Попробовать снова». */
  onReload: () => void;
  onTopup: () => void;
  onExpand?: () => void;
  onNavigate?: () => void;
};

export default function MergeRail(props: MergeRailProps) {
  if (props.variant === "compact") return <CompactRail {...props} />;
  return <FullRail {...props} />;
}

function FullRail({
  loading,
  authed,
  list,
  openId,
  balance,
  balanceFailed,
  back,
  onOpen,
  onNew,
  onDelete,
  onMore,
  onReload,
  onTopup,
  onNavigate,
}: MergeRailProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const atNew = openId === null;
  const listLabel = t("merge.rail.title", { defaultValue: "Мои склейки" });
  const profileLabel = t("nav.profile", { defaultValue: "Профиль" });

  return (
    <nav aria-label={listLabel} className="flex h-full min-h-0 flex-col">
      <div className="flex h-14 shrink-0 items-center gap-2.5 px-4">
        <Link href="/" className={vx("flex items-center rounded-md", VS_FOCUS)} aria-label="EsAI">
          <EsaiLogo tone="auto" className="h-6 w-auto" />
        </Link>
        {/* На ≥1280 колонка стоит вплотную к строке над лентой, а там уже написано имя раздела или склейки. */}
        <span className="truncate text-[13px] font-medium text-muted xl:hidden">{t("merge.name", { defaultValue: "Склейка видео" })}</span>
      </div>

      <div className="shrink-0 px-3">
        {/* Открыта склейка — золотая кнопка зовёт начать новую; у новой — тихая, с точкой «вы здесь». */}
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
          {t("merge.new", { defaultValue: "Новая склейка" })}
        </button>
      </div>

      <div className="mt-4 min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 pb-3">
        {loading || (authed && !list.loaded) ? (
          <RailSkeleton />
        ) : !authed ? (
          <div className="vs-card mx-1 rounded-2xl p-3.5">
            <p className="text-[13px] leading-snug text-muted">
              {t("merge.rail.guest", { defaultValue: "Войдите — и ваши склейки сохранятся здесь." })}
            </p>
            <a
              href={signInHref(back)}
              onClick={() => rememberReturnPath(back)}
              className={vx(VS_PILL, VS_PILL_ON, "mt-3 max-md:h-11")}
            >
              <FiLogIn className="shrink-0" aria-hidden="true" />
              {t("top.signin", { defaultValue: "Войти" })}
            </a>
          </div>
        ) : list.failed && list.items.length === 0 ? (
          // Не загрузилось — не «здесь появятся»: склейки есть, их просто не видно.
          <div role="alert" className="flex flex-col items-start gap-1 px-2.5 py-2">
            <p className="text-[13px] leading-snug text-muted">
              {t("merge.rail.failed", { defaultValue: "Не удалось загрузить склейки" })}
            </p>
            <button
              type="button"
              disabled={list.loading}
              onClick={onReload}
              className={vx(VS_BTN_LINK, "-ml-2 !text-vs-accent disabled:cursor-default disabled:opacity-60")}
            >
              <FiRefreshCw className={vx(list.loading && "animate-spin motion-reduce:animate-none")} aria-hidden="true" />
              {t("page.retry", { defaultValue: "Попробовать снова" })}
            </button>
          </div>
        ) : list.items.length === 0 ? (
          <p className="px-2.5 py-2 text-[13px] leading-snug text-muted-2">
            {t("merge.rail.empty", { defaultValue: "Здесь появятся ваши склейки" })}
          </p>
        ) : (
          <>
            <h3 className={vx(VS_LABEL, "px-2.5 pb-1.5")}>{listLabel}</h3>
            <ul className="flex flex-col gap-0.5">
              {list.items.map((p) => (
                <MergeItem
                  key={p.id}
                  project={p}
                  active={p.id === openId}
                  running={isActive(p.status) || list.activeId === p.id}
                  onOpen={() => {
                    onOpen(p.id);
                    onNavigate?.();
                  }}
                  onDelete={() => onDelete(p.id)}
                />
              ))}
            </ul>
            {list.hasMore && (
              <button
                type="button"
                disabled={list.loading}
                onClick={onMore}
                className={vx(VS_BTN_LINK, "mt-2 w-full justify-center disabled:cursor-default disabled:opacity-60")}
              >
                {list.loading ? t("page.loading", { defaultValue: "Загружаем…" }) : t("nav.more", { defaultValue: "Показать ещё" })}
              </button>
            )}
          </>
        )}
      </div>

      <div className="shrink-0 border-t border-border px-2 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2">
        {/* Соседние разделы сайта: полный переход, заранее не грузим — код студий тяжёлый. */}
        {VSTUDIO_NAV && (
          <Link href="/video-studio" prefetch={false} className={VS_MENU_ITEM}>
            <FiVideo className="shrink-0 text-muted" aria-hidden="true" />
            <span className="min-w-0 flex-1 truncate">{t("merge.rail.vstudio", { defaultValue: "Видеостудия" })}</span>
            <FiArrowUpRight className="shrink-0 text-muted-2" aria-hidden="true" />
          </Link>
        )}
        <Link href="/studio" prefetch={false} className={VS_MENU_ITEM}>
          <FiFilm className="shrink-0 text-muted" aria-hidden="true" />
          <span className="min-w-0 flex-1 truncate">{t("nav.cartoon", { defaultValue: "Мультстудия" })}</span>
          <FiArrowUpRight className="shrink-0 text-muted-2" aria-hidden="true" />
        </Link>
        <div className="mt-2 flex flex-col gap-2 px-1">
          {authed !== false && (
            <MergeBalance
              variant="rail"
              loading={loading}
              authed={authed}
              balance={balance}
              failed={balanceFailed}
              onTopup={() => {
                onTopup();
                onNavigate?.();
              }}
            />
          )}
          <div className="flex items-center justify-end gap-2">
            <ThemeToggle />
            {loading ? (
              <span className={vx(VS_ICON_BTN, "pointer-events-none")} aria-hidden="true" />
            ) : (
              authed && (
                <Link href="/profile" className={VS_ICON_BTN} aria-label={profileLabel} title={profileLabel}>
                  <FiUser aria-hidden="true" />
                </Link>
              )
            )}
          </div>
        </div>
      </div>
    </nav>
  );
}

function MergeItem({
  project,
  active,
  running,
  onOpen,
  onDelete,
}: {
  project: MergeProjectBrief;
  active: boolean;
  running: boolean;
  onOpen: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const [menu, setMenu] = useState(false);
  const box = useRef<HTMLLIElement>(null);
  const title = project.title.trim() || t("merge.untitled", { defaultValue: "Без названия" });
  const status = t(`merge.status.${project.status}`, { defaultValue: STATUS_RU[project.status] });
  const until = project.status === "ready" ? shortDate(project.expires_at) : "";
  const meta =
    project.status === "ready" && until
      ? t("merge.until", { defaultValue: "Хранится до {{date}}", date: until })
      : project.status === "draft"
        ? t("merge.rail.draft", { defaultValue: "Черновик · {{n}} фрагм.", n: project.fragments })
        : status;
  const runningLabel = t("merge.status.rendering", { defaultValue: STATUS_RU.rendering });
  const menuLabel = t("merge.rail.menu", { defaultValue: "Меню склейки" });
  const deleteLabel = t("library.delete", { defaultValue: "Удалить" });

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

  return (
    <li ref={box} className="group relative">
      <a
        href={`${MERGE_PATH}?id=${project.id}`}
        onClick={(e) => {
          if (!plainClick(e)) return;
          e.preventDefault();
          onOpen();
        }}
        aria-current={active ? "page" : undefined}
        className={vx(
          "relative flex min-h-11 items-center gap-2.5 rounded-xl py-1.5 pl-2.5 pr-10 text-sm transition-colors",
          VS_FOCUS,
          active
            ? "bg-vs-ink/[0.08] text-foreground dark:bg-vs-ink/[0.06]"
            : "text-foreground/70 hover:bg-vs-ink/[0.05] hover:text-foreground dark:hover:bg-vs-ink/[0.04]",
        )}
      >
        {active && <span className="absolute inset-y-2.5 left-0 w-0.5 rounded-full bg-vs-accent" aria-hidden="true" />}
        {project.poster_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={project.poster_url}
            alt=""
            loading="lazy"
            decoding="async"
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
          <span className={vx("block truncate text-[11px]", project.status === "failed" ? "text-status-fail" : "text-muted-2")}>
            {meta}
          </span>
        </span>
        {running && (
          <span className={vx(CS_DOT, "motion-safe:animate-pulse")} role="img" aria-label={runningLabel} title={runningLabel} />
        )}
      </a>
      {/* Удалять нельзя, пока склейка идёт: кредиты в резерве, сервер ответит отказом. */}
      {!isActive(project.status) && (
        <button
          type="button"
          onClick={() => setMenu((v) => !v)}
          aria-haspopup="menu"
          aria-expanded={menu}
          aria-label={menuLabel}
          className={vx(
            "absolute right-1 top-1/2 grid size-9 -translate-y-1/2 cursor-pointer place-items-center rounded-full text-muted transition-[opacity,background-color,color] hover:bg-vs-ink/[0.1] hover:text-foreground focus-visible:opacity-100 before:absolute before:-inset-1",
            VS_FOCUS,
            menu || active ? "opacity-100" : "opacity-100 pointer-fine:opacity-0 pointer-fine:group-hover:opacity-100",
          )}
        >
          <FiMoreHorizontal aria-hidden="true" />
        </button>
      )}
      {menu && (
        <div role="menu" className={vx(VS_MENU, CS_MENU_POP, "absolute right-1 top-full z-30 mt-1 w-48")}>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setMenu(false);
              const ask = t("merge.rail.deleteConfirm", {
                defaultValue: "Удалить склейку «{{title}}»? Готовый ролик тоже удалится.",
                title,
              });
              if (window.confirm(ask)) onDelete();
            }}
            className={vx(VS_MENU_ITEM, "hover:!text-status-fail")}
          >
            <FiTrash2 className="shrink-0 text-muted" aria-hidden="true" />
            {deleteLabel}
          </button>
        </div>
      )}
    </li>
  );
}

/** Заглушка списка: те же строки — кадр 44×25 и название. */
function RailSkeleton() {
  return (
    <div className="flex flex-col gap-0.5 px-2.5" aria-hidden="true">
      <div className={vx("mb-2 h-2.5 w-16 rounded-full", CS_SKELETON)} />
      {["w-3/4", "w-1/2", "w-5/6", "w-2/3"].map((w) => (
        <div key={w} className="flex min-h-11 items-center gap-2.5">
          <div className={vx("h-[25px] w-11 shrink-0 rounded-md", CS_SKELETON)} />
          <div className={vx("h-2.5 rounded-full", CS_SKELETON, w)} />
        </div>
      ))}
    </div>
  );
}

function CompactRail({ loading, authed, list, openId, balance, balanceFailed, back, onNew, onTopup, onExpand }: MergeRailProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const atNew = openId === null;
  const running = Boolean(list.activeId) || list.items.some((p) => isActive(p.status));
  const newLabel = t("merge.new", { defaultValue: "Новая склейка" });
  const listLabel = t("merge.rail.title", { defaultValue: "Мои склейки" });
  const runningLabel = t("merge.status.rendering", { defaultValue: STATUS_RU.rendering });
  const vstudioLabel = t("merge.rail.vstudio", { defaultValue: "Видеостудия" });
  const cartoonLabel = t("nav.cartoon", { defaultValue: "Мультстудия" });
  const profileLabel = t("nav.profile", { defaultValue: "Профиль" });

  return (
    <nav aria-label={listLabel} className="flex h-full flex-col items-center gap-1.5 pb-3">
      <Link href="/" className={vx("grid h-14 w-11 shrink-0 place-items-center rounded-xl", VS_FOCUS)} aria-label="EsAI">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/esai-mark.svg" alt="" className="size-7 rounded-lg ring-1 ring-vs-ink/10" />
      </Link>
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
        <FiScissors className="text-lg" aria-hidden="true" />
        {running && <span className={vx(CS_DOT, "absolute right-2 top-2 motion-safe:animate-pulse")} aria-hidden="true" />}
      </button>
      {VSTUDIO_NAV && (
        <Link href="/video-studio" prefetch={false} className={VS_ICON_BTN} aria-label={vstudioLabel} title={vstudioLabel}>
          <FiVideo className="text-lg" aria-hidden="true" />
        </Link>
      )}
      <Link href="/studio" prefetch={false} className={VS_ICON_BTN} aria-label={cartoonLabel} title={cartoonLabel}>
        <FiFilm className="text-lg" aria-hidden="true" />
      </Link>
      <div className="flex-1" />
      <MergeBalance
        variant="compact"
        loading={loading}
        authed={authed}
        balance={balance}
        failed={balanceFailed}
        onTopup={onTopup}
        back={back}
      />
      <ThemeToggle variant="compact" />
      {!loading && authed && (
        <Link href="/profile" className={VS_ICON_BTN} aria-label={profileLabel} title={profileLabel}>
          <FiUser className="text-lg" aria-hidden="true" />
        </Link>
      )}
    </nav>
  );
}

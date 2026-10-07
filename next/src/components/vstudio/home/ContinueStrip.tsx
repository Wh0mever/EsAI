"use client";

import { useCallback, useId, useState, useSyncExternalStore } from "react";
import type { MouseEvent, RefCallback } from "react";
import { useTranslation } from "react-i18next";
import { FiArrowRight, FiChevronLeft, FiChevronRight, FiFilm, FiGrid } from "react-icons/fi";
import type { Uid } from "@/lib/vstudio/types";
import { useVStudio } from "../context";
import { VS_CARD, VS_FOCUS, VS_H2, VS_ICON_BTN, VS_SECTION, VS_SECTION_GAP, vx } from "../ui/skin";
import { useReveal } from "../ui/useReveal";
import { trackHomePick } from "./homePick";
import { lastActive } from "./strip/stripLogic";
import { EDGE_FADE, useEdgeFade } from "./strip/useEdgeFade";

/** Пропсов нет: проекты, вход и переход берутся из useVStudio(). */
export type ContinueStripProps = Record<string, never>;

const MAX_PROJECTS = 8;

/* ------------------------------------------------------------------ */
/* Минутные часы для подписи «5 минут назад»                           */
/* ------------------------------------------------------------------ */

// Секундные часы ленты (feed/TakeStatus) перерисовывали бы карточки каждую
// секунду, а без часов вкладка, открытая с вечера, утром писала бы «только что».

const MINUTE_MS = 60_000;

const minute = {
  now: 0,
  timer: null as ReturnType<typeof setInterval> | null,
  subs: new Set<() => void>(),
};

function tickMinute() {
  minute.now = Date.now();
  minute.subs.forEach((f) => f());
}

/** Вкладку вернули на экран: в фоне браузер таймеры придерживает, сверяемся сразу. */
function onTabVisible() {
  if (document.visibilityState === "visible") tickMinute();
}

function subscribeMinute(cb: () => void): () => void {
  minute.subs.add(cb);
  if (!minute.timer) {
    minute.timer = setInterval(tickMinute, MINUTE_MS);
    document.addEventListener("visibilitychange", onTabVisible);
  }
  return () => {
    minute.subs.delete(cb);
    if (!minute.subs.size && minute.timer) {
      clearInterval(minute.timer);
      minute.timer = null;
      document.removeEventListener("visibilitychange", onTabVisible);
      // Следующий, кто спросит время, возьмёт свежее, а не оставшееся с прошлого раза.
      minute.now = 0;
    }
  };
}

const subscribeNever = () => () => {};
const readMinute = () => {
  if (!minute.now) minute.now = Date.now();
  return minute.now;
};
const serverMinute = () => 0;

/* ------------------------------------------------------------------ */

/** Лента на экране: точка «идёт генерация» пульсирует, только пока её видно. */
function useOnScreen<T extends HTMLElement>(): [RefCallback<T>, boolean] {
  const [seen, setSeen] = useState(false);
  const ref = useCallback((node: T | null) => {
    if (!node || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        const last = entries[entries.length - 1];
        if (last) setSeen(last.isIntersecting);
      },
      { root: node.closest("[data-vs-feed]") },
    );
    io.observe(node);
    return () => io.disconnect();
  }, []);
  return [ref, seen];
}

/** Кадр проекта; не загрузился или его ещё нет — значок плёнки. */
function Thumb({ src }: { src: string | null }) {
  const [broken, setBroken] = useState(false);
  return (
    <span className="block aspect-video overflow-hidden bg-surface-2">
      {src && !broken ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt=""
          loading="lazy"
          decoding="async"
          draggable={false}
          onError={() => setBroken(true)}
          className="h-full w-full object-cover"
        />
      ) : (
        <span className="grid h-full w-full place-items-center text-xl text-muted-2">
          <FiFilm aria-hidden />
        </span>
      )}
    </span>
  );
}

// Кольцо фокуса — у самой ссылки, фактура карточки — у вложенного блока: тень vs-card кольцо бы перекрыла.
const CARD_LINK = vx(
  "group block h-full w-full cursor-pointer rounded-2xl text-left transition-transform duration-200 active:scale-[0.97] motion-reduce:transition-none",
  VS_FOCUS,
);
const CARD_FACE = vx(VS_CARD, "vs-card-hover vs-sheen h-full");

/**
 * «Продолжить»: последние проекты вошедшего человека — одно нажатие, и он там,
 * где остановился. У гостя и у того, кто ещё ничего не снимал, секции нет.
 */
export default function ContinueStrip() {
  const { t, i18n } = useTranslation("vstudio", { useSuspense: false });
  const { state, dispatch, actions, authed, breakpoint } = useVStudio();
  const reveal = useReveal<HTMLElement>();
  const { attach, fade, page } = useEdgeFade<HTMLDivElement>();
  const [watch, seen] = useOnScreen<HTMLUListElement>();
  const headingId = useId();

  // Поиск в левой колонке сужает общий список проектов. Секция при этом не
  // должна мигать и пустеть — держим последний список, полученный без поиска.
  const { items, q, loading } = state.projects;
  const settled = !q && !loading;
  const [recent, setRecent] = useState(items);
  if (settled && recent !== items) setRecent(items);
  const projects = (settled ? items : recent).slice(0, MAX_PROJECTS);

  const shown = authed === true && projects.length > 0;
  const now = useSyncExternalStore(shown ? subscribeMinute : subscribeNever, readMinute, serverMinute);
  if (!shown) return null;

  const untitled = t("nav.untitled", { defaultValue: "Без названия" });
  // На широком экране история и так открыта слева — карточка «Все проекты» там лишняя.
  const railHidden = breakpoint !== "desktop";

  const open = (e: MouseEvent<HTMLAnchorElement>, uid: Uid) => {
    trackHomePick("continue", uid);
    // Ctrl/⌘/Shift и средняя кнопка — как у обычной ссылки: проект в новой вкладке.
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    actions.openProject(uid);
  };

  const openAll = () => {
    trackHomePick("continue", "all");
    dispatch({ type: "ui/panel", panel: "rail", open: true });
  };

  return (
    <section ref={reveal} aria-labelledby={headingId} className={vx(VS_SECTION, VS_SECTION_GAP, "vs-reveal")}>
      {/* Высота строки задана заранее: стрелки появляются после замера ленты и не должны её сдвигать. */}
      <div className="flex items-end justify-between gap-4 md:min-h-10">
        <h2 id={headingId} className={VS_H2}>
          {t("home.continue.title", { defaultValue: "Продолжить" })}
        </h2>
        {fade !== "none" && (
          <div className="hidden shrink-0 gap-2 md:flex">
            <button
              type="button"
              onClick={() => page(-1)}
              disabled={fade === "start"}
              className={VS_ICON_BTN}
              aria-label={t("home.continue.prev", { defaultValue: "Прокрутить назад" })}
            >
              <FiChevronLeft aria-hidden />
            </button>
            <button
              type="button"
              onClick={() => page(1)}
              disabled={fade === "end"}
              className={VS_ICON_BTN}
              aria-label={t("home.continue.next", { defaultValue: "Прокрутить вперёд" })}
            >
              <FiChevronRight aria-hidden />
            </button>
          </div>
        )}
      </div>

      {/* Поля по вертикали — чтобы лента не срезала кольцо фокуса карточек. */}
      <div
        ref={attach}
        className={vx(
          "vs-noscroll -mx-4 -mb-1 mt-3 overflow-x-auto px-4 py-1 sm:-mx-6 sm:px-6",
          EDGE_FADE[fade],
        )}
      >
        <ul ref={watch} className="flex w-max gap-3">
          {projects.map((project) => {
            const running = project.open_takes > 0;
            const when = running ? "" : lastActive(project.last_activity_at, now, i18n.language);
            return (
              <li key={project.uid} className="w-[220px] shrink-0">
                <a href={`/video-studio/${project.uid}`} onClick={(e) => open(e, project.uid)} className={CARD_LINK}>
                  <span className={vx(CARD_FACE, "block")}>
                    <Thumb key={project.thumb_url ?? ""} src={project.thumb_url} />
                    <span className="block px-3 pb-3 pt-2.5">
                      <span className="block truncate text-sm font-medium text-foreground">
                        {project.title.trim() || untitled}
                      </span>
                      <span className="mt-1 flex h-4 items-center gap-1.5 text-[11px] leading-4 text-muted">
                        {running ? (
                          <>
                            <span
                              aria-hidden
                              className={vx(
                                "size-1.5 shrink-0 rounded-full bg-accent",
                                seen && "animate-pulse motion-reduce:animate-none",
                              )}
                            />
                            <span className="truncate text-accent">
                              {t("nav.running", { defaultValue: "Идёт генерация" })}
                            </span>
                          </>
                        ) : (
                          when && (
                            <time dateTime={project.last_activity_at} className="truncate">
                              {when}
                            </time>
                          )
                        )}
                      </span>
                    </span>
                  </span>
                </a>
              </li>
            );
          })}
          {railHidden && (
            <li className="w-[148px] shrink-0">
              <button type="button" onClick={openAll} className={CARD_LINK}>
                <span className={vx(CARD_FACE, "flex flex-col items-center justify-center gap-2.5 px-3 text-center")}>
                  <span className="grid size-10 place-items-center rounded-full border border-white/10 bg-white/[0.05] text-muted transition-colors group-hover:text-foreground">
                    <FiGrid aria-hidden />
                  </span>
                  <span className="inline-flex items-center gap-1 text-[13px] font-medium text-foreground/85">
                    {t("home.continue.all", { defaultValue: "Все проекты" })}
                    <FiArrowRight
                      aria-hidden
                      className="shrink-0 text-muted-2 transition-transform duration-200 group-hover:translate-x-0.5 motion-reduce:transition-none"
                    />
                  </span>
                </span>
              </button>
            </li>
          )}
        </ul>
      </div>
    </section>
  );
}

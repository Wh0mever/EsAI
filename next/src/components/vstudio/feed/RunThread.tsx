"use client";

import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type Dispatch, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { FiAlertTriangle, FiChevronUp, FiLoader, FiRefreshCw } from "react-icons/fi";
import { listShots } from "@/lib/vstudio/api";
import { errorText, reactionFor } from "@/lib/vstudio/errors";
import type { ActiveTake, FeedState, Uid, VsAction, VsError, VsKind, VsState } from "@/lib/vstudio/types";
import { useVStudio, useVStudioOptional, type VStudioContextValue } from "../context";
import { useTakePolling } from "../hooks/useTakePolling";
import StudioHome from "../home/StudioHome";
import { VS_TEMPLATES, type VsStarter } from "../home/templates";
import { AUTO } from "../settings/settingsModel";
import { VS_BTN_GHOST, VS_CARD, vx } from "../ui/skin";
import EmptyState from "./EmptyState";
import { exampleDoc, starterReplaceable, type VsExample } from "./examples";
import {
  COMPOSER_FILLED_EVENT,
  exampleAspect,
  FEED_PAGE_SIZE,
  findModel,
  indexTakesByShot,
  isNearBottom,
  openTakeUids,
  shotDomId,
  shotOfTake,
  shotTakes,
} from "./feedLogic";
import { isScrollable, scrollParentOf } from "./scrollParent";
import ShotCard from "./ShotCard";
import type { ComposerFillReason } from "./ShotActions";
import type { SettledTake } from "./takePoller";

export type RunThreadProps = {
  /** Проект стора (state.project?.uid), а не адреса: по нему редьюсер принимает страницы. null — новая сессия. */
  projectUid: Uid | null;
  shots: VsState["shots"];
  takes: VsState["takes"];
  /** uid кадров по возрастанию created_at. */
  order: Uid[];
  feed: FeedState;
  models: VsState["models"];
  /** ?take=<uid> или клик по тосту — прокрутить и подсветить. */
  focusTake: Uid | null;
  dispatch: Dispatch<VsAction>;
  /** Вид в композере: пример другого вида сначала переключает вкладку. */
  composerKind?: VsKind;
  /** Модель композера: пропорцию примера берём, только если модель её умеет. */
  composerModel?: string | null;
  /** false — не опрашивать дубли (гость). По умолчанию true. */
  polling?: boolean;
  /**
   * Кто грузит страницы ленты. true — сама лента (listShots). false —
   * контейнер (FE-1): первую страницу при открытии проекта, «раньше» — по
   * loadOlder. По умолчанию: внутри <VideoStudio> — контейнер, вне — сама.
   */
  selfLoad?: boolean;
  /** «Показать раньше» силами контейнера (actions.loadOlderShots). */
  loadOlder?: () => void | Promise<void>;
  /** Контейнер прокрутки ленты (feedScrollRef контекста); без него ищем ближайший прокручиваемый предок. */
  scrollRef?: { current: HTMLElement | null };
  /**
   * Карточка или пример заполнили композер: фокус в редактор, на телефоне —
   * показать композер. Кроме этой ручки всегда шлётся событие окна
   * COMPOSER_FILLED_EVENT — композер слушает его сам, без пропсов.
   */
  onComposerFilled?: (reason: ComposerFillReason) => void;
  /** Свой обработчик примера; по умолчанию — composer/kind, composer/doc, composer/params. */
  onExample?: (example: VsExample, text: string) => void;
  /**
   * Первый экран студии (StudioHome) вместо пустого состояния, пока проекта
   * нет. Флаг ставит контейнер — тот же, по которому оболочка отдаёт ленте всю
   * ширину; StudioHome читает стор из контекста, поэтому вне <VideoStudio> —
   * false. У проекта без кадров остаётся EmptyState.
   */
  home?: boolean;
  /**
   * Что контейнер показывает на месте ленты, пока её нет: каркас открывающегося
   * проекта, «Проект не найден», просьбу войти. Сама лента остаётся
   * смонтированной: в ней единственный опрос дублей страницы, и он не должен
   * останавливаться, пока человек ходит между проектами.
   */
  cover?: ReactNode;
  className?: string;
};

/* ------------------------------------------------------------------ */
/* Прокрутка: лента живёт либо в своей колонке (overflow-y), либо в окне */
/* ------------------------------------------------------------------ */

type Scroller = {
  target: HTMLElement | Window;
  metrics: () => { scrollTop: number; clientHeight: number; scrollHeight: number };
  toBottom: (smooth: boolean) => void;
  by: (dy: number) => void;
};

function boxScroller(box: HTMLElement): Scroller {
  return {
    target: box,
    metrics: () => ({ scrollTop: box.scrollTop, clientHeight: box.clientHeight, scrollHeight: box.scrollHeight }),
    toBottom: (smooth) => box.scrollTo({ top: box.scrollHeight, behavior: smooth ? "smooth" : "auto" }),
    by: (dy) => box.scrollBy({ top: dy, behavior: "auto" }),
  };
}

function findScroller(node: HTMLElement | null, preferred?: HTMLElement | null): Scroller {
  if (isScrollable(preferred)) return boxScroller(preferred);
  const box = scrollParentOf(node);
  if (box) return boxScroller(box);
  const doc = document.scrollingElement || document.documentElement;
  return {
    target: window,
    metrics: () => ({ scrollTop: doc.scrollTop, clientHeight: window.innerHeight, scrollHeight: doc.scrollHeight }),
    toBottom: (smooth) => window.scrollTo({ top: doc.scrollHeight, behavior: smooth ? "smooth" : "auto" }),
    by: (dy) => window.scrollBy({ top: dy, behavior: "auto" }),
  };
}

/** До скольких страниц назад догружать ленту ради ?take=<uid>. */
const FOCUS_MAX_PAGES = 5;
/** Контейнер не начал грузить первую страницу за это время — грузим сами (страховка). */
const SELF_LOAD_FALLBACK_MS = 1500;

/** Кнопки ленты («Показать раньше», «Попробовать снова») — мельче обычных, чтобы не спорить с кадрами. */
const FEED_BTN = vx(VS_BTN_GHOST, "!text-xs");

/** Заготовка карточки в том же порядке, что у настоящей: кадр, подпись, метки. */
function FeedSkeleton() {
  return (
    <div className="flex flex-col gap-5" aria-hidden>
      {[0, 1].map((k) => (
        <div key={k} className={vx(VS_CARD, "flex flex-col gap-3 p-3 sm:p-4")}>
          <div className="vs-film aspect-video max-h-[46vh] w-full rounded-xl" />
          <div className="vs-film h-4 w-3/4 rounded-full" />
          <div className="flex gap-1.5">
            <div className="vs-film h-5 w-16 rounded-full" />
            <div className="vs-film h-5 w-24 rounded-full" />
            <div className="vs-film h-5 w-12 rounded-full" />
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * Первый экран на месте ленты. Сценарий («С чего начать») ложится только в
 * пустой запрос или поверх такой же нетронутой заготовки: свой текст человека
 * и поднятый черновик он не затирает — как «Снять похожее» и ссылка с текстом.
 * Текст композера читаем здесь, а не пропсом ленты: она (memo) не должна
 * перерисовываться на каждую букву. Первый экран живёт только внутри студии.
 */
function HomeSlot({ onStarter }: { onStarter: (starter: VsStarter) => void }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { state, actions } = useVStudio();
  const kept = t("home.templates.kept", {
    defaultValue: "В запросе уже есть ваш текст — сценарий его не заменил. Очистите запрос, чтобы взять сценарий.",
  });

  const live = useRef({ doc: state.composer.doc, toast: actions.toast, onStarter, t, kept });
  useLayoutEffect(() => {
    live.current = { doc: state.composer.doc, toast: actions.toast, onStarter, t, kept };
  });

  /** false — запрос не тронут: в нём свой текст. */
  const start = useCallback((starter: VsStarter): boolean => {
    const cur = live.current;
    // И перевод, и русский исходник: заготовку могли взять до смены языка.
    const starters = VS_TEMPLATES.flatMap((tpl) => [
      tpl.prompt,
      cur.t(`home.tpl.${tpl.id}.prompt`, { defaultValue: tpl.prompt }),
    ]);
    if (!starterReplaceable(cur.doc, starters)) {
      cur.toast(cur.kept, "info");
      return false;
    }
    cur.onStarter(starter);
    return true;
  }, []);

  return <StudioHome onStarter={start} />;
}

/**
 * Лента результатов (§9.2, §9.4): кадры проекта от старых к новым, новые —
 * внизу, у композера. Страницы подгружаются при прокрутке вверх
 * (IntersectionObserver) или кнопкой «Показать раньше», позиция при этом
 * не прыгает. Здесь же живёт единственный useTakePolling страницы: он
 * опрашивает ВСЕ открытые дубли стора, включая восстановленные из других
 * проектов, а при готовом результате докручивает ленту, если человек внизу.
 */
function RunThreadView({
  projectUid,
  shots,
  takes,
  order,
  feed,
  models,
  focusTake,
  dispatch,
  composerKind,
  composerModel,
  polling = true,
  selfLoad = true,
  loadOlder: loadOlderExternal,
  scrollRef,
  onComposerFilled,
  onExample,
  home = false,
  cover,
  className,
}: RunThreadProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const rootRef = useRef<HTMLElement | null>(null);
  const topRef = useRef<HTMLDivElement | null>(null);
  const atBottomRef = useRef(true);
  const projectRef = useRef(projectUid);
  const feedRef = useRef(feed);
  const externalRef = useRef(loadOlderExternal);
  const scrollPrefRef = useRef(scrollRef);
  const inflightRef = useRef<string | null>(null);
  const anchorRef = useRef<{ el: HTMLElement; top: number; first: Uid | undefined } | null>(null);
  const initialRef = useRef<string | null>(null);
  const tailRef = useRef<Uid | undefined>(undefined);
  const focusPagesRef = useRef<{ take: Uid | null; pages: number }>({ take: null, pages: 0 });
  // Сколько раз лента сама запрашивала первую страницу проекта: страховка от
  // петли, если редьюсер отбросит ответ (проект в сторе ещё не выставлен).
  const autoRef = useRef<{ project: Uid | null; count: number }>({ project: null, count: 0 });

  const [loadError, setLoadError] = useState<{ project: Uid; error: VsError } | null>(null);
  const [readyFor, setReadyFor] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<Uid | null>(null);

  const projectKey = projectUid || "new";
  const covered = cover != null;

  const filledRef = useRef(onComposerFilled);
  useEffect(() => {
    projectRef.current = projectUid;
    feedRef.current = feed;
    externalRef.current = loadOlderExternal;
    scrollPrefRef.current = scrollRef;
    filledRef.current = onComposerFilled;
  });
  // Стабильная ручка для карточек: новая стрелка у родителя не перерисует всю ленту.
  const onFilled = useCallback((reason: ComposerFillReason) => {
    filledRef.current?.(reason);
    try {
      window.dispatchEvent(new CustomEvent(COMPOSER_FILLED_EVENT, { detail: { reason } }));
    } catch {
      /* старый браузер без CustomEvent — композер просто не возьмёт фокус */
    }
  }, []);

  // Контейнер прокрутки ищем каждый раз заново: на телефоне и компьютере
  // оболочка может прокручивать разные элементы.
  const scroller = useCallback(
    (): Scroller => findScroller(rootRef.current, scrollPrefRef.current?.current ?? null),
    [],
  );

  // «Человек внизу» отслеживаем постоянно: после обновления DOM мерить поздно.
  useEffect(() => {
    let s = findScroller(rootRef.current, scrollPrefRef.current?.current ?? null);
    const onScroll = () => {
      atBottomRef.current = isNearBottom(s.metrics());
    };
    const onResize = () => {
      const next = findScroller(rootRef.current, scrollPrefRef.current?.current ?? null);
      if (next.target !== s.target) {
        s.target.removeEventListener("scroll", onScroll);
        s = next;
        s.target.addEventListener("scroll", onScroll, { passive: true });
      }
      onScroll();
    };
    s.target.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onResize);
    onScroll();
    return () => {
      s.target.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onResize);
    };
  }, []);

  /* ---------- страницы ---------- */

  /** Опора для прокрутки: верхняя карточка и её положение до вставки старых. */
  const captureAnchor = useCallback(() => {
    const first = rootRef.current?.querySelector<HTMLElement>("[data-shot]");
    anchorRef.current = first ? { el: first, top: first.getBoundingClientRect().top, first: first.dataset.shot } : null;
  }, []);

  const loadPage = useCallback(
    async (before: string | null) => {
      const uid = projectUid;
      if (!uid) return;
      const key = `${uid}:${before || "first"}`;
      if (inflightRef.current === key) return;
      inflightRef.current = key;
      // Повтор первой страницы после ошибки: лента уже «загружена» пустой, и
      // только older=true даёт редьюсеру взять курсор из ответа.
      const older = Boolean(before) || feedRef.current.loaded;
      dispatch({ type: "feed/loading" });
      const res = await listShots(uid, { before, limit: FEED_PAGE_SIZE });
      if (inflightRef.current === key) inflightRef.current = null;
      if (projectRef.current !== uid) return; // проект сменили, пока ждали
      if (res.ok) {
        setLoadError(null);
        dispatch({ type: "feed/loaded", page: res.data, older });
        return;
      }
      anchorRef.current = null;
      if (reactionFor(res.error).kind === "not_found") dispatch({ type: "page/status", status: "not_found" });
      setLoadError({ project: uid, error: res.error });
      // Отдельного feed/failed нет: пустая страница снимает loading и не трогает курсор.
      dispatch({ type: "feed/loaded", page: { items: [], next: before ? before : null }, older: Boolean(before) });
    },
    [projectUid, dispatch],
  );

  // Первая страница проекта. Внутри <VideoStudio> её грузит контейнер, а
  // лента подстраховывает: если за 1.5 с загрузка так и не началась — сама.
  useEffect(() => {
    // Пока контейнер показывает своё (covered), первую страницу ведёт он сам.
    if (covered || !projectUid || feed.loaded || feed.loading) return;
    const auto = autoRef.current;
    if (auto.project !== projectUid) {
      auto.project = projectUid;
      auto.count = 0;
    }
    if (auto.count >= 3) return;
    const go = () => {
      auto.count += 1;
      void loadPage(null);
    };
    if (selfLoad) {
      go();
      return;
    }
    const id = window.setTimeout(() => {
      const f = feedRef.current;
      if (projectRef.current === projectUid && !f.loaded && !f.loading) go();
    }, SELF_LOAD_FALLBACK_MS);
    return () => window.clearTimeout(id);
  }, [covered, projectUid, feed.loaded, feed.loading, selfLoad, loadPage]);

  const loadOlder = useCallback(() => {
    const f = feedRef.current;
    if (!f.next || f.loading) return;
    captureAnchor();
    const external = externalRef.current;
    if (!selfLoad && external) void external();
    else void loadPage(f.next);
  }, [selfLoad, captureAnchor, loadPage]);

  // Верх ленты показался — грузим раньше. Только после первой прокрутки вниз,
  // иначе на старте страница сама себя догружала бы до самого начала.
  // order в зависимостях: после вставки страницы наблюдатель пересоздаётся —
  // если верх всё ещё виден (короткие кадры), он сразу попросит следующую.
  const olderReady = readyFor === projectKey && Boolean(feed.next);
  useEffect(() => {
    const node = topRef.current;
    if (!olderReady || !node || typeof IntersectionObserver === "undefined") return;
    const target = scroller().target;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) loadOlder();
      },
      { root: target instanceof HTMLElement ? target : null, rootMargin: "600px 0px 0px 0px" },
    );
    io.observe(node);
    return () => io.disconnect();
  }, [olderReady, loadOlder, order, scroller]);

  /* ---------- прокрутка ---------- */

  // Старые кадры вставлены сверху: возвращаем опорную карточку на её место.
  useLayoutEffect(() => {
    const a = anchorRef.current;
    if (!a || order[0] === a.first) return;
    anchorRef.current = null;
    if (!a.el.isConnected) return;
    const dy = a.el.getBoundingClientRect().top - a.top;
    if (Math.abs(dy) > 1) scroller().by(dy);
  }, [order, scroller]);

  // Загрузка «раньше» закончилась ничем (ошибка, пустая страница) — опора больше не нужна.
  useEffect(() => {
    if (feed.loading) return;
    const a = anchorRef.current;
    if (a && order[0] === a.first) anchorRef.current = null;
  }, [feed.loading, order]);

  // Первая загрузка проекта — сразу к новым (они внизу, у композера).
  const initialDone = projectUid ? feed.loaded : true;
  useLayoutEffect(() => {
    if (!initialDone || initialRef.current === projectKey) return;
    initialRef.current = projectKey;
    tailRef.current = order[order.length - 1];
    if (!focusTake && order.length) scroller().toBottom(false);
  }, [initialDone, projectKey, order, focusTake, scroller]);

  // Подгрузку «раньше» включаем кадром позже — когда лента уже внизу.
  useEffect(() => {
    if (!initialDone || readyFor === projectKey) return;
    const raf = requestAnimationFrame(() => setReadyFor(projectKey));
    return () => cancelAnimationFrame(raf);
  }, [initialDone, readyFor, projectKey]);

  // Новый кадр внизу (нажали «Создать») — показать его. Догрузка старых
  // меняет только верх, хвост при этом тот же.
  useLayoutEffect(() => {
    if (initialRef.current !== projectKey) return;
    const tail = order[order.length - 1];
    if (!tail || tail === tailRef.current) return;
    tailRef.current = tail;
    scroller().toBottom(true);
  }, [order, projectKey, scroller]);

  // Готов результат, а человек был внизу — докрутить, чтобы ролик был виден.
  const onSettled = useCallback(
    (settled: SettledTake[]) => {
      if (!atBottomRef.current) return;
      if (!settled.some((s) => shots.has(s.take.shot))) return;
      // Два кадра анимации: сначала React вставит плеер, потом меряем высоту.
      requestAnimationFrame(() => requestAnimationFrame(() => scroller().toBottom(true)));
    },
    [shots, scroller],
  );

  /* ---------- ?take=<uid> ---------- */

  useEffect(() => {
    if (!focusTake) return;
    const tracker = focusPagesRef.current;
    if (tracker.take !== focusTake) {
      tracker.take = focusTake;
      tracker.pages = 0;
    }
    const shotUid = shotOfTake(focusTake, takes, shots);
    if (!shotUid || !order.includes(shotUid)) {
      // takes/active/ отдаёт project_uid: дубль из другого проекта здесь не найти.
      const elsewhere = (takes.get(focusTake) as Partial<ActiveTake> | undefined)?.project_uid;
      if (projectUid && elsewhere && elsewhere !== projectUid) {
        dispatch({ type: "ui/focusTake", take: null });
        return;
      }
      if (!projectUid || !feed.loaded || feed.loading) return;
      if (feed.next && tracker.pages < FOCUS_MAX_PAGES) {
        tracker.pages += 1;
        loadOlder();
      } else {
        // Дубля нет в этом проекте (или он слишком давно) — просто забываем.
        dispatch({ type: "ui/focusTake", take: null });
      }
      return;
    }
    const raf = requestAnimationFrame(() => {
      document.getElementById(shotDomId(shotUid))?.scrollIntoView({ block: "center", behavior: "smooth" });
      setHighlight(shotUid);
      dispatch({ type: "ui/focusTake", take: null });
    });
    return () => cancelAnimationFrame(raf);
  }, [focusTake, takes, shots, order, projectUid, feed.loaded, feed.loading, feed.next, loadOlder, dispatch]);

  useEffect(() => {
    if (!highlight) return;
    const id = window.setTimeout(() => setHighlight(null), 2600);
    return () => window.clearTimeout(id);
  }, [highlight]);

  /* ---------- опрос ---------- */

  const openUids = useMemo(() => openTakeUids(takes.values()), [takes]);
  useTakePolling(openUids, { takes, dispatch, onSettled, enabled: polling });

  /* ---------- пример и сценарий первого экрана ---------- */

  // Один путь для карточки примера и для сценария первого экрана: вид → текст
  // → пропорция → фокус в композер. Ничего не запускается и не тратится.
  const applyStarter = useCallback(
    (starter: VsStarter) => {
      const sameKind = composerKind === starter.kind;
      if (!sameKind) dispatch({ type: "composer/kind", kind: starter.kind });
      dispatch({ type: "composer/doc", doc: exampleDoc(starter.text) });
      // «Авто» умеет любая модель (пропорция берётся с фото), остальные — только если модель их знает.
      const aspect =
        starter.aspect === AUTO
          ? AUTO
          : exampleAspect(starter.aspect, models, starter.kind, sameKind ? composerModel : null);
      if (aspect) dispatch({ type: "composer/params", params: { aspect_ratio: aspect } });
      onFilled("example");
    },
    [composerKind, composerModel, models, dispatch, onFilled],
  );

  const pickExample = useCallback(
    (example: VsExample, text: string) => {
      if (onExample) {
        onExample(example, text);
        return;
      }
      applyStarter({ kind: example.kind, text, aspect: example.params.aspect_ratio });
    },
    [onExample, applyStarter],
  );

  /* ---------- разметка ---------- */

  const byShot = useMemo(() => indexTakesByShot(takes.values()), [takes]);
  const list = useMemo(
    () =>
      order.flatMap((uid) => {
        const shot = shots.get(uid);
        return shot ? [{ shot, takes: shotTakes(shot, byShot.get(uid)) }] : [];
      }),
    [order, shots, byShot],
  );

  const error = loadError && loadError.project === projectUid ? loadError.error : null;
  const firstLoading = Boolean(projectUid) && !feed.loaded && list.length === 0 && !error;
  const empty = list.length === 0 && !firstLoading && !error && (!projectUid || feed.loaded) && !feed.next;
  // Проекта нет — первый экран; пустой проект остаётся с примерами.
  const showHome = home && empty && !projectUid;

  if (covered) {
    return (
      <section ref={rootRef} className={vx("w-full", className)}>
        {cover}
      </section>
    );
  }

  return (
    <section
      ref={rootRef}
      // Первый экран — не лента: у его секций свои заголовки, ширина и поля.
      aria-label={showHome ? undefined : t("feed.aria", { defaultValue: "Лента генераций" })}
      className={vx("flex w-full flex-col", !showHome && "mx-auto max-w-[920px] gap-5", className)}
    >
      {feed.next && list.length > 0 && (
        <div ref={topRef} className="flex justify-center">
          <button
            type="button"
            onClick={loadOlder}
            disabled={feed.loading}
            className={vx(FEED_BTN, "disabled:!cursor-wait")}
          >
            {feed.loading ? <FiLoader className="animate-spin motion-reduce:animate-none" aria-hidden /> : <FiChevronUp aria-hidden />}
            {feed.loading
              ? t("feed.loading", { defaultValue: "Загружаем…" })
              : t("feed.earlier", { defaultValue: "Показать раньше" })}
          </button>
        </div>
      )}

      {error && (
        <div
          className="flex flex-wrap items-center gap-2.5 rounded-xl border border-status-fail/25 bg-status-fail/[0.07] p-3 text-sm leading-snug text-foreground"
          role="alert"
        >
          <FiAlertTriangle className="shrink-0 text-status-fail" aria-hidden />
          <span className="min-w-0 flex-1">
            {t("feed.loadFailed", { defaultValue: "Не удалось загрузить ленту." })} {errorText(t, error)}
          </span>
          <button
            type="button"
            onClick={() => {
              if (list.length) loadOlder();
              else void loadPage(null);
            }}
            className={FEED_BTN}
          >
            <FiRefreshCw aria-hidden />
            {t("feed.retry", { defaultValue: "Попробовать снова" })}
          </button>
        </div>
      )}

      {firstLoading && <FeedSkeleton />}

      {empty && (showHome ? <HomeSlot onStarter={applyStarter} /> : <EmptyState onPick={pickExample} />)}

      {list.length > 0 && (
        <div role="feed" aria-busy={feed.loading} className="flex flex-col gap-5">
          {list.map(({ shot, takes: shotTakeList }) => (
            <ShotCard
              key={shot.uid}
              shot={shot}
              takes={shotTakeList}
              model={findModel(models, shot.kind, shot.model?.id)}
              focusTake={focusTake}
              highlighted={highlight === shot.uid}
              dispatch={dispatch}
              onComposerFilled={onFilled}
            />
          ))}
        </div>
      )}
    </section>
  );
}

const MemoRunThreadView = memo(RunThreadView);

/** Необязательные пропсы: внутри <VideoStudio> всё остальное берётся из контекста. */
export type RunThreadOwnProps = Partial<RunThreadProps>;

function fromContext(ctx: VStudioContextValue): RunThreadProps {
  const s = ctx.state;
  return {
    projectUid: s.project?.uid ?? null,
    shots: s.shots,
    takes: s.takes,
    order: s.order,
    feed: s.feed,
    models: s.models,
    focusTake: s.ui.focusTake,
    dispatch: ctx.dispatch,
    composerKind: s.composer.kind,
    composerModel: s.composer.model,
    polling: ctx.authed !== false,
    selfLoad: false,
    loadOlder: ctx.actions.loadOlderShots,
    scrollRef: ctx.feedScrollRef,
  };
}

/** Пропсы-«пустышки» (undefined) не должны затирать значения из контекста. */
function definedOnly<T extends object>(o: T): Partial<T> {
  const out: Partial<T> = {};
  for (const [k, v] of Object.entries(o)) if (v !== undefined) (out as Record<string, unknown>)[k] = v;
  return out;
}

/**
 * Лента. Внутри <VideoStudio> достаточно `<RunThread />` (плюс по желанию
 * home, onComposerFilled и className): стор, dispatch, «показать раньше» и
 * контейнер прокрутки берутся из контекста. Вне студии (витрина, тест
 * вёрстки) все поля передаются пропсами, и лента грузит страницы сама.
 */
export default function RunThread(props: RunThreadOwnProps) {
  const ctx = useVStudioOptional();
  if (ctx) return <MemoRunThreadView {...fromContext(ctx)} {...definedOnly(props)} />;
  if (!props.shots || !props.takes || !props.order || !props.feed || !props.dispatch) return null;
  // Первому экрану нужен контекст студии — без него остаётся пустое состояние.
  return <MemoRunThreadView {...(props as RunThreadProps)} home={false} />;
}

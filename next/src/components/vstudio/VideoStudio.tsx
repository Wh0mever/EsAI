"use client";

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";
import { FiAlertTriangle, FiFilm, FiLogIn, FiPlus, FiRefreshCw, FiWifiOff, FiX } from "react-icons/fi";
import PaywallModal from "@/components/chat/PaywallModal";
import TopUpModal from "@/components/chat/TopUpModal";
import { StudioAuthDialog } from "@/components/studio/StudioDialogs";
import { useBalance } from "@/hooks/useBalance";
import { ensureAccess, getToken } from "@/tools/fetchData";
import { isJwtValid, parseJwtPayload } from "@/tools/jwt";
import { rememberReturnPath } from "@/tools/authNext";
import {
  activeTakes,
  archiveProject as archiveProjectApi,
  fixturesEnabled,
  getProject,
  isUid,
  listProjects,
  listShots,
  trackVs,
  updateProject,
} from "@/lib/vstudio/api";
import { errorText, reactionFor } from "@/lib/vstudio/errors";
import { clearDraft, loadDraft, saveDraft } from "@/lib/vstudio/draft";
import type {
  ActiveTake,
  ModelsResponse,
  PageStatus,
  ProjectJSON,
  ProjectsState,
  Toast,
  Uid,
  VsAction,
  VsError,
  VsState,
} from "@/lib/vstudio/types";
import { VStudioContext, useVStudio } from "./context";
import type { HandleErrorOptions, VStudioActions, VStudioContextValue } from "./context";
import { createInitialState, parseStudioPath, reducer, reservedNow, studioReserved } from "./store";
import type { BalanceSnapshot } from "./store";
import VStudioShell, { useVsBreakpoint } from "./VStudioShell";
import ProjectRail from "./ProjectRail";
import StudioTopBar, { StudioHeader } from "./StudioTopBar";
import { useRestoreActive } from "./hooks/useRestoreActive";
import { useVisualViewport } from "./hooks/useVisualViewport";
import { loadVStudioModels } from "./hooks/useVStudioModels";
import RunThread from "./feed/RunThread";
import { TAKES_SETTLED_EVENT } from "./feed/feedLogic";
import Composer from "./composer/Composer";
import DropOverlay from "./composer/DropOverlay";
import AssetLibrarySheet from "./library/AssetLibrarySheet";
import RunSettingsPanel from "./settings/RunSettingsPanel";
import SettingsSheet from "./settings/SettingsSheet";
import KindTabs from "./settings/KindTabs";
import { selectKind, useRunSettingsSync } from "./settings/useRunSettingsSync";

/**
 * Видеостудия: контейнер страницы (§9.3).
 *
 * Здесь живут стор (useReducer со store.ts) и контекст, через который его
 * читают все части студии; загрузка моделей, истории и ленты проекта;
 * «Восстановили N генераций»; черновик гостя; окна входа, пэйволла и
 * пополнения; всплывающие сообщения; состояния страницы (скелетон, «Проект
 * не найден», «Нет сети», «Видеостудия скоро откроется»).
 *
 * Переходы между проектами — через history.pushState/replaceState: Next
 * встраивает их в свой роутер (usePathname обновляется), а студия при этом
 * не пересоздаётся. Иначе первый запуск в новой сессии (адрес меняется на
 * /video-studio/<uid>) пересоздал бы страницу и потерял бы лоток с
 * картинкой, которая ещё создаётся.
 */

const BASE = "/video-studio";
const PROJECTS_PAGE = 30;
const SHOTS_PAGE = 20;
const SETTINGS_COLLAPSED_KEY = "vstudio:ui:settingsCollapsed";
const DRAFT_SAVE_MS = 400;

/* ------------------------------------------------------------------ */
/* Память вкладки: студия рисуется сразу, свежие данные догружаются фоном */
/* ------------------------------------------------------------------ */

type Memory = { key: string; models?: ModelsResponse; projects?: ProjectsState };
let memory: Memory | null = null;

/** Чей кэш: выход и вход другим человеком в той же вкладке не должны показать чужую историю. */
function sessionKey(): string {
  const payload = parseJwtPayload<{ user_id?: number | string }>(getToken("access"));
  return payload?.user_id != null ? `u${payload.user_id}` : "guest";
}

function seedFromMemory(): Partial<Pick<VsState, "mode" | "available" | "models" | "projects">> | undefined {
  if (!memory || memory.key !== sessionKey()) return undefined;
  const seed: Partial<Pick<VsState, "mode" | "available" | "models" | "projects">> = {};
  if (memory.models) {
    seed.mode = memory.models.mode;
    seed.available = memory.models.available;
    seed.models = { video: memory.models.video, image: memory.models.image };
  }
  if (memory.projects) seed.projects = { ...memory.projects, loading: false, q: "" };
  return seed;
}

/* ------------------------------------------------------------------ */
/* Мелочи                                                              */
/* ------------------------------------------------------------------ */

/** «1 генерацию / 2 генерации / 5 генераций» для русского текста по умолчанию. */
function ruPlural(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}

/** Режим фикстур: «гость» берётся из настроек мока, а не из cookie. */
function fixturesGuest(): boolean {
  try {
    const raw = window.localStorage.getItem("vstudio:fixtures:opts");
    const o = raw ? (JSON.parse(raw) as { guest?: unknown }) : null;
    return Boolean(o && o.guest === true);
  } catch {
    return false;
  }
}

async function checkAuth(): Promise<boolean> {
  if (fixturesEnabled()) return !fixturesGuest();
  try {
    return await ensureAccess();
  } catch {
    return false;
  }
}

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(SETTINGS_COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

function writeCollapsed(v: boolean) {
  try {
    if (v) window.localStorage.setItem(SETTINGS_COLLAPSED_KEY, "1");
    else window.localStorage.removeItem(SETTINGS_COLLAPSED_KEY);
  } catch {
    /* хранилище недоступно — просто не запомним */
  }
}

/* ------------------------------------------------------------------ */
/* Контейнер                                                           */
/* ------------------------------------------------------------------ */

export type VideoStudioProps = {
  /** uid проекта из адреса; null — новая генерация (/video-studio). */
  projectUid: string | null;
};

export default function VideoStudio({ projectUid }: VideoStudioProps) {
  const { t, ready } = useTranslation("vstudio", { useSuspense: false });

  const [initial] = useState(() => createInitialState(seedFromMemory()));
  const [state, baseDispatch] = useReducer(reducer, initial);
  // Зеркало стора: действия и побочные эффекты видят состояние сразу после
  // dispatch, не дожидаясь перерисовки (редьюсер чистый — результат тот же).
  const latest = useRef<VsState>(initial);

  const [authed, setAuthed] = useState<boolean | null>(null);
  const [online, setOnline] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  /** Проект или его лента не загрузились (не 404): кнопка «Попробовать снова» вместо ленты. */
  const [feedError, setFeedError] = useState<{ uid: Uid; error: VsError } | null>(null);
  const [collapsed, setCollapsed] = useState<boolean>(() => (typeof window === "undefined" ? false : readCollapsed()));
  const [railSearch, setRailSearch] = useState(false);
  /** Баланс из последнего quote/запуска и сумма резерва дублей в этот момент (для поправки). */
  const [balSnap, setBalSnap] = useState<BalanceSnapshot | null>(null);

  const breakpoint = useVsBreakpoint();
  const breakpointRef = useRef(breakpoint);
  useVisualViewport({ cssVars: true });
  const { balance: accountBalance } = useBalance();
  const feedScrollRef = useRef<HTMLDivElement | null>(null);

  const pathname = usePathname();
  const route = useMemo(() => parseStudioPath(pathname, projectUid), [pathname, projectUid]);

  // Ссылки на свежие значения для стабильных действий контекста.
  const authedRef = useRef(authed);
  const routeRef = useRef(route);
  const tRef = useRef(t);
  useEffect(() => {
    authedRef.current = authed;
    breakpointRef.current = breakpoint;
    routeRef.current = route;
    tRef.current = t;
  });

  const loadSeq = useRef(0);
  const projSeq = useRef(0);
  const toastSeq = useRef(0);
  const draftReady = useRef(false);
  const viewTracked = useRef(false);
  /** Дубль → проект: клик по тосту о дубле из другого проекта открывает тот проект. */
  const takeProjects = useRef(new Map<Uid, Uid>());
  /** Сверка открытых дублей с сервером (syncActive ниже; ссылка — для обработчиков, объявленных раньше). */
  const syncActiveRef = useRef<() => void>(() => {});

  /* ---------- dispatch с побочными эффектами ---------- */

  const onActionRef = useRef<(a: VsAction, prev: VsState, next: VsState) => void>(() => {});
  const dispatch = useCallback((action: VsAction) => {
    const prev = latest.current;
    const next = reducer(prev, action);
    latest.current = next;
    baseDispatch(action);
    onActionRef.current(action, prev, next);
  }, []);

  const setPage = useCallback(
    (status: PageStatus) => {
      if (latest.current.ui.page !== status) dispatch({ type: "page/status", status });
    },
    [dispatch],
  );

  const flushDraft = useCallback(() => {
    if (authedRef.current !== false) return;
    const c = latest.current.composer;
    saveDraft({ kind: c.kind, model: c.model, params: c.params, doc: c.doc });
  }, []);

  useEffect(() => {
    onActionRef.current = (action, prev, next) => {
      switch (action.type) {
        case "run/failed":
          // Ответа на запуск не было (сеть): сервер мог уже создать дубль и
          // держать резерв. Сверяемся сразу и ещё раз, когда появится сеть, —
          // иначе вкладка не видит дубль, не считает его в лимит и не опрашивает.
          if (action.error.status === 0) syncActiveRef.current();
          break;
        case "ui/auth":
          // Окно входа — главный шаг воронки гостя; черновик должен пережить уход на вход.
          if (action.open && !prev.ui.auth) {
            trackVs("vstudio_auth_prompt");
            flushDraft();
          }
          break;
        case "ui/panel":
          // «Другая модель» из карточки открывает параметры: на ≥1280 колонка
          // могла быть свёрнута человеком — разворачиваем её (и запоминаем).
          if (action.panel === "settings" && action.open === true && breakpointRef.current === "desktop") {
            setCollapsed(false);
            writeCollapsed(false);
          }
          break;
        case "quote/loaded": {
          const b = action.quote.balance;
          if (b) setBalSnap({ balance: b.balance, reserved: b.reserved, local: studioReserved(next) });
          break;
        }
        case "run/done": {
          const r = action.response;
          if (r.balance) setBalSnap({ balance: r.balance.balance, reserved: r.balance.reserved, local: studioReserved(next) });
          takeProjects.current.set(r.take.uid, r.project.uid);
          // Первый запуск новой сессии создал проект: адрес → /video-studio/<uid>
          // без перезагрузки (история браузера не растёт — replace).
          if (next.project?.uid === r.project.uid && routeRef.current.uid !== r.project.uid) {
            try {
              window.history.replaceState(null, "", `${BASE}/${r.project.uid}`);
            } catch {
              /* без смены адреса студия работает так же */
            }
          }
          clearDraft();
          break;
        }
        default:
          break;
      }
    };
  });

  /* ---------- действия контекста ---------- */

  const toast = useCallback(
    (text: string, tone: Toast["tone"] = "info", take?: Uid | null) => {
      if (!text) return;
      toastSeq.current += 1;
      dispatch({ type: "ui/toast", toast: { id: `vs${toastSeq.current}`, tone, text, ...(take ? { take } : {}) } });
    },
    [dispatch],
  );

  const openAuth = useCallback(() => dispatch({ type: "ui/auth", open: true }), [dispatch]);

  const requireAuth = useCallback((): boolean => {
    const a = authedRef.current;
    if (a) return true;
    if (a === null && !fixturesEnabled() && isJwtValid(getToken("access"))) return true;
    openAuth();
    return false;
  }, [openAuth]);

  const handleError = useCallback(
    (err: VsError, opts?: HandleErrorOptions) => {
      const r = reactionFor(err);
      const say = () => {
        if (!opts?.silent) toast(errorText(tRef.current, err), "error");
      };
      switch (r.kind) {
        case "paywall":
          dispatch({ type: "ui/paywall", paywall: r.paywall });
          break;
        case "auth":
          openAuth();
          break;
        case "disabled":
          setPage("disabled");
          break;
        case "offline":
        case "retry_later":
        case "message":
          say();
          break;
        default:
          break;
      }
      return r;
    },
    [dispatch, openAuth, setPage, toast],
  );

  const fetchProjects = useCallback(
    async (q: string, before: string | null) => {
      const seq = ++projSeq.current;
      dispatch({ type: "projects/loading" });
      const res = await listProjects({ q, before, limit: PROJECTS_PAGE });
      if (seq !== projSeq.current) return;
      if (res.ok) {
        dispatch({ type: "projects/loaded", page: res.data, append: Boolean(before) });
        return;
      }
      // Список остаётся прежним, только снимаем «загрузку».
      const cur = latest.current.projects;
      dispatch({ type: "projects/loaded", page: { items: cur.items, next: cur.next }, append: false });
      handleError(res.error, { silent: true });
    },
    [dispatch, handleError],
  );

  const newSession = useCallback(() => {
    loadSeq.current += 1;
    setFeedError(null);
    dispatch({ type: "project/set", project: null });
    dispatch({ type: "composer/reset" });
    dispatch({ type: "ui/panel", panel: "rail", open: false });
    if (latest.current.ui.page === "not_found") setPage(latest.current.models ? "ready" : "loading");
    const r = routeRef.current;
    if (r.uid || r.invalid) {
      try {
        window.history.pushState(null, "", BASE);
      } catch {
        window.location.assign(BASE);
      }
    }
  }, [dispatch, setPage]);

  const openProject = useCallback(
    (uid: Uid | null, opts?: { take?: Uid | null }) => {
      if (!uid) {
        newSession();
        return;
      }
      if (!isUid(uid)) return;
      dispatch({ type: "ui/panel", panel: "rail", open: false });
      const take = opts?.take && isUid(opts.take) ? opts.take : null;
      if (uid === routeRef.current.uid && latest.current.project?.uid === uid) {
        if (take) dispatch({ type: "ui/focusTake", take });
        return;
      }
      const url = `${BASE}/${uid}${take ? `?take=${take}` : ""}`;
      try {
        window.history.pushState(null, "", url);
      } catch {
        window.location.assign(url);
      }
    },
    [dispatch, newSession],
  );

  const actions = useMemo<VStudioActions>(
    () => ({
      requireAuth,
      handleError,
      toast,
      openProject,
      newSession,
      renameProject: async (uid, title) => {
        const res = await updateProject(uid, { title });
        if (!res.ok) {
          handleError(res.error);
          return false;
        }
        dispatch({ type: "projects/upsert", project: res.data });
        return true;
      },
      archiveProject: async (uid) => {
        const res = await archiveProjectApi(uid);
        if (!res.ok) {
          handleError(res.error);
          return false;
        }
        dispatch({ type: "projects/remove", uid });
        if (latest.current.project?.uid === uid || routeRef.current.uid === uid) newSession();
        toast(tRef.current("nav.archived", { defaultValue: "Проект убран в архив" }), "ok");
        return true;
      },
      searchProjects: (q) => {
        if (q === latest.current.projects.q) return;
        dispatch({ type: "projects/query", q });
        void fetchProjects(q, null);
      },
      loadMoreProjects: async () => {
        const p = latest.current.projects;
        if (!p.next || p.loading) return;
        await fetchProjects(p.q, p.next);
      },
      loadOlderShots: async () => {
        const s = latest.current;
        if (!s.project || !s.feed.next || s.feed.loading) return;
        const projectUid = s.project.uid;
        const cursor = s.feed.next;
        dispatch({ type: "feed/loading" });
        const res = await listShots(projectUid, { before: cursor, limit: SHOTS_PAGE });
        if (latest.current.project?.uid !== projectUid) return;
        if (!res.ok) {
          // Курсор прежний: «показать раньше» можно нажать ещё раз.
          dispatch({ type: "feed/loaded", page: { items: [], next: cursor }, older: true });
          handleError(res.error);
          return;
        }
        dispatch({ type: "feed/loaded", page: res.data, older: true });
      },
      upsertProject: (project) => dispatch({ type: "projects/upsert", project }),
      openLibrary: () => {
        if (!requireAuth()) return;
        dispatch({ type: "ui/panel", panel: "library", open: true });
      },
      openPaywall: (paywall) => dispatch({ type: "ui/paywall", paywall }),
      openTopUp: () => {
        if (!requireAuth()) return;
        dispatch({ type: "ui/topup", open: true });
      },
      refreshBalance: () => {
        try {
          window.dispatchEvent(new Event("balance:refresh"));
        } catch {
          /* старые браузеры без конструктора Event */
        }
      },
    }),
    [dispatch, fetchProjects, handleError, newSession, openProject, requireAuth, toast],
  );

  /* ---------- вход ---------- */

  useEffect(() => {
    let alive = true;
    const check = () => {
      void checkAuth().then((ok) => {
        if (alive) setAuthed(ok);
      });
    };
    check();
    // Вкладка могла простоять сутки: access живёт 12 ч, а вход мог случиться в соседней вкладке.
    const onVisible = () => {
      if (document.visibilityState === "visible") check();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      alive = false;
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  /* ---------- первый шаг воронки ---------- */

  useEffect(() => {
    if (viewTracked.current) return;
    viewTracked.current = true;
    trackVs("vstudio_view");
  }, []);

  /* ---------- модели и режим студии ---------- */

  useEffect(() => {
    if (authed === null) return;
    let alive = true;
    void (async () => {
      // Общий с панелью параметров кэш: запрос models/ уходит один на вкладку.
      const res = await loadVStudioModels({ force: reloadKey > 0 });
      if (!alive) return;
      if (!res.ok) {
        // Модели уже есть из памяти вкладки — студия работает, просто без свежего списка.
        if (latest.current.models) {
          if (reactionFor(res.error).kind === "offline") setOnline(false);
          return;
        }
        setPage(reactionFor(res.error).kind === "offline" ? "offline" : "error");
        return;
      }
      dispatch({ type: "models/loaded", payload: res.data });
      const { mode, available } = res.data;
      if (mode === "off" || !available) {
        setPage("disabled");
        return;
      }
      const page = latest.current.ui.page;
      if (page === "loading" || page === "offline" || page === "error" || page === "disabled") setPage("ready");
    })();
    return () => {
      alive = false;
    };
  }, [authed, reloadKey, dispatch, setPage]);

  const canUse = state.mode !== null && state.mode !== "off" && state.available;

  // Выбор модели и параметров, Project.settings (PATCH) — трек параметров. На
  // телефоне панель живёт в закрытой шторке, поэтому хук зовёт и контейнер.
  useRunSettingsSync(state, dispatch);

  /* ---------- история ---------- */

  useEffect(() => {
    if (authed !== true || !canUse) return;
    void fetchProjects(latest.current.projects.q, null);
  }, [authed, canUse, reloadKey, fetchProjects]);

  /* ---------- проект из адреса ---------- */

  /**
   * Проект и первая страница ленты. Ответ: null — показали, {uid, error} —
   * не загрузилось (не 404), undefined — ответ устарел (ушли на другой адрес).
   */
  const loadProject = useCallback(
    async (uid: Uid): Promise<{ uid: Uid; error: VsError } | null | undefined> => {
      const seq = ++loadSeq.current;
      // Название из истории — сразу, пока грузится остальное; лента — скелетоном.
      const known = latest.current.projects.items.find((p) => p.uid === uid) ?? null;
      dispatch({ type: "project/set", project: known });
      dispatch({ type: "feed/loading" });
      const [p, s] = await Promise.all([getProject(uid), listShots(uid, { limit: SHOTS_PAGE })]);
      if (seq !== loadSeq.current) return undefined;
      if (!p.ok) {
        const r = reactionFor(p.error);
        if (r.kind === "not_found") {
          dispatch({ type: "project/set", project: null });
          setPage("not_found");
          return null;
        }
        if (r.kind === "offline" && !latest.current.models) {
          setPage("offline");
          return null;
        }
        handleError(p.error);
        return { uid, error: p.error };
      }
      const project: ProjectJSON = p.data;
      dispatch({ type: "project/set", project });
      dispatch({ type: "projects/upsert", project });
      if (latest.current.ui.page === "not_found") setPage(latest.current.models ? "ready" : "loading");
      if (!s.ok) {
        handleError(s.error, { silent: true });
        return { uid, error: s.error };
      }
      dispatch({ type: "feed/loaded", page: s.data, older: false });
      // ?take=<uid> — прокрутить к карточке (ссылка из пуша или тоста) и убрать из адреса.
      try {
        const take = new URLSearchParams(window.location.search).get("take");
        if (take && isUid(take)) {
          dispatch({ type: "ui/focusTake", take });
          window.history.replaceState(null, "", `${BASE}/${uid}`);
        }
      } catch {
        /* адрес без параметров — ничего */
      }
      return null;
    },
    [dispatch, handleError, setPage],
  );

  /** Загрузить проект и запомнить исход для «Попробовать снова». */
  const openRoute = useCallback(
    (uid: Uid) => {
      void loadProject(uid).then((outcome) => {
        if (outcome !== undefined) setFeedError(outcome);
      });
    },
    [loadProject],
  );

  useEffect(() => {
    if (authed === null) return;
    const cur = latest.current;
    // Уход на другой адрес отменяет загрузку прежнего проекта: её ответ выбросится.
    if (route.invalid) {
      loadSeq.current += 1;
      if (cur.project) dispatch({ type: "project/set", project: null });
      setPage("not_found");
      return;
    }
    if (!route.uid) {
      loadSeq.current += 1;
      if (cur.project) dispatch({ type: "project/set", project: null });
      if (cur.ui.page === "not_found") setPage(cur.models ? "ready" : "loading");
      return;
    }
    // Уже показываем этот проект (например, его только что создал первый запуск).
    if (cur.project?.uid === route.uid) return;
    if (!authed) {
      // Гость по ссылке на проект: окно входа, не 401 в ленте.
      loadSeq.current += 1;
      if (cur.project) dispatch({ type: "project/set", project: null });
      return;
    }
    openRoute(route.uid);
  }, [route.uid, route.invalid, authed, dispatch, openRoute, setPage]);

  /* ---------- «Восстановили N генераций» ---------- */

  const onRestored = useCallback(
    (items: ActiveTake[]) => {
      for (const it of items) if (isUid(it.project_uid)) takeProjects.current.set(it.uid, it.project_uid);
      const n = items.length;
      const text = tRef.current("page.restored", {
        count: n,
        n,
        defaultValue: ruPlural(
          n,
          "Восстановили {{count}} генерацию",
          "Восстановили {{count}} генерации",
          "Восстановили {{count}} генераций",
        ),
      });
      toast(text, "info", items[0]?.uid ?? null);
    },
    [toast],
  );
  useRestoreActive({ enabled: authed === true && canUse, dispatch, onRestored });

  /**
   * Сверка открытых дублей с сервером: после запуска, ответ на который
   * потерялся (status 0), и при появлении сети. Найденное кладём в стор — его
   * подхватит опрос, лимит «2 видео» и уведомление «готово». Новый кадр
   * текущего проекта — перечитываем первую страницу ленты, чтобы появилась
   * карточка; дубли в других проектах (и в новой сессии) — тост со ссылкой.
   */
  const syncActive = useCallback(async () => {
    const s0 = latest.current;
    if (authedRef.current !== true || !s0.mode || s0.mode === "off" || !s0.available) return;
    const res = await activeTakes();
    if (!res.ok) return; // сети всё ещё нет — повторим на событии online
    const items = Array.isArray(res.data.items) ? res.data.items : [];
    for (const it of items) if (isUid(it.project_uid)) takeProjects.current.set(it.uid, it.project_uid);
    const before = latest.current;
    const unknown = items.filter((it) => !before.takes.has(it.uid));
    if (!items.length) return;
    dispatch({ type: "takes/upsert", takes: items });
    if (!unknown.length) return;
    const current = before.project?.uid ?? null;
    const here = unknown.filter((it) => it.project_uid === current);
    if (current && here.some((it) => !before.shots.has(it.shot))) {
      const page = await listShots(current, { limit: SHOTS_PAGE });
      if (page.ok && latest.current.project?.uid === current) {
        dispatch({ type: "feed/loaded", page: page.data, older: false });
      }
    }
    const elsewhere = unknown.filter((it) => it.project_uid !== current);
    if (elsewhere.length) onRestored(elsewhere);
  }, [dispatch, onRestored]);
  useEffect(() => {
    syncActiveRef.current = () => void syncActive();
  }, [syncActive]);

  // Дубли закрылись: строка проекта в «Истории» («Идёт генерация», превью)
  // устарела — её считает сервер, поэтому перечитываем эти проекты.
  useEffect(() => {
    const onSettled = (e: Event) => {
      const detail = (e as CustomEvent<Array<{ uid: Uid; shot: Uid }>>).detail;
      const s = latest.current;
      const uids = new Set<Uid>();
      for (const it of Array.isArray(detail) ? detail : []) {
        const uid = s.shots.get(it.shot)?.project ?? takeProjects.current.get(it.uid);
        if (uid && isUid(uid)) uids.add(uid);
      }
      for (const uid of uids) {
        void getProject(uid).then((res) => {
          if (res.ok) dispatch({ type: "projects/upsert", project: res.data });
        });
      }
    };
    window.addEventListener(TAKES_SETTLED_EVENT, onSettled);
    return () => window.removeEventListener(TAKES_SETTLED_EVENT, onSettled);
  }, [dispatch]);

  /* ---------- черновик гостя ---------- */

  useEffect(() => {
    if (authed === null || draftReady.current) return;
    draftReady.current = true;
    const d = loadDraft();
    if (!d) return;
    dispatch({ type: "composer/restore", draft: d });
    // Вошёл — черновик своё отслужил: дальше текст живёт в композере и в проекте.
    if (authed) clearDraft();
  }, [authed, dispatch]);

  const { kind, model, params, doc } = state.composer;
  useEffect(() => {
    if (authed !== false || !draftReady.current) return;
    const id = window.setTimeout(() => saveDraft({ kind, model, params, doc }), DRAFT_SAVE_MS);
    return () => window.clearTimeout(id);
  }, [authed, kind, model, params, doc]);

  useEffect(() => {
    // Закрыли вкладку раньше паузы сохранения — дописываем сразу.
    const onHide = () => flushDraft();
    window.addEventListener("pagehide", onHide);
    return () => window.removeEventListener("pagehide", onHide);
  }, [flushDraft]);

  /* ---------- сеть ---------- */

  useEffect(() => {
    const sync = () => setOnline(navigator.onLine !== false);
    const onOnline = () => {
      setOnline(true);
      // Страница так и не загрузилась из-за сети — пробуем снова сами.
      if (latest.current.ui.page === "offline") setReloadKey((k) => k + 1);
      // Пока сети не было, запуск мог дойти до сервера без ответа — сверяемся.
      syncActiveRef.current();
    };
    const onOffline = () => setOnline(false);
    sync();
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, []);

  /* ---------- память вкладки ---------- */

  useEffect(() => {
    const key = sessionKey();
    if (!memory || memory.key !== key) memory = { key };
    if (state.models && state.mode) {
      memory.models = { mode: state.mode, available: state.available, video: state.models.video, image: state.models.image };
    }
    if (state.projects.loaded && !state.projects.q) memory.projects = state.projects;
  }, [state.models, state.mode, state.available, state.projects]);

  /* ---------- баланс и резерв ---------- */

  const takesMap = state.takes;
  const localReserved = useMemo(() => studioReserved({ takes: takesMap }), [takesMap]);
  const reserved = reservedNow(balSnap, localReserved);
  const balance = authed ? (accountBalance ?? balSnap?.balance ?? null) : null;

  /* ---------- контекст ---------- */

  const ctx = useMemo<VStudioContextValue>(
    () => ({
      state,
      dispatch,
      actions,
      authed,
      balance,
      reserved,
      online,
      breakpoint,
      routeProject: route.uid,
      feedScrollRef,
    }),
    [state, dispatch, actions, authed, balance, reserved, online, breakpoint, route.uid],
  );

  /* ---------- раскладка ---------- */

  const desktop = breakpoint === "desktop";
  const settingsTitle = t("settings.title", { defaultValue: "Параметры запуска" });
  const currentPath = route.uid ? `${BASE}/${route.uid}` : BASE;
  const guestProject = authed === false && Boolean(route.uid);
  const page = state.ui.page;
  const routeError = feedError && feedError.uid === route.uid ? feedError.error : null;
  // Проект из адреса ещё не показан или его лента впервые грузится — скелетон.
  const routePending =
    Boolean(route.uid) &&
    authed === true &&
    page !== "not_found" &&
    !routeError &&
    (state.project?.uid !== route.uid || (state.feed.loading && !state.feed.loaded));

  const toggleSettings = () => {
    if (desktop) {
      const next = !collapsed;
      setCollapsed(next);
      writeCollapsed(next);
    } else {
      dispatch({ type: "ui/panel", panel: "settings" });
    }
  };

  let body: ReactNode;
  // Пока не пришёл models/, режим студии неизвестен: «Проект не найден» по
  // кривой ссылке не показываем раньше, чем узнаем, не закрыта ли студия вовсе.
  if (!ready || (!state.models && (page === "loading" || page === "not_found"))) {
    body = <PageSkeleton />;
  } else if (page === "disabled") {
    body = <DisabledPage guest={authed === false} returnTo={currentPath} />;
  } else if ((page === "offline" || page === "error") && !state.models) {
    body = <LoadErrorPage offline={page === "offline"} onRetry={() => setReloadKey((k) => k + 1)} />;
  } else {
    let feed: ReactNode;
    if (page === "not_found") {
      feed = (
        <CenterMessage
          icon={<FiFilm />}
          title={t("page.notFound", { defaultValue: "Проект не найден" })}
          hint={t("page.notFoundHint", { defaultValue: "Возможно, он в архиве или ссылка с ошибкой." })}
          action={
            <button type="button" onClick={newSession} className={PRIMARY_BTN}>
              <FiPlus />
              {t("nav.new", { defaultValue: "Новая генерация" })}
            </button>
          }
        />
      );
    } else if (guestProject) {
      feed = (
        <CenterMessage
          icon={<FiLogIn />}
          title={t("auth.project", { defaultValue: "Войдите, чтобы открыть этот проект" })}
          hint={t("auth.projectHint", { defaultValue: "Проекты видеостудии видны только их автору." })}
          action={
            <a
              href={`/auth/signin?next=${encodeURIComponent(currentPath)}`}
              onClick={() => rememberReturnPath(currentPath)}
              className={PRIMARY_BTN}
            >
              <FiLogIn />
              {t("top.signin", { defaultValue: "Войти" })}
            </a>
          }
        />
      );
    } else if (routeError) {
      feed = (
        <CenterMessage
          icon={<FiAlertTriangle />}
          title={errorText(t, routeError)}
          action={
            <button
              type="button"
              onClick={() => {
                if (!route.uid) return;
                setFeedError(null);
                openRoute(route.uid);
              }}
              className={SECONDARY_BTN}
            >
              <FiRefreshCw />
              {t("page.retry", { defaultValue: "Попробовать снова" })}
            </button>
          }
        />
      );
    } else if (routePending) {
      feed = <FeedSkeleton />;
    } else {
      feed = <FeedSlot />;
    }

    const hideComposer = page === "not_found" || guestProject;

    body = (
      <VStudioShell
        breakpoint={breakpoint}
        rail={(variant) =>
          variant === "compact" ? (
            <ProjectRail
              variant="compact"
              onExpand={(focus) => {
                setRailSearch(focus === "search");
                dispatch({ type: "ui/panel", panel: "rail", open: true });
              }}
            />
          ) : (
            <ProjectRail
              variant="full"
              onNavigate={() => dispatch({ type: "ui/panel", panel: "rail", open: false })}
              autoFocusSearch={railSearch && state.ui.panels.rail}
            />
          )
        }
        railOpen={state.ui.panels.rail}
        onRailOpenChange={(open) => {
          if (!open) setRailSearch(false);
          dispatch({ type: "ui/panel", panel: "rail", open });
        }}
        header={
          <StudioHeader
            kindTabs={<KindTabsSlot />}
            settingsOpen={desktop ? !collapsed : state.ui.panels.settings}
            onToggleSettings={toggleSettings}
          />
        }
        topBar={
          <StudioTopBar
            onMenu={() => dispatch({ type: "ui/panel", panel: "rail", open: true })}
            onSettings={() => dispatch({ type: "ui/panel", panel: "settings", open: true })}
          />
        }
        banner={!online ? <OfflineBanner /> : null}
        feed={feed}
        composer={hideComposer ? null : <ComposerSlot />}
        settings={
          <RunSettingsPanel
            state={state}
            dispatch={dispatch}
            variant="panel"
            // Вкладки «Видео | Картинка» на ≥1024 стоят в строке над лентой.
            showKindTabs={breakpoint === "tablet"}
            onClose={
              desktop
                ? () => {
                    setCollapsed(true);
                    writeCollapsed(true);
                  }
                : () => dispatch({ type: "ui/panel", panel: "settings", open: false })
            }
          />
        }
        settingsSheet={<SettingsSheet state={state} dispatch={dispatch} />}
        settingsTitle={settingsTitle}
        settingsOpen={state.ui.panels.settings}
        onSettingsOpenChange={(open) => dispatch({ type: "ui/panel", panel: "settings", open })}
        settingsCollapsed={collapsed}
        feedScrollRef={feedScrollRef}
        centerOverlay={hideComposer ? null : <DropOverlay />}
        labels={{
          history: t("nav.history", { defaultValue: "История" }),
          main: t("meta.title", { defaultValue: "Видеостудия" }),
        }}
        overlays={
          <>
            <LibrarySlot />
            <ToastStack
              toasts={state.ui.toasts}
              mobile={breakpoint === "mobile"}
              onDismiss={(id) => dispatch({ type: "ui/toastDismiss", id })}
              onOpen={(toastItem) => {
                dispatch({ type: "ui/toastDismiss", id: toastItem.id });
                const take = toastItem.take;
                if (!take) return;
                const s = latest.current;
                const known = s.takes.get(take);
                if (known && s.shots.has(known.shot)) {
                  dispatch({ type: "ui/focusTake", take });
                  return;
                }
                const project = takeProjects.current.get(take);
                if (project) openProject(project, { take });
              }}
            />
          </>
        }
      />
    );
  }

  return (
    <VStudioContext.Provider value={ctx}>
      {body}
      {/* Окна — поверх любой раскладки (и поверх страницы «скоро откроется»). */}
      <PaywallModal
        context={state.ui.paywall}
        onClose={() => dispatch({ type: "ui/paywall", paywall: null })}
        onTopUp={() => dispatch({ type: "ui/topup", open: true })}
      />
      <TopUpModal
        open={state.ui.topup}
        onClose={() => {
          dispatch({ type: "ui/topup", open: false });
          actions.refreshBalance();
        }}
      />
      <StudioAuthDialog
        open={state.ui.auth}
        onClose={() => dispatch({ type: "ui/auth", open: false })}
        returnTo={currentPath}
        title={t("auth.title", { defaultValue: "Войдите, чтобы создать видео" })}
        note={t("auth.body", { defaultValue: "Черновик сохранится" })}
        onSignIn={flushDraft}
      />
    </VStudioContext.Provider>
  );
}

/* ------------------------------------------------------------------ */
/* Части других треков. Подключаются здесь, в одном месте.              */
/* Лента — feed/RunThread (FE-5), композер — composer/Composer (FE-3),  */
/* параметры — settings/RunSettingsPanel и KindTabs (FE-4), библиотека — */
/* library/AssetLibrarySheet (FE-3). Все они читают стор через           */
/* useVStudio() из ./context.                                          */
/* ------------------------------------------------------------------ */

function FeedSlot() {
  return <RunThread />;
}

function ComposerSlot() {
  return <Composer />;
}

/** «Мои материалы»: открывается по state.ui.panels.library (actions.openLibrary()). */
function LibrarySlot() {
  return <AssetLibrarySheet />;
}

/** Вкладки «Видео | Картинка» в строке над лентой (≥1024). */
function KindTabsSlot() {
  const { state, dispatch } = useVStudio();
  const { composer, models } = state;
  return (
    <KindTabs
      value={composer.kind}
      onChange={(kind) =>
        selectKind(dispatch, models, { kind: composer.kind, model: composer.model, params: composer.params }, kind)
      }
      counts={models ? { video: models.video.length, image: models.image.length } : undefined}
      className="w-60 shrink-0"
    />
  );
}

/* ------------------------------------------------------------------ */
/* Состояния страницы                                                   */
/* ------------------------------------------------------------------ */

const PRIMARY_BTN =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-accent px-5 text-sm font-semibold text-on-accent transition-colors hover:bg-accent-strong cursor-pointer";
const SECONDARY_BTN =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-xl border border-border bg-surface-2 px-5 text-sm font-medium transition-colors hover:border-border-strong cursor-pointer";

function CenterMessage({
  icon,
  title,
  hint,
  action,
}: {
  icon?: ReactNode;
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center gap-3 px-4 text-center">
      {icon && <div className="grid h-12 w-12 place-items-center rounded-full bg-surface-2 text-xl text-muted">{icon}</div>}
      <h2 className="text-lg font-semibold">{title}</h2>
      {hint && <p className="max-w-sm text-sm text-muted">{hint}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

function FullPage({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col bg-background text-foreground" style={{ minHeight: "var(--vvh, 100dvh)" }}>
      <header className="flex h-14 shrink-0 items-center px-4 pt-[env(safe-area-inset-top,0px)]">
        <Link href="/" aria-label="EsAI" className="flex items-center">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/esai-logo.svg" alt="EsAI" className="h-6 w-auto" />
        </Link>
      </header>
      <div className="flex flex-1 items-center justify-center p-4">{children}</div>
    </div>
  );
}

function DisabledPage({ guest, returnTo }: { guest: boolean; returnTo: string }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  return (
    <FullPage>
      <CenterMessage
        icon={<FiFilm />}
        title={t("page.disabled", { defaultValue: "Видеостудия скоро откроется" })}
        hint={t("page.disabledHint", {
          defaultValue: "Мы заканчиваем настройку. А пока видео можно сделать в чате или в «Мультфильмах».",
        })}
        action={
          <div className="flex flex-wrap items-center justify-center gap-2">
            <Link href="/" className={PRIMARY_BTN}>
              {t("page.toChat", { defaultValue: "Открыть чат" })}
            </Link>
            <Link href="/studio" className={SECONDARY_BTN}>
              {t("page.toCartoons", { defaultValue: "Мультфильмы" })}
            </Link>
            {guest && (
              <a
                href={`/auth/signin?next=${encodeURIComponent(returnTo)}`}
                onClick={() => rememberReturnPath(returnTo)}
                className={SECONDARY_BTN}
              >
                <FiLogIn />
                {t("top.signin", { defaultValue: "Войти" })}
              </a>
            )}
          </div>
        }
      />
    </FullPage>
  );
}

function LoadErrorPage({ offline, onRetry }: { offline: boolean; onRetry: () => void }) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  return (
    <FullPage>
      <CenterMessage
        icon={offline ? <FiWifiOff /> : <FiAlertTriangle />}
        title={
          offline
            ? t("page.offline", { defaultValue: "Нет сети — результаты не пропадут" })
            : t("page.error", { defaultValue: "Не удалось загрузить студию" })
        }
        hint={
          offline
            ? t("page.offlineHint", { defaultValue: "Генерации продолжаются на сервере. Как только связь вернётся, студия обновится сама." })
            : undefined
        }
        action={
          <button type="button" onClick={onRetry} className={SECONDARY_BTN}>
            <FiRefreshCw />
            {t("page.retry", { defaultValue: "Попробовать снова" })}
          </button>
        }
      />
    </FullPage>
  );
}

function OfflineBanner() {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  return (
    <div
      role="status"
      className="flex shrink-0 items-center justify-center gap-2 border-b border-border bg-surface-2 px-3 py-2 text-sm text-muted"
    >
      <FiWifiOff className="shrink-0 text-status-wait" />
      {t("page.offline", { defaultValue: "Нет сети — результаты не пропадут" })}
    </div>
  );
}

function PageSkeleton() {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  return (
    <div
      className="grid w-full grid-cols-1 bg-background lg:grid-cols-[64px_minmax(0,1fr)] xl:grid-cols-[240px_minmax(0,1fr)_340px]"
      style={{ height: "var(--vvh, 100dvh)" }}
      aria-busy="true"
    >
      <span className="sr-only" role="status">
        {t("page.loading", { defaultValue: "Загружаем…" })}
      </span>
      <div className="hidden border-r border-border bg-surface p-3 lg:block">
        <div className="h-6 w-24 animate-pulse rounded bg-surface-2 max-xl:w-8" />
        <div className="mt-4 h-11 animate-pulse rounded-xl bg-surface-2" />
      </div>
      <div className="flex min-h-0 flex-col">
        <div className="h-14 shrink-0 border-b border-border" />
        <div className="mx-auto w-full max-w-[860px] flex-1 overflow-hidden px-3 py-4 sm:px-4">
          <FeedSkeleton />
        </div>
        <div className="shrink-0 border-t border-border p-3">
          <div className="mx-auto h-24 w-full max-w-[860px] animate-pulse rounded-2xl bg-surface-2" />
        </div>
      </div>
      <div className="hidden border-l border-border bg-surface p-4 xl:block">
        <div className="h-5 w-40 animate-pulse rounded bg-surface-2" />
        <div className="mt-4 h-16 animate-pulse rounded-xl bg-surface-2" />
        <div className="mt-3 h-10 animate-pulse rounded-xl bg-surface-2" />
        <div className="mt-3 h-10 animate-pulse rounded-xl bg-surface-2" />
      </div>
    </div>
  );
}

function FeedSkeleton() {
  return (
    <div className="flex flex-col gap-4" aria-hidden="true">
      {[0, 1].map((i) => (
        <div key={i} className="rounded-2xl border border-border bg-surface p-4">
          <div className="h-3 w-3/4 animate-pulse rounded bg-surface-2" />
          <div className="mt-2 h-3 w-1/2 animate-pulse rounded bg-surface-2" />
          <div className="mt-4 aspect-video w-full animate-pulse rounded-xl bg-surface-2" />
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Всплывающие сообщения                                                */
/* ------------------------------------------------------------------ */

const TOAST_MS: Record<Toast["tone"], number> = { info: 6000, ok: 6000, error: 9000 };

function ToastStack({
  toasts,
  mobile,
  onDismiss,
  onOpen,
}: {
  toasts: Toast[];
  mobile: boolean;
  onDismiss: (id: string) => void;
  onOpen: (toast: Toast) => void;
}) {
  return (
    <div
      aria-live="polite"
      className={
        "pointer-events-none fixed z-[1050] flex flex-col gap-2 " +
        (mobile ? "inset-x-3 top-[calc(4rem_+_env(safe-area-inset-top,0px))]" : "right-4 top-4 w-[min(360px,calc(100vw-2rem))]")
      }
    >
      {toasts.map((toastItem) => (
        <ToastItem key={toastItem.id} toast={toastItem} onDismiss={onDismiss} onOpen={onOpen} />
      ))}
    </div>
  );
}

function ToastItem({
  toast,
  onDismiss,
  onOpen,
}: {
  toast: Toast;
  onDismiss: (id: string) => void;
  onOpen: (toast: Toast) => void;
}) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const [paused, setPaused] = useState(false);
  useEffect(() => {
    if (paused) return;
    const id = window.setTimeout(() => onDismiss(toast.id), TOAST_MS[toast.tone] ?? 6000);
    return () => window.clearTimeout(id);
  }, [paused, toast.id, toast.tone, onDismiss]);

  const tone =
    toast.tone === "error"
      ? "border-status-fail/40"
      : toast.tone === "ok"
        ? "border-status-ok/40"
        : "border-border-strong";
  const clickable = Boolean(toast.take);
  return (
    <div
      role={toast.tone === "error" ? "alert" : "status"}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      className={"pointer-events-auto flex items-start gap-2 rounded-xl border bg-surface px-3 py-2.5 text-sm shadow-xl " + tone}
    >
      {clickable ? (
        <button type="button" onClick={() => onOpen(toast)} className="min-w-0 flex-1 text-left hover:underline cursor-pointer">
          {toast.text}
        </button>
      ) : (
        <span className="min-w-0 flex-1">{toast.text}</span>
      )}
      <button
        type="button"
        onClick={() => onDismiss(toast.id)}
        className="-m-1 grid h-8 w-8 shrink-0 place-items-center rounded-lg text-muted hover:text-foreground cursor-pointer"
        aria-label={t("mobile.close", { defaultValue: "Закрыть" })}
      >
        <FiX />
      </button>
    </div>
  );
}

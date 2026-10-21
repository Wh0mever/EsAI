"use client";

import { useCallback, useEffect, useEffectEvent, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { PaywallContext } from "@/components/chat/PaywallModal";
import { isAborted, paywallContext } from "@/lib/vstudio/errors";
import type { VsError } from "@/lib/vstudio/types";
import { apiLang } from "@/lib/apiLang";
import { ensureAccess } from "@/tools/fetchData";
import {
  createProject,
  deleteProject,
  deleteUpload as deleteUploadApi,
  getConfig,
  getProject,
  listProjects,
  listSources,
  listUploads,
  patchProject,
  renderProject,
  uploadVideo,
  type UploadPhase,
} from "./mergeApi";
import {
  DEFAULT_LIMITS,
  DEFAULT_PRICE,
  MERGE_PATH,
  TABS,
  addRefusal,
  appendUnique,
  cardToItem,
  insertItem,
  isActive,
  isAspect,
  isEditable,
  isFit,
  isTab,
  isUid,
  itemRefs,
  moveItem as moveInList,
  parseAddParam,
  refusalText,
  removeAt,
  renderBlock,
  saveRetryDelay,
  shortDate,
  signature,
  toLocal,
  totalDuration,
  transientSaveError,
  type AddPlace,
  type ItemRef,
  type LocalBlock,
  type LocalItem,
  type TextSpec,
} from "./mergeLogic";
import {
  DEFAULT_UPLOAD_LIMITS,
  precheckFile,
  precheckMedia,
  precheckText,
  probeVideoFile,
  retryableUpload,
  uploadErrorCode,
  uploadErrorText,
  uploadName,
} from "./uploadLogic";
import { MERGE_ERROR_RU } from "./mergeText";
import type {
  MergeAspect,
  MergeBalance,
  MergeConfig,
  MergeFit,
  MergeLimits,
  MergeProject,
  MergeProjectBrief,
  MergeSourceCard,
  MergeTab,
  MergeUploadCard,
  MergeUploadLimits,
  MergeUploadUsage,
} from "./mergeTypes";

/**
 * Состояние страницы «Склейка видео»: вход, цена и баланс, «Мои склейки»,
 * открытая склейка, правка списка фрагментов, запуск, опрос и выбор роликов.
 *
 * Правка — на месте: добавили, убрали, переставили — экран меняется сразу, а
 * весь список уходит на сервер одним PATCH через 600 мс тишины (запись не чаще
 * 60 раз в минуту). Сохранения идут строго по очереди: ответ на старое не
 * затирает то, что человек успел поменять после. Новая склейка заводится на
 * сервере с первым фрагментом — пустые черновики в «Моих склейках» не копятся.
 *
 * Деньги решает сервер: цена резервируется при запуске и списывается, только
 * когда ролик сохранён. Здесь — только показать цену, спросить подтверждение и
 * открыть пополнение на 402.
 *
 * Свои видео («Мои файлы»): загрузка бесплатная, одна за раз, с прогрессом и
 * отменой; в склейку видео встаёт как любой фрагмент — в начало или в конец.
 */

const SAVE_DEBOUNCE_MS = 600;
const POLL_MS = 3_000;
/** После двух минут опрос реже: длинная склейка идёт несколько минут, очередь общая с мультстудией. */
const POLL_SLOW_MS = 10_000;
const POLL_SLOW_AFTER_MS = 120_000;
/** Чужую идущую склейку (в списке) проверяем реже — только ради точки в списке. */
const LIST_POLL_MS = 10_000;

const PREFS_KEY = "merge:prefs";
const LAST_KEY = "merge:last";

export type SourcesState = {
  items: MergeSourceCard[];
  page: number;
  hasMore: boolean;
  loading: boolean;
  loaded: boolean;
  failed: boolean;
};

export type ListState = {
  items: MergeProjectBrief[];
  page: number;
  hasMore: boolean;
  loading: boolean;
  loaded: boolean;
  /** Список не загрузился — в колонке «Не удалось загрузить» и повтор, а не «здесь появятся». */
  failed: boolean;
  activeId: string | null;
};

export type EditState = { items: LocalItem[]; aspect: MergeAspect; fit: MergeFit; title: string };

/** Плашка над лентой: текст и, для «уже идёт другая», ссылка на неё. */
export type MergeBanner = { text: TextSpec; openId?: string };

/**
 * Идущая загрузка своего видео: checking — читаем длину и кадр на месте,
 * upload — байты идут (pct), processing — дошли, сервер проверяет видео.
 */
export type UploadState = { name: string; phase: "checking" | UploadPhase; pct: number };

type Prefs = { aspect: MergeAspect; fit: MergeFit; tab: MergeTab | null };

const EMPTY_SOURCES: SourcesState = { items: [], page: 0, hasMore: false, loading: false, loaded: false, failed: false };
const EMPTY_LIST: ListState = { items: [], page: 0, hasMore: false, loading: false, loaded: false, failed: false, activeId: null };

function readPrefs(): Prefs {
  const prefs: Prefs = { aspect: "16:9", fit: "pad", tab: null };
  try {
    const raw = JSON.parse(window.localStorage.getItem(PREFS_KEY) || "{}") as Record<string, unknown>;
    if (isAspect(raw.aspect)) prefs.aspect = raw.aspect;
    if (isFit(raw.fit)) prefs.fit = raw.fit;
    if (isTab(raw.tab)) prefs.tab = raw.tab;
  } catch {
    /* без памяти браузера — значения по умолчанию */
  }
  return prefs;
}

function writePrefs(patch: Partial<Prefs>) {
  try {
    window.localStorage.setItem(PREFS_KEY, JSON.stringify({ ...readPrefs(), ...patch }));
  } catch {
    /* не запомнили — не беда */
  }
}

function remember(id: string | null) {
  try {
    if (id) window.localStorage.setItem(LAST_KEY, id);
    else window.localStorage.removeItem(LAST_KEY);
  } catch {
    /* не запомнили — не беда */
  }
}

function recall(): string | null {
  try {
    const v = window.localStorage.getItem(LAST_KEY);
    return isUid(v) ? v : null;
  } catch {
    return null;
  }
}

/** Адрес страницы — открытая склейка: перезагрузка возвращает к ней. */
function replaceUrl(id: string | null) {
  try {
    window.history.replaceState(null, "", id ? `${MERGE_PATH}?id=${id}` : MERGE_PATH);
  } catch {
    /* без смены адреса страница работает так же */
  }
}

function briefOf(p: MergeProject): MergeProjectBrief {
  return {
    id: p.id,
    title: p.title,
    status: p.status,
    aspect: p.aspect,
    fit: p.fit,
    fragments: p.fragments,
    total_duration_s: p.total_duration_s,
    duration_s: p.duration_s,
    poster_url: p.poster_url,
    error: p.error,
    error_code: p.error_code,
    error_fragment: p.error_fragment,
    expires_at: p.expires_at,
    created_at: p.created_at,
    updated_at: p.updated_at,
  };
}

/** Строка открытой склейки — наверх списка (сортировка сервера — по последнему изменению). */
function upsertBrief(list: ListState, p: MergeProject): ListState {
  const brief = briefOf(p);
  return { ...list, items: [brief, ...list.items.filter((x) => x.id !== p.id)] };
}

async function checkAuth(): Promise<boolean> {
  try {
    return await ensureAccess();
  } catch {
    return false;
  }
}

export type MergeModel = ReturnType<typeof useMerge>;

export function useMerge() {
  const { t, i18n } = useTranslation("vstudio", { useSuspense: false });
  const lang = apiLang(i18n.language);

  const [authed, setAuthed] = useState<boolean | null>(null);
  const [booting, setBooting] = useState(true);
  const [config, setConfig] = useState<MergeConfig | null>(null);
  const [price, setPrice] = useState<number>(DEFAULT_PRICE);
  const [balance, setBalance] = useState<MergeBalance | null>(null);
  const [balanceFailed, setBalanceFailed] = useState(false);
  const [limits, setLimits] = useState<MergeLimits>(DEFAULT_LIMITS);
  const [list, setList] = useState<ListState>(EMPTY_LIST);
  const [project, setProjectState] = useState<MergeProject | null>(null);
  const [openId, setOpenIdState] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);
  const [edit, setEditState] = useState<EditState>({ items: [], aspect: "16:9", fit: "pad", title: "" });
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<MergeBanner | null>(null);
  const [paywall, setPaywall] = useState<PaywallContext | null>(null);
  const [topup, setTopup] = useState(false);
  const [confirm, setConfirm] = useState(false);
  /** Последнее сохранение не дошло (связь, лимит, сбой сервера): видно у ленты, повтор идёт сам. */
  const [unsaved, setUnsaved] = useState(false);
  const [sources, setSources] = useState<Record<MergeTab, SourcesState>>({
    vstudio: EMPTY_SOURCES,
    cartoon: EMPTY_SOURCES,
    chat: EMPTY_SOURCES,
    upload: EMPTY_SOURCES,
  });
  const [uploadLimits, setUploadLimits] = useState<MergeUploadLimits>(DEFAULT_UPLOAD_LIMITS);
  const [uploadUsage, setUploadUsage] = useState<MergeUploadUsage | null>(null);
  const [upload, setUpload] = useState<UploadState | null>(null);
  const [uploadError, setUploadError] = useState<TextSpec | null>(null);
  /** Файл последней загрузки, которая сорвалась не из-за самого файла: «Повторить» без нового выбора. */
  const [retryFile, setRetryFile] = useState<File | null>(null);
  /** Какие свои видео сейчас удаляются (id) — их может быть несколько разом. */
  const [deletingUploads, setDeletingUploads] = useState<readonly string[]>([]);
  /** Отказ удаления — на той карточке, где нажали корзину, а не над зоной загрузки. */
  const [deleteError, setDeleteError] = useState<{ id: string; text: TextSpec } | null>(null);
  const [tab, setTabState] = useState<MergeTab>("vstudio");
  /** Куда вернуть гостя после входа: та же страница, вместе с ?add= из мультстудии. */
  const [returnPath, setReturnPath] = useState(MERGE_PATH);

  // Последние значения для асинхронных шагов: ответ сервера сверяется с тем,
  // что на экране сейчас, а не с тем, что было при отправке.
  const editRef = useRef(edit);
  const projectRef = useRef<MergeProject | null>(null);
  const openIdRef = useRef<string | null>(null);
  /** Слепок того, что лежит на сервере (формат, заполнение, фрагменты). */
  const savedSigRef = useRef("");
  /** Растёт при каждой смене открытой склейки: ответы про прежнюю отбрасываем. */
  const epochRef = useRef(0);
  const keySeq = useRef(0);
  const saveTimer = useRef(0);
  const saveChain = useRef<Promise<boolean>>(Promise.resolve(true));
  const pollStart = useRef<{ id: string; at: number } | null>(null);
  const runningRef = useRef(false);
  /** Есть правка, которая ещё не ушла на сервер (ждёт паузы или повтора). */
  const pendingRef = useRef(false);
  const unsavedRef = useRef(false);
  const retryCount = useRef(0);
  const retryDelay = useRef(0);
  const mountedRef = useRef(false);
  const flushRef = useRef<() => Promise<boolean>>(() => Promise.resolve(true));
  const langRef = useRef(lang);
  /** Отмена идущей загрузки; есть — значит, загрузка идёт (одна за раз). */
  const uploadAbort = useRef<AbortController | null>(null);
  const uploadLimitsRef = useRef(uploadLimits);
  const uploadUsageRef = useRef(uploadUsage);

  useEffect(() => {
    uploadLimitsRef.current = uploadLimits;
    uploadUsageRef.current = uploadUsage;
  }, [uploadLimits, uploadUsage]);

  useEffect(() => {
    langRef.current = lang;
  }, [lang]);

  const makeKey = useCallback(() => {
    keySeq.current += 1;
    return `f${keySeq.current}`;
  }, []);

  const commitEdit = useCallback((next: EditState) => {
    editRef.current = next;
    setEditState(next);
  }, []);

  const commitProject = useCallback((p: MergeProject | null) => {
    projectRef.current = p;
    setProjectState(p);
  }, []);

  const commitUnsaved = useCallback((value: boolean) => {
    unsavedRef.current = value;
    setUnsaved(value);
  }, []);

  const commitOpenId = useCallback((id: string | null) => {
    openIdRef.current = id;
    setOpenIdState(id);
  }, []);

  const applyBalance = useCallback((b: MergeBalance | null | undefined) => {
    if (b) {
      setBalance(b);
      setBalanceFailed(false);
    }
  }, []);

  /** Название новой склейки на языке человека (сервер по умолчанию ставит русское). */
  const defaultTitle = useCallback(
    () => t("merge.title_default", { defaultValue: "Склейка {{date}}", date: shortDate(new Date().toISOString()) }),
    [t],
  );

  const showError = useCallback((err: VsError, openActive?: string) => {
    setError({ text: refusalText(err.code, err.data, err.message), ...(openActive ? { openId: openActive } : {}) });
  }, []);

  /** Ответ сервера — на экран; reset — правка берётся из него (открыли, закончилась склейка, сброс после отказа). */
  const applyServer = useCallback(
    (p: MergeProject, reset: boolean) => {
      commitProject(p);
      setList((l) => upsertBrief(l, p));
      if (typeof p.price_credits === "number") setPrice(p.price_credits);
      if (p.limits) setLimits(p.limits);
      if (reset) {
        savedSigRef.current = signature(p.items, p.aspect, p.fit);
        const cur = editRef.current;
        commitEdit({ items: toLocal(p.items, cur.items, makeKey), aspect: p.aspect, fit: p.fit, title: p.title });
      }
    },
    [commitEdit, commitProject, makeKey],
  );

  const refreshConfig = useCallback(async () => {
    const res = await getConfig();
    if (!res.ok) {
      setBalanceFailed(true);
      return;
    }
    setConfig(res.data);
    setPrice(res.data.price_credits);
    if (res.data.limits) setLimits(res.data.limits);
    if (res.data.uploads) setUploadLimits(res.data.uploads);
    if (res.data.balance) applyBalance(res.data.balance);
  }, [applyBalance]);

  const loadList = useCallback(async (page = 1) => {
    setList((l) => ({ ...l, loading: true }));
    const res = await listProjects(page);
    if (!res.ok) {
      setList((l) => ({ ...l, loading: false, loaded: true, failed: true }));
      return null;
    }
    const data = res.data;
    setList((l) => ({
      items: page > 1 ? [...l.items, ...data.results.filter((x) => !l.items.some((y) => y.id === x.id))] : data.results,
      page,
      hasMore: data.has_more,
      loading: false,
      loaded: true,
      failed: false,
      activeId: data.active_id,
    }));
    setPrice(data.price_credits);
    if (data.limits) setLimits(data.limits);
    return data;
  }, []);

  /** «Мои файлы» — одним списком (их не больше 10) вместе с занятым местом. */
  const loadUploads = useCallback(async () => {
    setSources((s) => ({ ...s, upload: { ...s.upload, loading: true, failed: false } }));
    const res = await listUploads(lang);
    setSources((s) => {
      const cur = s.upload;
      if (!res.ok) return { ...s, upload: { ...cur, loading: false, loaded: true, failed: true } };
      return { ...s, upload: { items: res.data.results, page: 1, hasMore: false, loading: false, loaded: true, failed: false } };
    });
    if (res.ok) {
      setUploadUsage(res.data.usage);
      if (res.data.limits) setUploadLimits(res.data.limits);
    }
    return res.ok ? res.data.results.length : 0;
  }, [lang]);

  const loadSources = useCallback(
    async (which: MergeTab, page = 1) => {
      if (which === "upload") return loadUploads();
      setSources((s) => ({ ...s, [which]: { ...s[which], loading: true, failed: false } }));
      const res = await listSources(which, page, lang);
      setSources((s) => {
        const cur = s[which];
        if (!res.ok) return { ...s, [which]: { ...cur, loading: false, loaded: true, failed: true } };
        const items = page > 1 ? appendUnique(cur.items, res.data.results) : res.data.results;
        return { ...s, [which]: { items, page, hasMore: res.data.has_more, loading: false, loaded: true, failed: false } };
      });
      return res.ok ? res.data.results.length : 0;
    },
    [lang, loadUploads],
  );

  /* ---------- сохранение ---------- */

  /** Одно сохранение того, что на экране: заводит склейку или шлёт PATCH со всем списком. */
  const saveOnce = useCallback(async (): Promise<boolean> => {
    const epoch = epochRef.current;
    const cur = editRef.current;
    const id = openIdRef.current;
    const p = projectRef.current;
    if (p && !isEditable(p.status)) return true;
    const sig = signature(cur.items, cur.aspect, cur.fit);
    if (id ? sig === savedSigRef.current : cur.items.length === 0) return true;

    setSaving(true);
    const body = { aspect: cur.aspect, fit: cur.fit, items: itemRefs(cur.items) };
    const res = id
      ? await patchProject(id, body, langRef.current)
      : await createProject({ ...body, title: cur.title.trim() || defaultTitle() }, langRef.current);
    if (epoch !== epochRef.current) return false;
    setSaving(false);

    if (res.ok) {
      const saved = res.data;
      retryCount.current = 0;
      if (unsavedRef.current) {
        // Дошло после сбоя связи — плашка про сбой больше не правда.
        commitUnsaved(false);
        setError(null);
      }
      if (!id) {
        commitOpenId(saved.id);
        replaceUrl(saved.id);
        remember(saved.id);
      }
      savedSigRef.current = signature(saved.items, saved.aspect, saved.fit);
      commitProject(saved);
      setList((l) => upsertBrief(l, saved));
      // Пока шёл запрос, список не меняли — берём карточки сервера (доступность, названия).
      const now = editRef.current;
      if (signature(now.items, now.aspect, now.fit) === sig) {
        commitEdit({ ...now, items: toLocal(saved.items, now.items, makeKey), title: now.title || saved.title });
      }
      return true;
    }

    const err = res.error;
    if (err.code === "render_in_progress" || err.code === "already_ready") {
      // Склейку запустили или закончили в другой вкладке — показываем, как есть на сервере.
      showError(err);
      const fresh = id ? await getProject(id, langRef.current) : null;
      if (fresh?.ok && epoch === epochRef.current) applyServer(fresh.data, true);
      return false;
    }
    if (transientSaveError(err.code)) {
      // Сбой проходящий: на экране «Не сохранено», повтор — сам, через паузу.
      commitUnsaved(true);
      const retryIn = saveRetryDelay(err.code, retryCount.current, err.data.wait);
      if (retryIn > 0) {
        retryCount.current += 1;
        retryDelay.current = retryIn;
      }
    }
    if (err.code === "project_not_found" && id) {
      // Склейку удалили в другой вкладке: правка остаётся новым черновиком и заведётся заново.
      commitOpenId(null);
      commitProject(null);
      replaceUrl(null);
      remember(null);
      savedSigRef.current = "";
      setList((l) => ({ ...l, items: l.items.filter((x) => x.id !== id) }));
    }
    if (err.code === "source_unavailable" || err.code === "source_unreadable") {
      const index = typeof err.data.index === "number" ? err.data.index : -1;
      const now = editRef.current;
      if (index >= 0 && index < now.items.length && signature(now.items, now.aspect, now.fit) === sig) {
        commitEdit({ ...now, items: now.items.map((it, i) => (i === index ? { ...it, available: false } : it)) });
      }
    }
    showError(err);
    return false;
  }, [applyServer, commitEdit, commitOpenId, commitProject, commitUnsaved, defaultTitle, makeKey, showError]);

  /** Отложить сохранение: пауза после правки или повтор после сбоя. */
  const saveLater = useCallback((ms: number) => {
    window.clearTimeout(saveTimer.current);
    pendingRef.current = true;
    saveTimer.current = window.setTimeout(() => void flushRef.current(), ms);
  }, []);

  /** Сохранить сейчас (после текущего сохранения, если оно идёт). */
  const flush = useCallback((): Promise<boolean> => {
    window.clearTimeout(saveTimer.current);
    pendingRef.current = false;
    const run = saveChain.current.then(saveOnce, saveOnce);
    saveChain.current = run.catch(() => false);
    const afterSave = () => {
      const delay = retryDelay.current;
      retryDelay.current = 0;
      if (delay > 0 && mountedRef.current) saveLater(delay);
    };
    void run.then(afterSave, afterSave);
    return run;
  }, [saveLater, saveOnce]);

  useEffect(() => {
    flushRef.current = flush;
  }, [flush]);

  const scheduleSave = useCallback(() => saveLater(SAVE_DEBOUNCE_MS), [saveLater]);

  /** «Попробовать снова» у «Не сохранено»: сразу и с новым счётом повторов. */
  const retrySave = useCallback(() => {
    retryCount.current = 0;
    void flush();
  }, [flush]);

  // Недосохранённую правку не теряем: вкладку свернули или закрыли, ушли по
  // ссылке в колонке раньше, чем кончилась пауза автосохранения.
  useEffect(() => {
    mountedRef.current = true;
    const saveNow = () => {
      if (pendingRef.current) void flushRef.current();
    };
    const onHide = () => {
      if (document.visibilityState === "hidden") saveNow();
    };
    document.addEventListener("visibilitychange", onHide);
    window.addEventListener("pagehide", saveNow);
    return () => {
      mountedRef.current = false;
      document.removeEventListener("visibilitychange", onHide);
      window.removeEventListener("pagehide", saveNow);
      saveNow();
      window.clearTimeout(saveTimer.current);
    };
  }, []);

  /* ---------- открыть, новая, удалить ---------- */

  /** Сменить открытую склейку: всё недосказанное про прежнюю больше не нужно. */
  const switchTo = useCallback(
    (id: string | null) => {
      epochRef.current += 1;
      window.clearTimeout(saveTimer.current);
      pendingRef.current = false;
      retryCount.current = 0;
      retryDelay.current = 0;
      commitUnsaved(false);
      setSaving(false);
      setError(null);
      setConfirm(false);
      commitOpenId(id);
      replaceUrl(id);
      remember(id);
    },
    [commitOpenId, commitUnsaved],
  );

  /** Пустой редактор новой склейки — с форматом и заполнением, что выбирали в прошлый раз. */
  const resetToNew = useCallback(() => {
    commitProject(null);
    savedSigRef.current = "";
    const prefs = readPrefs();
    commitEdit({ items: [], aspect: prefs.aspect, fit: prefs.fit, title: "" });
  }, [commitEdit, commitProject]);

  const newMerge = useCallback(async () => {
    // Недосохранённое прежней склейки не теряем: сначала дописываем её, потом меняем.
    await flush();
    switchTo(null);
    setOpening(false);
    resetToNew();
  }, [flush, resetToNew, switchTo]);

  const open = useCallback(
    async (id: string) => {
      if (!isUid(id)) return;
      if (id === openIdRef.current && projectRef.current) return;
      setOpening(true);
      await flush();
      switchTo(id);
      const epoch = epochRef.current;
      const res = await getProject(id, langRef.current);
      if (epoch !== epochRef.current) return;
      setOpening(false);
      if (res.ok) {
        applyServer(res.data, true);
        return;
      }
      showError(res.error);
      if (res.error.code === "project_not_found") {
        setList((l) => ({ ...l, items: l.items.filter((x) => x.id !== id) }));
        commitOpenId(null);
        replaceUrl(null);
        remember(null);
      } else {
        // Не открылась из-за связи или сбоя сервера: пустой редактор не должен
        // записать себя поверх настоящей склейки — правка заведёт новую. Адрес и
        // память не трогаем: перезагрузка или строка в списке откроют её снова.
        commitOpenId(null);
      }
      resetToNew();
    },
    [applyServer, commitOpenId, flush, resetToNew, showError, switchTo],
  );

  const remove = useCallback(
    async (id: string) => {
      // Открытую сначала закрываем: её недосохранённая правка ушла бы уже удалённой склейке.
      if (openIdRef.current === id) {
        switchTo(null);
        setOpening(false);
        resetToNew();
      }
      const res = await deleteProject(id);
      if (!res.ok && res.error.code !== "project_not_found") {
        showError(res.error);
        return false;
      }
      setList((l) => ({ ...l, items: l.items.filter((x) => x.id !== id) }));
      return true;
    },
    [resetToNew, showError, switchTo],
  );

  const rename = useCallback(
    async (title: string) => {
      const next = title.replace(/\s+/g, " ").trim().slice(0, 140);
      const cur = editRef.current;
      if (!next || next === cur.title) return;
      commitEdit({ ...cur, title: next });
      const id = openIdRef.current;
      // Ещё не заведена — название уйдёт вместе с первым фрагментом.
      if (!id) return;
      const res = await patchProject(id, { title: next }, langRef.current);
      if (res.ok) {
        const p = projectRef.current;
        // Название — единственное, что поменялось: правку фрагментов не трогаем.
        if (p && p.id === res.data.id) commitProject({ ...p, title: res.data.title, updated_at: res.data.updated_at });
        setList((l) => ({ ...l, items: l.items.map((x) => (x.id === id ? { ...x, title: res.data.title } : x)) }));
        return;
      }
      showError(res.error);
    },
    [commitEdit, commitProject, showError],
  );

  /**
   * Готовую склейку менять нельзя — новая с теми же фрагментами, форматом и
   * заполнением. Фрагмента, которого больше нет (своё видео удалили, ролик
   * истёк), в новой не будет: из готовой его не убрать, и отказ сервера был бы
   * тупиком. Сервер нашёл ещё один пропавший — убираем и его и пробуем снова.
   */
  const copyProject = useCallback(async () => {
    const p = projectRef.current;
    if (!p) return;
    let items = itemRefs(p.items.filter((i) => i.available));
    let dropped = p.items.length - items.length;
    const notice = (): MergeBanner | null =>
      dropped > 0
        ? { text: { key: "merge.err.copy_dropped", ru: MERGE_ERROR_RU.copy_dropped, params: { n: dropped } } }
        : null;
    while (items.length > 0) {
      const res = await createProject({ aspect: p.aspect, fit: p.fit, items, title: defaultTitle() }, langRef.current);
      if (res.ok) {
        switchTo(res.data.id);
        applyServer(res.data, true);
        setError(notice());
        return;
      }
      const index = res.error.data.index;
      if (res.error.code !== "source_unavailable" || typeof index !== "number" || !(index >= 0 && index < items.length)) {
        showError(res.error);
        return;
      }
      items = removeAt(items, index);
      dropped += 1;
    }
    // Не осталось ни одного фрагмента — новая пустая склейка (пустые черновики сервер не заводит).
    await flush();
    switchTo(null);
    setOpening(false);
    resetToNew();
    setError(notice());
  }, [applyServer, defaultTitle, flush, resetToNew, showError, switchTo]);

  /* ---------- правка фрагментов ---------- */

  const editable = isEditable(project?.status ?? null);

  const change = useCallback(
    (next: EditState) => {
      const p = projectRef.current;
      if (p && !isEditable(p.status)) return;
      commitEdit(next);
      setError(null);
      // Новая правка — новый счёт повторов: прежние неудачи к ней не относятся.
      retryCount.current = 0;
      scheduleSave();
    },
    [commitEdit, scheduleSave],
  );

  /** «+ Добавить» — в конец склейки, «В начало» — первым фрагментом. */
  const addSource = useCallback(
    (card: MergeSourceCard, place: AddPlace = "end"): boolean => {
      const cur = editRef.current;
      if (addRefusal(cur.items, card, limits, uploadLimits.max_per_project)) return false;
      change({ ...cur, items: insertItem(cur.items, { ...cardToItem(card), key: makeKey() }, place) });
      return true;
    },
    [change, limits, makeKey, uploadLimits.max_per_project],
  );

  /* ---------- свои видео ---------- */

  /**
   * Загрузить своё видео в «Мои файлы»: сначала то, что видно на месте
   * (размер, расширение, место, длина и кадр), потом файл — с прогрессом и
   * отменой. В склейку само не добавляется: человек выбирает «В начало» или
   * «В конец» на карточке. Вернёт карточку или null (отказ, отмена).
   */
  const uploadFile = useCallback(
    async (file: File): Promise<MergeUploadCard | null> => {
      if (uploadAbort.current) return null;
      const limitsNow = uploadLimitsRef.current;
      setUploadError(null);
      setRetryFile(null);
      const refusal = precheckFile(file, limitsNow, uploadUsageRef.current);
      if (refusal) {
        setUploadError(precheckText(refusal));
        return null;
      }
      const ctrl = new AbortController();
      uploadAbort.current = ctrl;
      const name = file.name || t("merge.upload.fallbackName", { defaultValue: "Видео" });
      setUpload({ name, phase: "checking", pct: 0 });
      try {
        const bad = precheckMedia(await probeVideoFile(file), limitsNow);
        if (ctrl.signal.aborted) return null;
        if (bad) {
          setUploadError(precheckText(bad));
          return null;
        }
        const res = await uploadVideo(file, {
          filename: uploadName(file, limitsNow) ?? undefined,
          lang: langRef.current,
          signal: ctrl.signal,
          onProgress: (pct, phase) => {
            if (!ctrl.signal.aborted) setUpload({ name, phase, pct });
          },
        });
        if (!res.ok) {
          if (isAborted(res.error)) return null;
          setUploadError(uploadErrorText(res.error));
          // Связь, сбой, лимит — тот же файл можно отправить ещё раз, не выбирая 90 МБ из галереи заново.
          if (retryableUpload(uploadErrorCode(res.error))) setRetryFile(file);
          // Место кончилось раньше, чем думал экран (загрузка из другой вкладки) — сверяемся.
          if (res.error.code === "upload_quota") void loadUploads();
          return null;
        }
        const card = res.data;
        setSources((s) => ({
          ...s,
          upload: { ...s.upload, items: [card, ...s.upload.items.filter((c) => c.id !== card.id)], loaded: true, failed: false },
        }));
        setUploadUsage((u) => (u ? { ...u, files: u.files + 1, bytes: u.bytes + (card.size_bytes || 0) } : u));
        return card;
      } finally {
        // Отменённую уже убрал cancelUpload — следующая загрузка могла начаться, её не трогаем.
        if (uploadAbort.current === ctrl) {
          uploadAbort.current = null;
          setUpload(null);
        }
      }
    },
    [loadUploads, t],
  );

  /** Отмена — пока файл читается или идёт; когда байты ушли, сервер его всё равно примет. */
  const cancelUpload = useCallback(() => {
    const ctrl = uploadAbort.current;
    if (!ctrl) return;
    uploadAbort.current = null;
    ctrl.abort();
    setUpload(null);
  }, []);

  // Ушли со страницы посреди загрузки — запрос не бросаем висеть.
  useEffect(() => () => uploadAbort.current?.abort(), []);

  /**
   * Удалить своё видео. В открытом черновике его строки становятся
   * «недоступно» — запуск погаснет с причиной. Отказ (идёт его склейка, нет
   * связи) — на самой карточке: зона загрузки на телефоне далеко вверху.
   */
  const removeUpload = useCallback(
    async (card: MergeSourceCard): Promise<boolean> => {
      setDeleteError((e) => (e && e.id === card.id ? null : e));
      setDeletingUploads((ids) => (ids.includes(card.id) ? ids : [...ids, card.id]));
      const res = await deleteUploadApi(card.id);
      setDeletingUploads((ids) => ids.filter((id) => id !== card.id));
      if (!res.ok && res.error.code !== "upload_not_found") {
        setDeleteError({ id: card.id, text: uploadErrorText(res.error) });
        return false;
      }
      // Место освободилось — прежний отказ «место занято» больше не про сейчас.
      setUploadError((e) => (e && e.key === "merge.err.upload_quota" ? null : e));
      setSources((s) => ({ ...s, upload: { ...s.upload, items: s.upload.items.filter((c) => c.id !== card.id) } }));
      setUploadUsage((u) =>
        u ? { ...u, files: Math.max(0, u.files - 1), bytes: Math.max(0, u.bytes - (card.size_bytes || 0)) } : u,
      );
      const p = projectRef.current;
      const cur = editRef.current;
      if ((!p || isEditable(p.status)) && cur.items.some((i) => i.type === "upload" && i.id === card.id)) {
        commitEdit({
          ...cur,
          items: cur.items.map((i) => (i.type === "upload" && i.id === card.id ? { ...i, available: false, url: null } : i)),
        });
      }
      return true;
    },
    [commitEdit],
  );

  const removeItem = useCallback(
    (index: number) => {
      const cur = editRef.current;
      change({ ...cur, items: removeAt(cur.items, index) });
    },
    [change],
  );

  const moveItem = useCallback(
    (from: number, to: number) => {
      const cur = editRef.current;
      const items = moveInList(cur.items, from, to);
      if (items !== cur.items) change({ ...cur, items });
    },
    [change],
  );

  const setAspect = useCallback(
    (aspect: MergeAspect) => {
      const cur = editRef.current;
      if (cur.aspect === aspect) return;
      writePrefs({ aspect });
      change({ ...cur, aspect });
    },
    [change],
  );

  const setFit = useCallback(
    (fit: MergeFit) => {
      const cur = editRef.current;
      if (cur.fit === fit) return;
      writePrefs({ fit });
      change({ ...cur, fit });
    },
    [change],
  );

  /* ---------- запуск ---------- */

  // Идёт другая склейка — запуск этой получил бы отказ busy: причина видна у кнопки ещё до подтверждения.
  const otherRunning = list.activeId && list.activeId !== openId ? list.activeId : null;
  const maxUploads = uploadLimits.max_per_project;
  const block = useMemo<LocalBlock | null>(() => {
    if (!editable) return null;
    return renderBlock(edit.items, limits, maxUploads) ?? (otherRunning ? { code: "busy" } : null);
  }, [editable, edit.items, limits, maxUploads, otherRunning]);
  const total = totalDuration(edit.items);
  const freeCredits = balance ? balance.available : null;
  const short = price > 0 && freeCredits != null && freeCredits < price ? price - freeCredits : 0;

  /** «Склеить»: не хватает кредитов — сразу пополнение, иначе — подтверждение с ценой. */
  const requestRun = useCallback(() => {
    if (runningRef.current || block) return;
    if (short > 0) {
      setPaywall({ reason: "insufficient_balance", balanceTokens: freeCredits ?? 0, requiredEstimate: price });
      return;
    }
    setConfirm(true);
  }, [block, freeCredits, price, short]);

  const cancelRun = useCallback(() => setConfirm(false), []);

  const run = useCallback(async () => {
    setConfirm(false);
    if (runningRef.current) return;
    runningRef.current = true;
    setRunning(true);
    setError(null);
    try {
      // Склейка ещё не заведена — заводим; идущее сохранение дожидаемся: иначе
      // его PATCH пришёл бы уже после запуска и получил отказ.
      window.clearTimeout(saveTimer.current);
      pendingRef.current = false;
      await saveChain.current;
      if (!openIdRef.current && !(await flush())) return;
      const id = openIdRef.current;
      if (!id) return;
      const epoch = epochRef.current;
      const cur = editRef.current;
      // Фрагменты, формат и заполнение — тем же запросом: запускается ровно то, что на экране.
      const res = await renderProject(
        id,
        { price, aspect: cur.aspect, fit: cur.fit, items: itemRefs(cur.items) },
        langRef.current,
      );
      if (epoch !== epochRef.current) return;
      if (res.ok) {
        pollStart.current = { id, at: Date.now() };
        applyServer(res.data, true);
        applyBalance(res.data.balance);
        setList((l) => ({ ...l, activeId: id }));
        return;
      }
      const err = res.error;
      const pw = paywallContext(err);
      if (pw) {
        setPaywall(pw);
        void refreshConfig();
        return;
      }
      if (err.code === "price_changed" && typeof err.data.credits === "number") setPrice(err.data.credits);
      if (err.code === "busy") {
        const active = typeof err.data.active_id === "string" && isUid(err.data.active_id) ? err.data.active_id : undefined;
        showError(err, active && active !== id ? active : undefined);
        void loadList(1);
        return;
      }
      if (err.code === "already_ready" || err.code === "render_in_progress") {
        const fresh = await getProject(id, langRef.current);
        if (fresh.ok && epoch === epochRef.current) applyServer(fresh.data, true);
      }
      if (err.code === "source_unavailable" || err.code === "source_unreadable") {
        const index = typeof err.data.index === "number" ? err.data.index : -1;
        const now = editRef.current;
        if (index >= 0 && index < now.items.length) {
          commitEdit({ ...now, items: now.items.map((it, i) => (i === index ? { ...it, available: false } : it)) });
        }
      }
      showError(err);
    } finally {
      runningRef.current = false;
      setRunning(false);
      // Отказ запуска откатывает и правку из того же запроса — она уйдёт обычным сохранением.
      const p = projectRef.current;
      const now = editRef.current;
      if (openIdRef.current && (!p || isEditable(p.status)) && signature(now.items, now.aspect, now.fit) !== savedSigRef.current) {
        scheduleSave();
      }
    }
  }, [applyBalance, applyServer, commitEdit, flush, loadList, price, refreshConfig, scheduleSave, showError]);

  /* ---------- опрос идущей склейки ---------- */

  const activeId = project && isActive(project.status) ? project.id : null;
  const activeStatus = project?.status ?? null;

  useEffect(() => {
    if (!activeId) return;
    let alive = true;
    let timer = 0;
    if (pollStart.current?.id !== activeId) pollStart.current = { id: activeId, at: Date.now() };
    const startedAt = pollStart.current.at;
    const next = () => {
      const slow = Date.now() - startedAt > POLL_SLOW_AFTER_MS;
      timer = window.setTimeout(tick, slow ? POLL_SLOW_MS : POLL_MS);
    };
    const tick = async () => {
      // Вкладка скрыта — не опрашиваем: вернётся — продолжим.
      if (document.visibilityState === "hidden") {
        next();
        return;
      }
      const res = await getProject(activeId, langRef.current);
      if (!alive || openIdRef.current !== activeId) return;
      if (res.ok) {
        const done = !isActive(res.data.status);
        applyServer(res.data, done);
        if (done) {
          setList((l) => ({ ...l, activeId: null }));
          void loadList(1);
          void refreshConfig();
          return;
        }
      } else if (res.error.code === "project_not_found") {
        return;
      }
      next();
    };
    next();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [activeId, activeStatus, applyServer, loadList, refreshConfig]);

  // Идёт другая склейка (открыта не она) — точку в списке снимаем, когда она кончится.
  const otherActive = list.activeId && list.activeId !== activeId ? list.activeId : null;
  useEffect(() => {
    if (!otherActive) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "hidden") void loadList(1);
    }, LIST_POLL_MS);
    return () => window.clearInterval(timer);
  }, [otherActive, loadList]);

  /* ---------- первый показ ---------- */

  /** Вход, цена, «Мои склейки», ролики для выбора и какую склейку открыть. Один раз. */
  const boot = useEffectEvent(async (alive: () => boolean) => {
    const ok = await checkAuth();
    if (!alive()) return;
    // Цена видна и гостю: на карточке входа написано, сколько стоит склейка.
    void refreshConfig();
    setAuthed(ok);
    if (!ok) {
      const { pathname, search } = window.location;
      if (pathname === MERGE_PATH && search) setReturnPath(`${pathname}${search}`);
      setBooting(false);
      return;
    }

    const query = new URLSearchParams(window.location.search);
    const wanted = query.get("id");
    const add: ItemRef[] = parseAddParam(query.get("add"));
    // ?add= — одноразовый: перезагрузка не заводит вторую такую же склейку.
    if (query.has("add")) replaceUrl(isUid(wanted) ? wanted : null);

    const prefs = readPrefs();
    commitEdit({ items: [], aspect: prefs.aspect, fit: prefs.fit, title: "" });
    const firstTab = add.some((a) => a.type === "cartoon_movie" || a.type === "cartoon_scene") ? "cartoon" : prefs.tab;
    if (firstTab) setTabState(firstTab);

    const tabCounts = Promise.all(TABS.map((x) => loadSources(x)));
    const listed = await loadList(1);
    if (!alive()) return;

    let target: string | null = null;
    if (add.length) {
      // «Открыть в склейке» из мультстудии: склейка сразу с этим мультфильмом.
      const res = await createProject(
        {
          aspect: prefs.aspect,
          fit: prefs.fit,
          items: add,
          title: defaultTitle(),
        },
        langRef.current,
      );
      if (!alive()) return;
      if (res.ok) {
        commitOpenId(res.data.id);
        replaceUrl(res.data.id);
        remember(res.data.id);
        applyServer(res.data, true);
      } else {
        showError(res.error);
      }
    } else if (isUid(wanted)) {
      target = wanted;
    } else if (listed?.active_id) {
      // Идёт склейка — открываем её: человек вернулся посмотреть, готово ли.
      target = listed.active_id;
    } else {
      const last = recall();
      if (last && listed?.results.some((x) => x.id === last)) target = last;
    }

    if (target) {
      await open(target);
      if (!alive()) return;
    }
    setBooting(false);

    // Первая вкладка — запомненная, иначе первая, где есть ролики.
    if (!firstTab) {
      const found = await tabCounts;
      if (!alive()) return;
      const nonEmpty = TABS.find((_, i) => found[i] > 0);
      if (nonEmpty) setTabState(nonEmpty);
    }
  });

  useEffect(() => {
    let alive = true;
    void boot(() => alive);
    return () => {
      alive = false;
    };
  }, []);

  const setTab = useCallback(
    (next: MergeTab) => {
      setTabState(next);
      writePrefs({ tab: next });
      if (!sources[next].loaded && !sources[next].loading) void loadSources(next);
    },
    [loadSources, sources],
  );

  /** Сколько раз ролик уже стоит в склейке — значок на карточке выбора. */
  const counts = new Map<string, number>();
  for (const it of edit.items) counts.set(`${it.type}:${it.id}`, (counts.get(`${it.type}:${it.id}`) ?? 0) + 1);

  return {
    authed,
    returnPath,
    loading: authed === null || booting,
    config,
    price,
    balance,
    balanceFailed,
    short,
    limits,
    list,
    project,
    openId,
    opening,
    edit,
    editable,
    block,
    total,
    counts,
    saving,
    unsaved,
    running,
    error,
    paywall,
    topup,
    confirm,
    sources,
    tab,
    uploadLimits,
    uploadUsage,
    upload,
    uploadError,
    retryFile,
    deletingUploads,
    deleteError,
    actions: {
      newMerge: () => void newMerge(),
      open: (id: string) => void open(id),
      remove,
      rename: (title: string) => void rename(title),
      copyProject: () => void copyProject(),
      addSource,
      removeItem,
      moveItem,
      setAspect,
      setFit,
      requestRun,
      cancelRun,
      run: () => void run(),
      retrySave,
      setTab,
      loadMoreSources: (which: MergeTab) => void loadSources(which, sources[which].page + 1),
      reloadSources: (which: MergeTab) => void loadSources(which, 1),
      uploadFile,
      cancelUpload,
      removeUpload,
      dismissUploadError: () => {
        setUploadError(null);
        setRetryFile(null);
      },
      dismissDeleteError: () => setDeleteError(null),
      loadMoreProjects: () => void loadList(list.page + 1),
      reloadProjects: () => void loadList(1),
      dismissError: () => setError(null),
      closePaywall: () => setPaywall(null),
      openTopup: () => {
        setPaywall(null);
        setTopup(true);
      },
      closeTopup: () => {
        setTopup(false);
        void refreshConfig();
      },
    },
  };
}

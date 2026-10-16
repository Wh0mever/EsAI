"use client";

import { useTranslation } from "react-i18next";
import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { fetchData } from "@/tools/fetchData";
import { trackFunnel } from "@/tools/funnel";
import { getOrCreateDeviceKey } from "@/tools/deviceKey";
import {
  MAX_DRAFT_SCENES,
  clearDraft,
  draftDock,
  emptyDraft,
  importBody,
  loadDraft,
  newSceneKey,
  recallProject,
  rememberProject,
  saveDraft,
  type DraftScene,
  type StudioDraft,
} from "@/lib/studioDraft";
import { apiLang } from "@/lib/apiLang";
import { prefersReducedMotion } from "@/components/vstudio/ui/useAutoplayAllowed";
import type { StudioCharacter } from "./CharacterPicker";
import type { SceneDurationChoice, SceneNote, StudioScene } from "./SceneTimeline";
import type { AudioConfig } from "./SceneAudioDialog";
import type { VoicePlan } from "./VoiceAllDialog";
import {
  DEFAULT_ASPECT,
  DOCK_RU,
  adjustedNotices,
  alreadyShot,
  cardEstimate,
  clampDuration,
  clampSceneDurations,
  completeDock,
  configLabel,
  displayDefaults,
  dockBody,
  dockPatch,
  durationChoices,
  explicitDefaults,
  findModel,
  guestRowPrice,
  modelLabel,
  presetsQuery,
  priceChanged,
  quoteBody,
  refusalText,
  reshootDurationQuestion,
  retryBody,
  sameDock,
  sanitizeDock,
  serialQueue,
  settlePriceNotes,
  switchModel,
  timelineTotal,
  withDuration,
  withResolution,
  type CartoonModel,
  type CartoonModels,
  type DockField,
  type DockNotice,
  type DockSettings,
  type DockTextKey,
  type SceneConfig,
} from "./dockLogic";
import {
  PAGE_SIZE,
  WORKING,
  type ApiRefusal,
  type Audience,
  type AuthReason,
  type CardPrice,
  type Category,
  type DockPrimary,
  type DockValue,
  type Preset,
  type Project,
  type SceneHandlers,
  type Shortfall,
  type TimelineCharacter,
} from "./cartoonTypes";

/**
 * useCartoonStudio — всё состояние студии мультфильмов: витрина, герои,
 * мультфильм и его лента, док, окна. Страница (CartoonStudio) только
 * раскладывает это по компонентам.
 *
 * Пока хоть одна сцена считается, состояние проекта опрашивается раз в 4
 * секунды. Опрос останавливается, как только считать нечего — иначе вкладка
 * будет молотить запросы часами, пока человек любуется результатом.
 */

/** Что сервер подогнал в ответе мультфильма (adjusted) — сообщениями дока. */
function serverNotices(p: Project): DockNotice[] {
  const order = [...p.scenes].sort((a, b) => a.order - b.order).map((s) => s.id);
  return adjustedNotices(p.adjusted, p.effective?.model_name ?? "", (id) => {
    const at = order.indexOf(id);
    return at < 0 ? null : at;
  });
}

/** Своя длительность сцены черновика: null — убрать (по умолчанию). */
function withSceneDuration(s: DraftScene, value: number | null): DraftScene {
  const next: DraftScene = { ...s };
  if (value == null) delete next.duration;
  else next.duration = value;
  return next;
}

/** Прокрутка к шагу: плавная, если человек не просил «меньше движения». */
function scrollBehavior(): ScrollBehavior {
  return prefersReducedMotion() ? "auto" : "smooth";
}

/**
 * Сцену добавили «+ В ленту» — показываем её саму: она последняя, а лента на
 * телефоне листается вбок, с 768 px — сетка в несколько рядов, и прокрутка к
 * секции оставляла новую карточку за краем. Пауза — чтобы карточка успела встать.
 */
function revealLastScene(section: RefObject<HTMLElement | null>) {
  window.setTimeout(() => {
    const root = section.current;
    const last = root?.querySelector<HTMLElement>("ol > li:last-child");
    (last ?? root)?.scrollIntoView({ behavior: scrollBehavior(), block: "nearest", inline: "nearest" });
  }, 60);
}

export type CartoonStudioModel = {
  loading: boolean;
  authed: boolean;
  balance: number | null;
  /** Баланс не пришёл (сбой профиля): в шапке «—», а не вечное «…». */
  balanceFailed: boolean;
  error: string;
  aspect: string;
  project: Project | null;
  /** Свои мультфильмы для переключателя (пустые черновики — только открытый). */
  movies: Project[];
  heroes: {
    /** Герои под выбранную аудиторию; свои — всегда. */
    list: StudioCharacter[];
    /** Герои, уже поставленные в сцены ленты. */
    cast: StudioCharacter[];
    selected: StudioCharacter | null;
    needHero: boolean;
    audience: Audience;
    showAudience: boolean;
  };
  library: {
    /** Карточки нынешней «горсти», уже отфильтрованные. */
    presets: Preset[];
    restCount: number;
    /** Разделы, в которых есть сцены для выбранной аудитории. */
    categories: Category[];
    hasPopular: boolean;
    hasPicks: boolean;
    /** "" — все, "__popular", "__pick" или slug раздела. */
    activeCat: string;
    /** Кадры выбранного героя в сценах (по id сцены библиотеки). */
    frames: Record<number, string>;
    /** Ролики пар «выбранный герой + сцена» (по id сцены библиотеки). */
    heroVideos: Record<number, string>;
    /** Какая сцена добавляется; -1 — своя сцена. */
    adding: number | null;
    tryingOn: number | null;
    customText: string;
    cardPrice: (p: Preset) => CardPrice;
  };
  timeline: {
    show: boolean;
    scenes: StudioScene[];
    characters: TimelineCharacter[];
    busyIds: Set<number>;
    repricing: boolean;
    framingId: number | null;
    frameCredits: number | undefined;
    /** Сообщения у строк; у гостя — нет (его отказы вверху страницы). */
    notes: Record<number, SceneNote> | undefined;
    readyCount: number;
    drafts: number;
    working: boolean;
    voicingNow: boolean;
    total: { credits: number | null; count: number };
    audioEnabled: boolean;
    planning: boolean;
    assembling: boolean;
    handlers: SceneHandlers;
  };
  result: { video: string; shareUrl: string };
  dock: {
    models: CartoonModel[] | null;
    modelsError: boolean;
    value: DockValue;
    notices: DockNotice[];
    warning: DockTextKey | null;
    total: { credits: number | null; count: number };
    hasShot: boolean;
    frameCredits: number | null | undefined;
    saving: boolean;
    error: string | null;
    primary: DockPrimary | null;
  };
  dialogs: {
    shortfall: Shortfall | null;
    authFor: AuthReason | null;
    audioScene: StudioScene | null;
    audioConfig: AudioConfig | null;
    voicePlan: VoicePlan | null;
    audioCharacters: { id: number; name: string }[];
  };
  refs: {
    heroes: RefObject<HTMLDivElement | null>;
    timeline: RefObject<HTMLDivElement | null>;
  };
  actions: {
    clearError: () => void;
    pickAudience: (a: Audience) => void;
    pickHero: (c: StudioCharacter) => void;
    heroCreated: (c: StudioCharacter) => void;
    heroDeleted: (id: number) => void;
    pickCategory: (slug: string) => void;
    showMore: () => void;
    addScene: (p: Preset) => Promise<void>;
    tryOnScene: (p: Preset) => Promise<void>;
    setCustomText: (text: string) => void;
    addCustomScene: () => Promise<void>;
    openProject: (id: number) => Promise<void>;
    startNewMovie: () => void;
    renameMovie: (value: string) => Promise<void>;
    assemble: () => Promise<void>;
    planVoiceAll: () => Promise<void>;
    guestRender: (from: "scene" | "cta") => void;
    retryModels: () => void;
    pickDockModel: (id: string) => void;
    pickDockResolution: (value: string) => void;
    pickDockDuration: (value: number) => void;
    pickAspect: (value: string) => Promise<void>;
    dismissNotices: () => void;
    dismissDockError: () => void;
    openAuth: (reason: AuthReason) => void;
    closeAuth: () => void;
    openPaywall: (v: Shortfall) => void;
    closePaywall: () => void;
    closeAudio: () => void;
    audioChanged: () => void;
    closeVoicePlan: () => void;
    voiceStarted: () => void;
    scrollToHeroes: () => void;
    scrollToTimeline: () => void;
  };
};

export function useCartoonStudio(): CartoonStudioModel {
  const { t, i18n } = useTranslation("common");
  const [presets, setPresets] = useState<Preset[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  // Подборки наверху библиотеки: «Популярное» приходит с сервера по
  // реальным добавлениям, «Выбор EsAI» помечен у самих сцен в админке.
  const [popular, setPopular] = useState<string[]>([]);
  const [activeCat, setActiveCat] = useState("");
  // Показываем по горсти карточек, остальное — по кнопке. У многих в Кыргызстане
  // медленный мобильный интернет, а сразу полторы сотни превью — это и запросы,
  // и память телефона на ровном месте.
  const [shown, setShown] = useState(PAGE_SIZE);
  // Для кого снимаем. Разделов девятнадцать, героев больше двух десятков, и
  // взрослому сюжету нужен взрослый герой — поэтому один переключатель наверху
  // сужает сразу оба списка.
  const [audience, setAudience] = useState<Audience>("all");
  // Сцены видны сразу, без выбора героя (просьба клиента), поэтому нажатие
  // «В ленту» без героя не ошибка, а подсказка с прокруткой к первому шагу.
  const [needHero, setNeedHero] = useState(false);
  const [characters, setCharacters] = useState<StudioCharacter[]>([]);
  const [character, setCharacter] = useState<StudioCharacter | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  // Все мультфильмы пользователя. Нужны не для красоты: как только человек
  // начинает новый, старый перестаёт быть «последним» и без списка исчезает
  // из интерфейса вместе с оплаченными сценами.
  const [projects, setProjects] = useState<Project[]>([]);
  const [balance, setBalance] = useState<number | null>(null);
  const [balanceFailed, setBalanceFailed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState<number | null>(null);
  const [busyIds, setBusyIds] = useState<Set<number>>(new Set());
  const [assembling, setAssembling] = useState(false);
  // Не хватило кредитов — не ошибка, а точка покупки: человек уже выбрал героя
  // и сцену, и это самый дорогой момент, чтобы упереться в сухую красную строку.
  const [shortfall, setShortfall] = useState<Shortfall | null>(null);
  // Звук сцены: какая сцена открыта в окне звука и включена ли озвучка вообще.
  const [audioScene, setAudioScene] = useState<StudioScene | null>(null);
  const [audioConfig, setAudioConfig] = useState<AudioConfig | null>(null);
  // «Озвучить весь мультфильм»: сперва план с ценой, потом очередь.
  const [voicePlan, setVoicePlan] = useState<VoicePlan | null>(null);
  const [planning, setPlanning] = useState(false);
  const [authFor, setAuthFor] = useState<AuthReason | null>(null);
  const [authed, setAuthed] = useState(true);
  // Лента гостя. Клиент: без регистрации человек выбирает героя, набирает
  // сцены и видит результат — а войти просим, когда ему уже есть что терять.
  // Живёт в браузере и после входа переезжает в настоящий проект.
  const [draft, setDraft] = useState<StudioDraft | null>(null);
  const pollRef = useRef<number | null>(null);
  const heroRef = useRef<HTMLDivElement | null>(null);
  const timelineRef = useRef<HTMLDivElement | null>(null);
  // Примерка героя: кадр «этот герой в этой сцене». Готовые пары приходят с
  // сервера бесплатно и подставляются сами — клиент просил, чтобы выбранный
  // герой сразу был виден в примерах. Недостающие рисуются по кнопке.
  // Кадры храним по героям: в ленте у каждой сцены может быть свой герой, и
  // карточке нужен кадр именно её персонажа.
  const [framesByChar, setFramesByChar] = useState<Record<number, Record<number, string>>>({});
  // Ролики пар «герой + сцена», уже снятые кем-то раньше: движущееся превью
  // сцены именно с этим героем, без новой генерации (просьба клиента).
  const [videosByChar, setVideosByChar] = useState<Record<number, Record<number, string>>>({});
  const fetchedChars = useRef<Set<number>>(new Set());
  const [tryingOn, setTryingOn] = useState<number | null>(null);
  // Своя сцена: вместо готового пресета человек пишет, что делает герой
  // (клиент: «быстро выбрать готовую сцену или самому описать, что хочешь»).
  const [customText, setCustomText] = useState("");
  const [framingId, setFramingId] = useState<number | null>(null);
  // Ссылка «поделиться» привязана к ролику, для которого сделана: после
  // пересборки мультфильма прежняя вела бы на старый ролик.
  const [share, setShare] = useState<{ video: string; url: string } | null>(null);
  const [sharing, setSharing] = useState(false);
  // Какой мультфильм открыт — синхронно, без ожидания перерисовки. По нему
  // отбрасываются ответы опроса старого проекта: иначе запрос, ушедший до
  // переключения, возвращал на экран прежний мультфильм.
  const currentIdRef = useRef<number | null>(null);
  const showProject = useCallback((p: Project | null) => {
    currentIdRef.current = p?.id ?? null;
    setProject(p);
  }, []);
  // Формат, под который запрошены кадры героев: ответ, пришедший для прежнего
  // формата, выкидываем — иначе в вертикальную ленту встали бы горизонтальные кадры.
  const aspectRef = useRef<string | null>(null);
  // Цены сцен витрины считаются под формат и настройки дока (в режиме цен
  // «наценка» квадрат дешевле 16:9, Mini дешевле 2.0): под что посчитан список.
  const [pricedKey, setPricedKey] = useState<string | null>(null);
  // Док: модели с ценами сцен, сообщения «подогнали значение» и выбор, который
  // ещё едет на сервер (до ответа док показывает его, а не прежний).
  const [models, setModels] = useState<CartoonModels | null>(null);
  const [modelsError, setModelsError] = useState(false);
  const [notices, setNotices] = useState<DockNotice[]>([]);
  const [dockPending, setDockPending] = useState<{ projectId: number; settings: DockSettings } | null>(null);
  const dockSeq = useRef(0);
  // Правки мультфильма (док, формат) уходят строго по одной: ответы приходят в
  // том же порядке, последний — это и есть итог на сервере, ни один не теряется.
  // Пока что-то едет, кнопки дока заняты (savingProject — id мультфильма).
  const [enqueuePatch] = useState(serialQueue);
  const inFlight = useRef(0);
  // Сколько ответов правок уже легло на экран: опрос, ушедший до правки, их не затирает.
  const patchEpoch = useRef(0);
  const [savingProject, setSavingProject] = useState<number | null>(null);
  // Отказ на правку дока или формата — показывается в самом доке.
  const [dockError, setDockError] = useState("");
  // Отказы и подсказки у строк ленты (по id сцены): «цена изменилась», «уже
  // снята», «не сохранилось» — там, где человек нажал, а не вверху страницы.
  const [sceneNotes, setSceneNotes] = useState<Record<number, SceneNote>>({});
  const dismissNotices = useCallback(() => setNotices([]), []);
  const dt = (key: DockTextKey, params?: Record<string, string | number>) =>
    t(key, { defaultValue: DOCK_RU[key], ...(params || {}) });
  /** «Seedance Mini · 480p · 5 с». */
  const cfgText = (c: SceneConfig) =>
    [configLabel(c), dt("studio_ui.dock_seconds", { n: c.duration })].filter(Boolean).join(" · ");
  /** «Цена изменилась: теперь N кр…» на языке человека; без числа — текст сервера. */
  const priceChangedText = (changed: { credits: number | null }, d: ApiRefusal, retry = false) =>
    changed.credits != null
      ? dt(retry ? "studio_ui.scene_price_changed_retry" : "studio_ui.scene_price_changed", { credits: changed.credits })
      : d?.detail || dt("studio_ui.scene_save_failed");
  /** Отказ сервера на языке человека: по-русски — его текст, иначе — по error_code.
   *  keepDetail — код незнакомый: текст сервера (почему отказали), а не общий. */
  const refusalMessage = (body: unknown, fallback: DockTextKey, keepDetail = false) => {
    const r = refusalText(i18n.language, body, fallback, keepDetail);
    return r.detail ?? dt(r.key);
  };
  /** Сообщение у строки ленты; null — убрать. price — у «Цена изменилась»: N из текста. */
  const noteScene = (id: number, text: string | null, tone: SceneNote["tone"] = "error", price?: number | null) =>
    setSceneNotes((prev) => {
      const next = { ...prev };
      if (text) next[id] = price === undefined ? { text, tone } : { text, tone, price };
      else delete next[id];
      return next;
    });
  /** Цены строк перечитаны: «Цена изменилась: теперь N кр» у строк с другой ценой уходит.
   *  saved — это ответ сохранённой правки дока или формата. */
  const settleNotes = useCallback(
    (fresh: Project, saved: boolean) => setSceneNotes((prev) => settlePriceNotes(prev, fresh.scenes, saved)),
    []
  );
  /** PATCH мультфильма в общую очередь; пока что-то едет, док занят. fetchData не
   *  бросает (сбой сети — ok: false), поэтому счётчик всегда возвращается к нулю.
   *  dock: false — правка не из дока (название): в очереди, но кнопки дока не заняты. */
  const patchProject = async (id: number, body: Record<string, unknown>, dock = true) => {
    if (dock) {
      inFlight.current += 1;
      setSavingProject(id);
    }
    const res = await enqueuePatch(() => fetchData<Project>(`cartoon/projects/${id}/`, "PATCH", body, true));
    if (dock) {
      inFlight.current -= 1;
      if (!inFlight.current) setSavingProject(null);
    }
    if (res.ok) patchEpoch.current += 1;
    return res;
  };

  // Формат мультфильма. Клиент: 9:16 для Reels и TikTok, 16:9 для YouTube,
  // 1:1 для ленты — и один на всю серию, чтобы сцены склеились ровно.
  const aspect = project?.aspect_ratio || draft?.aspect_ratio || "16:9";

  /** Сменить формат: у проекта — на сервере (в общей очереди правок), у гостя — в черновике. */
  const setAspect = async (value: string) => {
    if (value === aspect) return;
    if (!authed || !project) {
      updateDraft((d) => ({ ...d, aspect_ratio: value }));
      return;
    }
    const id = project.id;
    setDockError("");
    const res = await patchProject(id, { aspect_ratio: value });
    if (res.ok && res.data) {
      const fresh = res.data;
      if (currentIdRef.current === fresh.id) {
        showProject(fresh);
        settleNotes(fresh, true);
      }
      setProjects((prev) => prev.map((x) => (x.id === fresh.id ? fresh : x)));
      return;
    }
    if (currentIdRef.current === id) setDockError(refusalMessage(res.data, "studio_ui.dock_save_failed"));
  };

  // Готовые кадры героев. Их отдают бесплатно, поэтому подставляем сразу и
  // молча: для человека это выглядит так, будто сцены сами перерисовались под
  // его персонажа. Спрашиваем по каждому герою один раз — и для выбранного, и
  // для тех, кого поставили на отдельные сцены ленты.
  const wantedChars = useMemo(() => {
    const ids = new Set<number>();
    if (character) ids.add(character.id);
    for (const s of draft?.scenes || []) if (s.character_id) ids.add(s.character_id);
    for (const s of project?.scenes || []) if (s.character?.id) ids.add(s.character.id);
    return [...ids].sort((a, b) => a - b).join(",");
  }, [character, draft, project]);

  useEffect(() => {
    // Формат поменяли — прежние кадры были другого размера: чистим и тут же
    // запрашиваем заново. Раньше очистка жила в отдельном эффекте, срабатывала
    // после запроса и стирала превью героев насовсем.
    if (aspectRef.current !== aspect) {
      if (aspectRef.current !== null) {
        fetchedChars.current.clear();
        setFramesByChar({});
        setVideosByChar({});
      }
      aspectRef.current = aspect;
    }
    const wanted = aspect;
    const ids = wantedChars ? wantedChars.split(",").map(Number) : [];
    for (const id of ids) {
      if (fetchedChars.current.has(id)) continue;
      fetchedChars.current.add(id);
      void (async () => {
        const res = await fetchData<Record<string, { frame: string; video: string }>>(
          `cartoon/previews/?character_id=${id}&aspect_ratio=${encodeURIComponent(wanted)}`,
          "GET", null, true
        );
        // Пока шёл запрос, формат сменили: ответ относится к прежнему.
        if (aspectRef.current !== wanted) return;
        if (!res.ok || !res.data) {
          fetchedChars.current.delete(id);
          return;
        }
        const frames: Record<number, string> = {};
        const videos: Record<number, string> = {};
        for (const [pid, row] of Object.entries(res.data)) {
          if (row?.frame) frames[Number(pid)] = row.frame;
          if (row?.video) videos[Number(pid)] = row.video;
        }
        setFramesByChar((prev) => ({ ...prev, [id]: { ...frames, ...(prev[id] || {}) } }));
        setVideosByChar((prev) => ({ ...prev, [id]: { ...videos, ...(prev[id] || {}) } }));
      })();
    }
  }, [wantedChars, aspect]);

  const tryOn: Record<number, string> = (character && framesByChar[character.id]) || {};
  const heroVideos: Record<number, string> = (character && videosByChar[character.id]) || {};

  /** Окно входа — и отметка в воронке: это главный шаг, который мы меряем. */
  const openAuth = (reason: AuthReason) => {
    setAuthFor(reason);
    trackFunnel("studio_auth_prompt", { reason });
  };

  /** Окно «не хватает кредитов» — точка покупки, её тоже считаем. */
  const openPaywall = (value: Shortfall) => {
    setShortfall(value);
    trackFunnel("studio_paywall", { kind: value.kind || "scene", required: value.required });
  };

  /** Нарисовать кадр этой сцены с выбранным героем. */
  const tryOnScene = async (preset: Preset) => {
    if (!character) {
      setNeedHero(true);
      heroRef.current?.scrollIntoView({ behavior: scrollBehavior(), block: "start" });
      return;
    }
    await tryOnPair(preset.id, character.id);
  };

  /** Примерка из ленты: герой — тот, что закреплён за сценой, а не выбранный сейчас. */
  const tryOnTimelineScene = async (scene: StudioScene) => {
    if (!scene.character) return;
    // У гостя заметок у строк нет (лента из черновика) — его отказ, как раньше, вверху.
    if (!authed) {
      await tryOnPair(scene.preset.id, scene.character.id);
      return;
    }
    noteScene(scene.id, null);
    await tryOnPair(scene.preset.id, scene.character.id, scene.id);
  };

  /** Кадр «этот герой в этой сцене». Потом он же пойдёт первым кадром съёмки.
   *  rowId — примеряли у строки ленты: отказ показываем у неё, а не вверху страницы. */
  const tryOnPair = async (presetId: number, heroId: number, rowId: number | null = null) => {
    const preset = { id: presetId };
    const wanted = aspect;
    trackFunnel("studio_tryon", { preset_id: preset.id, authed });
    setTryingOn(preset.id);
    // Гость шлёт запрос без токена: ответ «нужен вход» (403) иначе принимается
    // за истёкшую сессию и уводит со страницы. Ключ устройства — чтобы сервер
    // посчитал «одну бесплатную на устройство».
    const res = await fetchData<{ image: string; charged: number; free?: boolean }>(
      `cartoon/presets/${preset.id}/try-on/`, "POST",
      { character_id: heroId, aspect_ratio: aspect }, authed,
      { "X-Device-Key": getOrCreateDeviceKey() }
    );
    setTryingOn(null);
    if (res.ok && res.data?.image) {
      const image = res.data.image;
      // Кадр прежнего формата в новую ленту не ставим.
      if (aspectRef.current === wanted) {
        setFramesByChar((prev) => ({ ...prev, [heroId]: { ...(prev[heroId] || {}), [preset.id]: image } }));
      }
      if (res.data.charged) void loadBalance();
      return;
    }
    const d = res.data as ApiRefusal;
    if (d?.need_auth) {
      openAuth("tryon");
      return;
    }
    if (d?.required) {
      openPaywall({ required: Number(d.required), balance: Number(d.balance ?? 0), kind: "character" });
    } else if (rowId != null) {
      // С телефона блок ошибки вверху страницы не виден — отказ рядом с кнопкой.
      noteScene(rowId, refusalMessage(d, "studio_ui.err_tryon", true));
    } else {
      setError(refusalMessage(d, "studio_ui.err_tryon", true));
    }
  };

  /** Изменить ленту гостя и сразу сохранить её в браузере. */
  const updateDraft = useCallback(
    (change: (d: StudioDraft) => StudioDraft) => {
      setDraft((prev) => saveDraft(change(prev || emptyDraft(character?.id ?? null))));
    },
    [character]
  );

  const byAudience = (p: Preset) => audience === "all" || p.audience === audience;

  // Раздел показываем, только если в нём есть что смотреть при текущем выборе
  // аудитории — иначе человек ткнёт в «Спорт» и увидит пустоту.
  const visibleCategories = categories.filter((c) =>
    presets.some((p) => p.category === c.slug && byAudience(p))
  );

  const picks = presets.filter((p) => p.is_pick && byAudience(p));
  const popularPresets = popular
    .map((slug) => presets.find((p) => p.slug === slug))
    .filter((p): p is Preset => Boolean(p) && byAudience(p as Preset));

  // Свои персонажи показываются всегда: человек загрузил их сам, и прятать их
  // за чужим делением на «детское/взрослое» было бы странно.
  const visibleCharacters =
    audience === "all"
      ? characters
      : characters.filter((c) => c.is_mine || c.audience === audience);

  const allPresets =
    activeCat === "__pick"
      ? picks
      : activeCat === "__popular"
      ? popularPresets
      : activeCat
      ? presets.filter((p) => p.category === activeCat && byAudience(p))
      : presets.filter(byAudience);

  const visiblePresets = allPresets.slice(0, shown);
  const restCount = Math.max(0, allPresets.length - visiblePresets.length);

  const pickAudience = (next: Audience) => {
    // Список карточек сменился целиком — показ начинаем с первой горсти
    // (отметки видимости роликов сбрасывает сама библиотека сцен).
    setShown(PAGE_SIZE);
    setAudience(next);
    if (activeCat && !activeCat.startsWith("__") && next !== "all") {
      const still = presets.some((p) => p.category === activeCat && p.audience === next);
      if (!still) setActiveCat("");
    }
  };

  const markBusy = (id: number, on: boolean) =>
    setBusyIds((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  const loadBalance = useCallback(async () => {
    const res = await fetchData<{
      token_balance?: unknown;
      user?: { token_balance?: unknown };
      data?: { token_balance?: unknown };
    }>("users/profile/", "GET", null, true);
    // Профиль отдаёт баланс внутри user — без этого шапка навсегда показывала «…».
    const b = res?.data?.user?.token_balance ?? res?.data?.token_balance ?? res?.data?.data?.token_balance;
    const ok = res?.ok && b != null && Number.isFinite(Number(b));
    if (ok) setBalance(Number(b));
    setBalanceFailed(!ok);
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      // Язык нужен серверу: названия сцен и героев лежат в базе и переводятся
      // там же, поэтому витрина просит их сразу на нужном языке.
      const lang = apiLang(i18n.language);
      // Первый показ — по пресетам, как раньше: настройки дока станут известны
      // чуть позже (модели, мультфильм), и витрина перезапросится под них сама.
      const first = presetsQuery({ lang, aspect: DEFAULT_ASPECT });
      const [p, c, mine] = await Promise.all([
        fetchData<{ categories: Category[]; presets: Preset[]; popular: string[] }>(
          `cartoon/presets/?${first.query}`, "GET", null, true),
        fetchData<StudioCharacter[]>(`cartoon/characters/?lang=${lang}`, "GET", null, true),
        fetchData<Project[]>(`cartoon/projects/?lang=${lang}`, "GET", null, true),
      ]);
      if (!alive) return;
      if (p.ok && p.data) {
        setPresets(p.data.presets || []);
        setPricedKey(first.key);
        setCategories(p.data.categories || []);
        setPopular(p.data.popular || []);
      }
      const chars = c.ok && Array.isArray(c.data) ? c.data : [];
      setCharacters(chars);
      if (!p.ok) setError(t("studio_ui.err_load"));

      // Витрина открыта всем, а свои мультфильмы есть только у вошедших:
      // по ответу этого запроса и понимаем, гость перед нами или нет.
      setAuthed(mine.ok);
      // Первый шаг воронки. Неделю рекламы студия не отправляла его вовсе —
      // и о 700 посетителях в день мы узнавали из чужой статистики.
      trackFunnel("studio_view", { authed: mine.ok });

      if (!mine.ok) {
        // Гость: поднимаем его ленту, если он уже начинал собирать.
        const saved = loadDraft();
        if (saved) {
          setDraft(saved);
          const hero = chars.find((x) => x.id === saved.character_id);
          if (hero) setCharacter(hero);
        }
        setLoading(false);
        return;
      }

      // Продолжаем последний мультфильм, а не начинаем пустой: сцены стоят
      // денег, и терять их при перезагрузке страницы недопустимо.
      const mineList = mine.ok && Array.isArray(mine.data) ? mine.data : [];
      setProjects(mineList);

      // Только что вошёл, а в браузере лежит лента, собранная гостем: переносим
      // её в настоящий проект и открываем именно его (просьба клиента: «вернуть
      // пользователя именно в этот проект»).
      let imported: Project | null = null;
      const saved = loadDraft();
      if (saved?.scenes.length && saved.character_id) {
        // Сбой переноса не должен оставить студию на заглушке загрузки:
        // черновик останется в браузере, и перенос повторится при следующем
        // открытии (сервер по ключу черновика второго проекта не заведёт).
        try {
          // Сцены, реплики, формат и выбранные в доке настройки — одним запросом.
          const res = await fetchData<Project>("cartoon/projects/import/", "POST", importBody(saved), true);
          if (!alive) return;
          if (res.ok && res.data) {
            const fresh = res.data;
            imported = fresh;
            clearDraft();
            setProjects((prev) => [fresh, ...prev.filter((x) => x.id !== fresh.id)]);
            // Черновик устарел (модель выключили, длительность другая) — сервер
            // взял ближайшее: говорим об этом, а не меняем молча.
            const notes = serverNotices(fresh);
            if (notes.length) setNotices(notes);
          }
        } catch {
          // тихо: остаёмся на обычном открытии студии
        }
      } else if (saved && !saved.scenes.length) {
        // Гость выбрал в доке модель, качество или формат, но сцен ещё не набрал: этот
        // выбор не теряем — с ним заведётся первый мультфильм (ensureProject).
        setDraft(saved);
      } else if (saved) {
        clearDraft();
      }

      // Бот и Mini App открывают конкретный мультфильм: ?project=<id>. После
      // оплаты и входа возвращаемся к тому, что было открыто последним, — а
      // не к «какому-нибудь последнему с сценами».
      const wanted = Number(new URLSearchParams(window.location.search).get("project") || 0);
      const remembered = recallProject();
      const last = imported
        || (wanted && mineList.find((x) => x.id === wanted))
        || (remembered && mineList.find((x) => x.id === remembered))
        || mineList.find((x) => x.scenes.length > 0);
      if (last) {
        showProject(last);
        if (last.character) setCharacter(last.character);
      }
      setLoading(false);
      void loadBalance();
      if (imported) {
        window.setTimeout(
          () => timelineRef.current?.scrollIntoView({ behavior: scrollBehavior(), block: "start" }),
          400
        );
      }
    })();
    return () => {
      alive = false;
    };
  }, [loadBalance, i18n.language, showProject, t]);

  // Модели дока с ценами сцен. Открыты всем: гость видит цены до входа.
  // modelsTry — «Повторить» на кнопке модели, если список не пришёл.
  const [modelsTry, setModelsTry] = useState(0);
  useEffect(() => {
    let alive = true;
    void (async () => {
      const res = await fetchData<CartoonModels>("cartoon/models/", "GET", null, true);
      if (!alive) return;
      if (res.ok && res.data && Array.isArray(res.data.models)) {
        setModels(res.data);
        setModelsError(false);
      } else {
        setModelsError(true);
      }
    })();
    return () => {
      alive = false;
    };
  }, [modelsTry]);

  // --- док: модель, качество, длительность ---
  const modelList = models?.models ?? null;
  // Мультфильма ещё нет (гость или новый) — настройки живут в черновике.
  const local = !authed || !project;
  // Выбранное в доке до мультфильма (черновик) — под нынешний список моделей.
  const chosen = sanitizeDock(draftDock(draft), modelList);
  // Чем снимутся сцены без мультфильма: выбранное, иначе — значения по умолчанию из админки.
  const localExplicit = chosen ?? explicitDefaults(models);
  const pending = project && dockPending?.projectId === project.id ? dockPending.settings : null;
  // Док или формат едут на сервер — цены строк ещё прежние: «Снять» ждёт новую цену.
  const repricing = Boolean(pending) || (project != null && savingProject === project.id);
  const projectSaved = project ? completeDock(project) : null;
  const effective = project?.effective ?? null;
  const dockShown: DockSettings | null = local
    ? localExplicit ?? displayDefaults(models)
    : pending ??
      (effective
        ? { video_model: effective.video_model, resolution: effective.resolution, duration: effective.duration }
        : displayDefaults(models));
  const dockModel = findModel(modelList, dockShown?.video_model);
  const want = presetsQuery({
    lang: apiLang(i18n.language),
    aspect,
    projectId: local ? null : project?.id ?? null,
    saved: project
      ? { video_model: project.video_model ?? null, resolution: project.resolution ?? null, duration: project.duration ?? null }
      : null,
    explicit: local ? localExplicit : null,
  });
  // Витрина посчитана под нынешние формат и настройки — её числа и показываем.
  const cardsFresh = pricedKey === want.key;
  const estimateDock = local ? localExplicit : pending ?? projectSaved;
  const estimateModel = findModel(modelList, estimateDock?.video_model);

  // Сменились формат, настройки дока или открытый мультфильм — перезапрашиваем
  // цены витрины. Пауза — человек щёлкает значения подряд.
  useEffect(() => {
    if (pricedKey === null || pricedKey === want.key) return;
    let alive = true;
    const timer = window.setTimeout(async () => {
      const res = await fetchData<{ presets: Preset[] }>(`cartoon/presets/?${want.query}`, "GET", null, true);
      if (!alive || !res.ok || !res.data) return;
      setPresets(res.data.presets || []);
      setPricedKey(want.key);
    }, 250);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [want.key, want.query, pricedKey]);

  useEffect(() => {
    void (async () => {
      const res = await fetchData<AudioConfig>("cartoon/audio/config/", "GET", null, false);
      if (res.ok && res.data) setAudioConfig(res.data);
    })();
  }, []);

  // Опрос, пока что-то считается. adopt — открыть именно этот мультфильм;
  // без него ответ по мультфильму, который уже не открыт, экран не трогает.
  const refresh = useCallback(async (id: number, adopt = false) => {
    const read = async () => {
      const epoch = patchEpoch.current;
      const res = await fetchData<Project>(`cartoon/projects/${id}/`, "GET", null, true);
      return { res, stale: epoch !== patchEpoch.current };
    };
    // Пока шёл запрос, на экран лёг ответ правки дока или формата: это чтение
    // могло уйти раньше правки — не затираем её прежними настройками, читаем ещё раз.
    let got = await read();
    for (let attempt = 0; attempt < 2 && got.stale && !adopt && got.res.ok; attempt++) got = await read();
    const res = got.res;
    if (res.ok && res.data && (adopt || !got.stale)) {
      const fresh = res.data;
      if (adopt || currentIdRef.current === fresh.id) {
        showProject(fresh);
        settleNotes(fresh, false);
      }
      setProjects((prev) => prev.map((x) => (x.id === fresh.id ? fresh : x)));
    }
    return res.data || null;
  }, [showProject, settleNotes]);

  useEffect(() => {
    const busy =
      !!project &&
      (project.status === "assembling" ||
        Boolean(project.voicing && !project.voicing.finished) ||
        project.scenes.some((s) => WORKING.includes(s.status)));
    if (!busy || !project) {
      if (pollRef.current) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }
    if (pollRef.current) return;
    pollRef.current = window.setInterval(() => {
      void refresh(project.id).then(() => void loadBalance());
    }, 4000);
    return () => {
      if (pollRef.current) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [project, refresh, loadBalance]);

  const ensureProject = useCallback(async (): Promise<Project | null> => {
    if (project) return project;
    if (!character) return null;
    // Док трогали до первой сцены — мультфильм заводится сразу с этими
    // настройками; не трогали — сервер даст значения по умолчанию.
    const dock = sanitizeDock(draftDock(draft), modelList);
    const res = await fetchData<Project>(
      "cartoon/projects/", "POST",
      { character_id: character.id, aspect_ratio: aspect, ...(dock ? dockBody(dock) : {}) }, true
    );
    if (res.ok && res.data) {
      showProject(res.data);
      setProjects((prev) => [res.data as Project, ...prev]);
      return res.data;
    }
    setError((res.data as ApiRefusal)?.detail || t("studio_ui.err_project"));
    return null;
    // Формат — в зависимостях: без него новый мультфильм заводился в
    // прежнем формате, выбранном до переключения.
  }, [project, character, aspect, draft, modelList, t, showProject]);

  // Открытый мультфильм запоминаем: после оплаты и входа студия откроет его же.
  useEffect(() => {
    if (project?.id) rememberProject(project.id);
  }, [project?.id]);

  const addScene = async (preset: Preset) => {
    if (!authed) {
      // Гость собирает ленту без входа (просьба клиента): она живёт в браузере,
      // а войти мы попросим, когда он захочет снимать.
      if (!character) {
        setNeedHero(true);
        heroRef.current?.scrollIntoView({ behavior: scrollBehavior(), block: "start" });
        return;
      }
      if ((draft?.scenes.length || 0) >= MAX_DRAFT_SCENES) {
        setError(t("studio_ui.err_draft_full"));
        return;
      }
      setNeedHero(false);
      // Сцена запоминает героя, с которым её добавили: сменил героя для
      // следующей сцены — предыдущая остаётся со своим (правило клиента).
      updateDraft((d) => ({
        ...d,
        character_id: d.character_id ?? character.id,
        scenes: [...d.scenes, { key: newSceneKey(), preset_id: preset.id, character_id: character.id }],
      }));
      trackFunnel("studio_scene_add", { preset_id: preset.id, authed: false });
      revealLastScene(timelineRef);
      return;
    }
    if (!character) {
      // Сцены видны сразу, но снимать их не с кем — ведём к первому шагу.
      setNeedHero(true);
      heroRef.current?.scrollIntoView({ behavior: scrollBehavior(), block: "start" });
      return;
    }
    setError("");
    setNeedHero(false);
    setShortfall(null);
    setAdding(preset.id);
    const p = await ensureProject();
    if (!p) {
      setAdding(null);
      return;
    }
    // Героя передаём явно: иначе сцена снялась бы с героем, с которого начат
    // мультфильм, а не с тем, кого человек выбрал сейчас.
    const res = await fetchData<StudioScene>(
      `cartoon/projects/${p.id}/scenes/`, "POST", { preset_id: preset.id, character_id: character.id }, true
    );
    setAdding(null);
    if (res.ok && res.data) {
      trackFunnel("studio_scene_add", { preset_id: preset.id, authed: true });
      await refresh(p.id, true);
      // Лента ниже сцен, и без прокрутки человек не понимает, куда делась
      // добавленная сцена.
      revealLastScene(timelineRef);
    } else {
      setError((res.data as ApiRefusal)?.detail || t("studio_ui.err_scene"));
    }
  };

  /** Снять сцену из ленты. Здесь и только здесь тратятся кредиты. */
  const renderScene = async (scene: StudioScene) => {
    if (!project) return;
    trackFunnel("studio_render_click", { authed: true, scene_id: scene.id });
    noteScene(scene.id, null);
    markBusy(scene.id, true);
    // Цена с кнопки: выросла с тех пор (док сменили в другой вкладке или в боте,
    // модель выключили) — сервер не снимет и вернёт новую.
    const res = await fetchData<StudioScene>(
      `cartoon/scenes/${scene.id}/render/`, "POST", quoteBody(scene.render_credits), true
    );
    if (res.ok) {
      // Строка свободна, когда уже показывает «снимается»: иначе на один запрос
      // «Снять» снова жалось бы.
      await refresh(project.id);
      markBusy(scene.id, false);
      return;
    }
    markBusy(scene.id, false);
    const d = res.data as ApiRefusal;
    const changed = priceChanged(res.status, d);
    if (changed) {
      // Ничего не снято и не списано: новая цена — в строке, просьба нажать ещё раз — рядом.
      noteScene(scene.id, priceChangedText(changed, d), "error", changed.credits);
      await refresh(project.id);
    } else if (alreadyShot(res.status, d)) {
      // Строка устарела: сцену уже сняли в другой вкладке или в боте. Второй съёмки
      // нет — показываем готовую сцену, переснять её можно подписанной кнопкой.
      noteScene(scene.id, dt("studio_ui.scene_already_shot"), "info");
      await refresh(project.id);
    } else if (d?.required) {
      openPaywall({ required: Number(d.required), balance: Number(d.balance ?? 0) });
    } else {
      // «Цены нет», «обновите страницу» — на языке человека, а не русским текстом сервера.
      noteScene(scene.id, refusalMessage(d, "studio_ui.scene_save_failed", true));
    }
  };

  // --- лента гостя: те же действия, что у проекта, но над черновиком ---
  // У черновика нет id из базы, поэтому сцена ленты получает отрицательный id,
  // а по нему восстанавливается её место в черновике.
  const guestIndex = (scene: StudioScene) => -scene.id - 1;

  const guestMove = (scene: StudioScene, dir: -1 | 1) =>
    updateDraft((d) => {
      const list = [...d.scenes];
      const i = guestIndex(scene);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= list.length) return d;
      [list[i], list[j]] = [list[j], list[i]];
      return { ...d, scenes: list };
    });

  const guestDelete = (scene: StudioScene) =>
    updateDraft((d) => ({ ...d, scenes: d.scenes.filter((_, i) => i !== guestIndex(scene)) }));

  const guestPickCharacter = (scene: StudioScene, characterId: number) =>
    updateDraft((d) => ({
      ...d,
      scenes: d.scenes.map((s, i) => (i === guestIndex(scene) ? { ...s, character_id: characterId } : s)),
    }));

  /** Добавить свою сцену по описанию. Ничего не генерируется и не списывается. */
  const addCustomScene = async () => {
    const text = customText.replace(/\s+/g, " ").trim().slice(0, 300);
    if (text.length < 3) {
      setError(t("studio_ui.custom_too_short"));
      return;
    }
    if (!character) {
      setNeedHero(true);
      heroRef.current?.scrollIntoView({ behavior: scrollBehavior(), block: "start" });
      return;
    }
    setError("");
    setNeedHero(false);
    const scrollToTimeline = () => revealLastScene(timelineRef);

    if (!authed) {
      if ((draft?.scenes.length || 0) >= MAX_DRAFT_SCENES) {
        setError(t("studio_ui.err_draft_full"));
        return;
      }
      updateDraft((d) => ({
        ...d,
        character_id: d.character_id ?? character.id,
        scenes: [...d.scenes, {
          key: newSceneKey(), preset_id: 0, character_id: character.id, custom_text: text,
        }],
      }));
      trackFunnel("studio_scene_add", { custom: true, authed: false });
      setCustomText("");
      scrollToTimeline();
      return;
    }

    setAdding(-1);
    const p = await ensureProject();
    if (!p) {
      setAdding(null);
      return;
    }
    const res = await fetchData<StudioScene>(
      `cartoon/projects/${p.id}/scenes/`, "POST", { custom_text: text, character_id: character.id }, true
    );
    setAdding(null);
    if (res.ok && res.data) {
      trackFunnel("studio_scene_add", { custom: true, authed: true });
      setCustomText("");
      await refresh(p.id, true);
      scrollToTimeline();
    } else {
      setError((res.data as ApiRefusal)?.detail || t("studio_ui.err_scene"));
    }
  };

  /** Кадр своей сцены до съёмки — увидеть, что получится. */
  const frameScene = async (scene: StudioScene) => {
    if (!authed || !project) {
      openAuth("render");
      return;
    }
    setFramingId(scene.id);
    noteScene(scene.id, null);
    const res = await fetchData<StudioScene>(`cartoon/scenes/${scene.id}/frame/`, "POST", {}, true);
    setFramingId(null);
    if (res.ok) {
      await refresh(project.id);
      void loadBalance();
      return;
    }
    const d = res.data as ApiRefusal;
    if (d?.required) {
      openPaywall({ required: Number(d.required), balance: Number(d.balance ?? 0), kind: "character" });
    } else {
      // Кадр жали у строки ленты — и отказ там же.
      noteScene(scene.id, refusalMessage(d, "studio_ui.err_tryon", true));
    }
  };

  /** Выбрать героя для следующих сцен. Уже набранные сцены своих героев не меняют. */
  const pickHero = (c: StudioCharacter) => {
    setCharacter(c);
    setNeedHero(false);
    trackFunnel("studio_hero_pick", { character_id: c.id, authed });
    // Первый выбранный герой становится героем мультфильма — с ним проект
    // переедет после входа. Дальше у каждой сцены свой.
    if (!authed) updateDraft((d) => ({ ...d, character_id: d.character_id ?? c.id }));
  };

  /** Снимать гость не может — это деньги и аккаунт. Здесь и просим войти. */
  const guestRender = (from: "scene" | "cta") => {
    trackFunnel("studio_render_click", { authed: false, from });
    openAuth("render");
  };

  /** Название мультфильма. Клиент: человек должен сам назвать свою серию. */
  const renameMovie = async (value: string) => {
    if (!project) return;
    const title = value.replace(/\s+/g, " ").trim().slice(0, 140);
    if (!title || title === project.title) return;
    // В общей очереди правок: ответ — мультфильм целиком, и пришедший после ответа
    // правки дока он вернул бы на экран прежние настройки.
    const res = await patchProject(project.id, { title }, false);
    if (res.ok && res.data) {
      const fresh = res.data;
      if (currentIdRef.current === fresh.id) showProject(fresh);
      setProjects((prev) => prev.map((x) => (x.id === fresh.id ? fresh : x)));
    } else {
      setError((res.data as ApiRefusal)?.detail || t("studio_ui.err_scene"));
    }
  };

  /** Реплика героя: её играет модель в кадре и ею же озвучивается сцена. */
  const setSceneDialogue = async (scene: StudioScene, text: string) => {
    if (!project) return;
    noteScene(scene.id, null);
    markBusy(scene.id, true);
    const res = await fetchData(`cartoon/scenes/${scene.id}/`, "PATCH", { dialogue: text }, true);
    markBusy(scene.id, false);
    if (!res.ok) {
      noteScene(scene.id, refusalMessage(res.data, "studio_ui.scene_save_failed"));
      return;
    }
    await refresh(project.id);
  };

  /** Гость реплику тоже пишет — она переедет вместе с лентой после входа. */
  const guestDialogue = (scene: StudioScene, text: string) =>
    updateDraft((d) => ({
      ...d,
      scenes: d.scenes.map((s, i) => (i === guestIndex(scene) ? { ...s, dialogue: text } : s)),
    }));

  /** Нарисовать кадр сцены заново: прежний не понравился или вышел не тот герой. */
  const redrawFrame = async (scene: StudioScene) => {
    if (!project) return;
    noteScene(scene.id, null);
    markBusy(scene.id, true);
    const res = await fetchData(`cartoon/scenes/${scene.id}/`, "PATCH",
                                { new_keyframe: true }, true);
    markBusy(scene.id, false);
    if (!res.ok) {
      noteScene(scene.id, refusalMessage(res.data, "studio_ui.scene_save_failed"));
      return;
    }
    // Кадра больше нет — сразу рисуем новый, чтобы человек не искал кнопку.
    if (scene.custom_text) await frameScene(scene);
    else await tryOnTimelineScene(scene);
    await refresh(project.id);
  };

  /** Поставить на сцену другого героя. Работает, пока сцена не снята. */
  const setSceneCharacter = async (scene: StudioScene, characterId: number) => {
    if (!project) return;
    noteScene(scene.id, null);
    markBusy(scene.id, true);
    const res = await fetchData(`cartoon/scenes/${scene.id}/`, "PATCH",
                                { character_id: characterId }, true);
    markBusy(scene.id, false);
    if (!res.ok) noteScene(scene.id, refusalMessage(res.data, "studio_ui.scene_save_failed"));
    await refresh(project.id);
  };

  const moveScene = async (scene: StudioScene, dir: -1 | 1) => {
    if (!project) return;
    const list = [...project.scenes].sort((a, b) => a.order - b.order);
    const i = list.findIndex((s) => s.id === scene.id);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= list.length) return;
    // Меняем местами и сохраняем обе позиции: сервер хранит явный порядок,
    // а не выводит его из времени создания.
    markBusy(scene.id, true);
    const a = list[i];
    const b = list[j];
    await Promise.all([
      fetchData(`cartoon/scenes/${a.id}/`, "PATCH", { order: b.order }, true),
      fetchData(`cartoon/scenes/${b.id}/`, "PATCH", { order: a.order }, true),
    ]);
    markBusy(scene.id, false);
    await refresh(project.id);
  };

  /** Переснять сцену. Готовую — только после подтверждения с ценой: это
   *  ~160 кредитов, а кнопку легко задеть случайно. */
  const retryScene = async (scene: StudioScene) => {
    if (!project) return;
    // Цена на кнопке (у готовой — и в вопросе): с ней и уходит запрос.
    const credits = scene.render_credits ?? scene.preset.credits;
    if (scene.status === "ready") {
      // Цены нет (себестоимость модели неизвестна) — «спишется 0 кр.» было бы
      // неправдой: спрашиваем без суммы, сервер сам откажет и ничего не спишет.
      // Пересъёмка идёт с нынешними настройками дока — их и называем рядом с ценой.
      const question = credits != null && scene.config
        ? dt("studio_ui.reshoot_confirm_cfg", { credits, config: cfgText(scene.config) })
        : credits != null
        ? t("studio_ui.reshoot_confirm", {
            defaultValue: "Переснять сцену заново? Спишется {{credits}} кр., нынешний ролик заменится новым.",
            credits,
          })
        : t("studio_ui.reshoot_confirm_no_price", {
            defaultValue: "Переснять сцену заново? Нынешний ролик заменится новым.",
          });
      if (!window.confirm(question)) return;
    }
    noteScene(scene.id, null);
    markBusy(scene.id, true);
    // С состоянием строки: у «ошибки» не спрашиваем, и если сцену с тех пор пересняли
    // (другая вкладка, бот), сервер готовый ролик не заменит.
    const res = await fetchData<StudioScene>(
      `cartoon/scenes/${scene.id}/`, "PATCH", retryBody(credits, scene.status), true
    );
    if (!res.ok) {
      // Как у «Снять»: не хватает кредитов — окно покупки, а не тишина;
      // цена выросла — новая цена у строки, ничего не снято.
      const d = res.data as ApiRefusal;
      const changed = priceChanged(res.status, d);
      if (changed) noteScene(scene.id, priceChangedText(changed, d, true), "error", changed.credits);
      else if (alreadyShot(res.status, d)) noteScene(scene.id, dt("studio_ui.scene_already_shot"), "info");
      else if (d?.required) openPaywall({ required: Number(d.required), balance: Number(d.balance ?? 0) });
      else noteScene(scene.id, refusalMessage(d, "studio_ui.scene_save_failed", true));
    }
    // Строка свободна, только когда показывает новое состояние: иначе на один запрос
    // она жила бы с прежними ценой и кнопками.
    await refresh(project.id);
    markBusy(scene.id, false);
  };

  /**
   * Док поменяли: у мультфильма — на сервере, без мультфильма — в черновике.
   * field — что человек тронул: у мультфильма без своих настроек уходит только оно
   * (dockPatch), и длительности сцен из библиотеки не становятся одной молча.
   */
  const applyDock = async (next: DockSettings, notes: DockNotice[], field: DockField) => {
    if (sameDock(next, dockShown) && !notes.length) return;
    setDockError("");
    if (local) {
      // Свои длительности сцен черновика — под новую модель, как сервер делает у мультфильма.
      const durations = findModel(modelList, next.video_model)?.caps.durations || [];
      setNotices([...notes, ...clampSceneDurations(draft?.scenes ?? [], durations).notices]);
      updateDraft((d) => ({ ...d, ...next, scenes: clampSceneDurations(d.scenes, durations).scenes }));
      return;
    }
    if (!project) return;
    const id = project.id;
    const seq = ++dockSeq.current;
    setNotices(notes);
    setDockPending({ projectId: id, settings: next });
    const res = await patchProject(id, dockPatch(project, next, field));
    // Ответы идут по очереди, каждый — состояние сервера после своей правки: берём
    // каждый, а «едет на сервер» снимаем с последним.
    if (seq === dockSeq.current) setDockPending(null);
    const current = currentIdRef.current === id;
    if (res.ok && res.data) {
      const fresh = res.data;
      if (current) {
        showProject(fresh);
        // У строк новые цены: «Цена изменилась: теперь N кр» с прежним N уходит.
        settleNotes(fresh, true);
      }
      setProjects((prev) => prev.map((x) => (x.id === fresh.id ? fresh : x)));
      // Свои длительности сцен, которых новая модель не умеет, сервер подогнал сам.
      const more = serverNotices(fresh);
      if (current && more.length) setNotices((prev) => [...prev, ...more]);
      return;
    }
    if (!current) return;
    // Не сохранилось: сообщения «подогнали значение» больше не о чём.
    setNotices([]);
    setDockError(refusalMessage(res.data, "studio_ui.dock_save_failed"));
    // Состояние сервера — через ту же очередь, после всех правок.
    void enqueuePatch(() => refresh(id));
  };

  const pickDockModel = (id: string) => {
    if (!modelList) return;
    const change = switchModel(modelList, dockShown, id);
    if (change) void applyDock(change.settings, change.notices, "video_model");
  };

  const pickDockResolution = (value: string) => {
    const next = modelList && dockShown ? withResolution(modelList, dockShown, value) : null;
    if (next) void applyDock(next, [], "resolution");
  };

  const pickDockDuration = (value: number) => {
    const next = modelList && dockShown ? withDuration(modelList, dockShown, value) : null;
    if (next) void applyDock(next, [], "duration");
  };

  /**
   * Снятая сцена, другая длительность. Сохраняем длительность и берём у
   * сервера цену новой съёмки (ровно ту, что спишет «Снять»), спрашиваем —
   * и снимаем. Отказался или не хватило кредитов — возвращаем как было:
   * длительность не должна расходиться с уже снятым роликом.
   */
  const reshootWithDuration = async (scene: StudioScene, value: number | null) => {
    if (!project) return;
    const id = scene.id;
    const before = scene.duration ?? null;
    // Длина ролика — по съёмке (у снятых до дока сервер отдаёт её по пресету).
    const was = scene.shot?.duration ?? scene.config?.duration ?? scene.preset.duration ?? null;
    const patch = (body: Record<string, unknown>) =>
      fetchData<StudioScene>(`cartoon/scenes/${id}/`, "PATCH", body, true);
    const finish = async (text: string | null = null, tone: SceneNote["tone"] = "error", price?: number | null) => {
      await refresh(project.id);
      markBusy(id, false);
      if (text) noteScene(id, text, tone, price);
    };
    noteScene(id, null);
    markBusy(id, true);
    const res = await patch({ duration: value });
    if (!res.ok || !res.data) {
      await finish(refusalMessage(res.data, "studio_ui.scene_save_failed"));
      return;
    }
    const next = res.data.config?.duration ?? value;
    // Ролик уже такой длины — снимать нечего, длительность просто сохранилась.
    if (next === was) {
      await finish();
      return;
    }
    const credits = res.data.render_credits;
    if (credits == null) {
      // Цены нет — съёмку сервер всё равно не примет.
      await patch({ duration: before });
      await finish(t("studio_ui.price_unavailable", { defaultValue: "Цена сейчас недоступна" }));
      return;
    }
    // Переснимется нынешними моделью и качеством дока и в нынешнем формате: отличаются
    // от прошлой съёмки — вопрос называет их, а не только секунды и цену.
    const question = reshootDurationQuestion({
      shot: scene.shot ?? null, next: res.data.config ?? null, from: was ?? "?", to: next ?? "?", credits,
    });
    if (!window.confirm(dt(question.key, question.params))) {
      await patch({ duration: before });
      await finish();
      return;
    }
    // Снимаем ровно за то, что человек подтвердил: выросла цена — сервер откажет.
    const shot = await patch(retryBody(credits, scene.status));
    if (!shot.ok) {
      await patch({ duration: before });
      // Как у «Снять»: не хватает кредитов — окно покупки, а не тишина.
      const d = shot.data as ApiRefusal;
      const changed = priceChanged(shot.status, d);
      if (d?.required && !changed && !alreadyShot(shot.status, d)) {
        openPaywall({ required: Number(d.required), balance: Number(d.balance ?? 0) });
        await finish();
        return;
      }
      if (changed) {
        // Цена — за новую длительность, а строка вернулась к прежней: числа на кнопке
        // такого нет (price null), сообщение снимет правка дока или следующее действие.
        await finish(priceChangedText(changed, d, true), "error", null);
      } else if (alreadyShot(shot.status, d)) {
        // Как у «Снять» и ↻: сцену сняли в другой вкладке — подсказка, а не ошибка.
        await finish(dt("studio_ui.scene_already_shot"), "info");
      } else {
        await finish(refusalMessage(d, "studio_ui.scene_save_failed", true));
      }
      return;
    }
    await finish();
  };

  /**
   * Своя длительность сцены (null — как у мультфильма). У снятой сцены это
   * новая платная съёмка: сперва сервер называет её цену, потом спрашиваем.
   */
  const setSceneDuration = async (scene: StudioScene, value: number | null) => {
    if (!authed || !project) {
      updateDraft((d) => ({
        ...d,
        scenes: d.scenes.map((s, i) => (i === guestIndex(scene) ? withSceneDuration(s, value) : s)),
      }));
      return;
    }
    if (value === (scene.duration ?? null)) return;
    if (scene.status === "ready") {
      await reshootWithDuration(scene, value);
      return;
    }
    noteScene(scene.id, null);
    markBusy(scene.id, true);
    const res = await fetchData<StudioScene>(`cartoon/scenes/${scene.id}/`, "PATCH", { duration: value }, true);
    // Строка свободна только с новыми длительностью и ценой: иначе на один запрос
    // «Снять» жалось бы по прежней цене (ревью R1 W2).
    await refresh(project.id);
    markBusy(scene.id, false);
    if (!res.ok) noteScene(scene.id, refusalMessage(res.data, "studio_ui.scene_save_failed"));
  };

  const deleteScene = async (scene: StudioScene) => {
    if (!project) return;
    noteScene(scene.id, null);
    markBusy(scene.id, true);
    const res = await fetchData(`cartoon/scenes/${scene.id}/`, "DELETE", null, true);
    markBusy(scene.id, false);
    if (!res.ok) noteScene(scene.id, refusalMessage(res.data, "studio_ui.scene_save_failed"));
    await refresh(project.id);
  };

  /** ИИ пишет реплики на все сцены — бесплатно, только чтобы показать цену. */
  const planVoiceAll = async () => {
    if (!project) return;
    setPlanning(true);
    setError("");
    const res = await fetchData<VoicePlan>(
      `cartoon/projects/${project.id}/voice-plan/`, "POST",
      { lang: apiLang(i18n.language) }, true
    );
    setPlanning(false);
    if (res.ok && res.data) {
      setVoicePlan(res.data);
      return;
    }
    const d = res.data as ApiRefusal;
    if (d?.required) openPaywall({ required: Number(d.required), balance: Number(d.balance ?? 0), kind: "audio" });
    else setError(d?.detail || t("studio_ui.voiceall_err"));
  };

  const assemble = async () => {
    if (!project || project.status === "assembling") return;
    // В мультфильм идут только снятые сцены — остальные молча пропали бы.
    const left = project.scenes.filter((s) => s.status !== "ready").length;
    if (left > 0 && !window.confirm(t("studio_ui.assemble_skip_confirm", {
      defaultValue: "Не снятые сцены не войдут в мультфильм: {{n}} шт. Собрать из готовых?",
      n: left,
    }))) return;
    setAssembling(true);
    setError("");
    const res = await fetchData<Project>(
      `cartoon/projects/${project.id}/assemble/`, "POST", {}, true
    );
    setAssembling(false);
    // Сервер сразу отвечает «собирается» — по нему включаются крутилка и опрос.
    if (res.ok && res.data) {
      if (currentIdRef.current === res.data.id) showProject(res.data);
    } else setError((res.data as ApiRefusal)?.detail || t("studio_ui.err_assemble"));
  };

  /** Начать новый мультфильм: проект обнуляется, герой остаётся выбранным —
   *  чаще всего следующую историю снимают тем же персонажем. Старый проект
   *  никуда не девается, к нему можно вернуться списком ниже. */
  const startNewMovie = () => {
    setShare(null);
    showProject(null);
    setShortfall(null);
    setError("");
    setNotices([]);
    setDockError("");
    setSceneNotes({});
    setBusyIds(new Set());
  };

  const openProject = async (id: number) => {
    setShare(null);
    setShortfall(null);
    setError("");
    setNotices([]);
    setDockError("");
    setSceneNotes({});
    const known = projects.find((x) => x.id === id);
    if (known) showProject(known);
    const fresh = await refresh(id, true);
    if (fresh?.character) setCharacter(fresh.character);
  };

  // Пустые черновики в список не берём: проект создаётся при первой сцене, и
  // брошенная попытка не должна засорять переключатель. Исключение — тот, что
  // открыт сейчас: человек удалил из него последнюю сцену, и мультфильм не
  // должен пропасть с экрана вместе с ней (жалоба клиента: «удалил сцену —
  // исчезли оба»).
  const myMovies = projects.filter((m) => m.scenes.length > 0 || m.id === project?.id);

  /** Ссылка на публичную страницу мультфильма.
   *
   *  Делимся именно ей, а не файлом: страница несёт og:video (мессенджеры
   *  играют ролик прямо в переписке) и призыв «Создайте свой мультфильм» с
   *  переходом в студию. Отправленный mp4 не сказал бы про EsAI ничего.
   */
  const resultVideo = project?.result_video || "";
  const shareUrl = share && share.video === resultVideo ? share.url : "";
  const makeShareLink = useCallback(async () => {
    if (!resultVideo || shareUrl || sharing) return;
    setSharing(true);
    const res = await fetchData<{ share_url: string }>(
      "ai/video/share/", "POST", { url: resultVideo }, true
    );
    setSharing(false);
    if (res.ok && res.data?.share_url) setShare({ video: resultVideo, url: res.data.share_url });
  }, [resultVideo, shareUrl, sharing]);

  // Готовый ролик появляется после склейки — ссылку готовим сразу, чтобы
  // кнопки соцсетей не заставляли ждать ещё один запрос.
  useEffect(() => {
    if (resultVideo) void makeShareLink();
  }, [resultVideo, makeShareLink]);

  // Лента гостя в том же виде, что и сцены проекта: так её рисует та же
  // SceneTimeline, и гость видит ровно то, что увидит после входа.
  const presetById = new Map(presets.map((p) => [p.id, p]));
  // Кадр своей сцены стоит как примерка первой сцены библиотеки. Витрины нет —
  // цены тоже нет: «4 кр» по памяти разошлось бы с ценой в админке.
  const frameCredits = presets[0]?.tryon_credits;
  const charById = new Map(characters.map((c) => [c.id, c]));

  /** Цена и длительность карточки: посчитанные сервером под нынешние настройки,
   *  а пока витрина пересчитывается — подсказка из таблицы модели. */
  const cardPrice = (p: Preset): CardPrice => {
    if (!cardsFresh) {
      const est = cardEstimate(estimateModel, estimateDock, aspect, p.tryon_credits, models?.frame_credits);
      if (est) return est;
    }
    return { credits: p.credits, duration: p.duration };
  };

  const guestScenes: StudioScene[] =
    !authed && draft
      ? draft.scenes.map((s, i) => {
          const custom = Boolean(s.custom_text);
          const p = custom ? undefined : presetById.get(s.preset_id);
          const heroId = s.character_id ?? draft.character_id ?? character?.id ?? null;
          const hero = heroId ? charById.get(heroId) : undefined;
          const keyframe = custom ? "" : (heroId && framesByChar[heroId]?.[s.preset_id]) || "";
          const card = p ? cardPrice(p) : null;
          const own = s.duration ?? null;
          // Длительность: своя, иначе дока, иначе — сцены библиотеки (настроек нет).
          const duration = own ?? (localExplicit ? localExplicit.duration : card?.duration ?? dockShown?.duration ?? null);
          // Цена — та, что спишет «Снять» после входа: строка равна карточке, своя
          // длительность и своя сцена — по таблице модели, с кадром из запаса — только видео.
          const price = guestRowPrice({
            model: dockModel,
            resolution: dockShown?.resolution,
            duration,
            aspect,
            custom,
            ownDuration: own != null,
            keyframe: Boolean(keyframe),
            cardCredits: card ? card.credits : undefined,
            frameCredits: p?.tryon_credits,
            frameFallback: models?.frame_credits,
          });
          // Цены нет по ответу сервера — «Снять» выключено. Цена просто ещё не
          // известна (модели не загрузились) — гостя ко входу всё равно пускаем.
          const unavailable = Boolean(dockModel?.price_unavailable) || (!custom && card?.credits === null);
          return {
            id: -(i + 1),
            order: i,
            custom_text: s.custom_text || "",
            dialogue: s.dialogue || "",
            preset: {
              id: s.preset_id,
              title: custom ? (s.custom_text || "").slice(0, 60) : p?.title || "…",
              credits: price.full ?? (unavailable ? null : undefined),
              duration: duration ?? undefined,
              poster: custom ? "" : p?.preview_poster,
              clip: custom ? "" : p?.preview_video,
            },
            character: hero ? { id: hero.id, name: hero.name, image: hero.image } : null,
            keyframe,
            preview_video: custom ? "" : (heroId && videosByChar[heroId]?.[s.preset_id]) || "",
            video: "",
            status: "draft",
            error: "",
            credits_spent: 0,
            render_credits: price.render ?? (unavailable ? null : undefined),
            duration: own,
            config: dockShown
              ? {
                  video_model: dockShown.video_model,
                  model_name: dockModel ? modelLabel(dockModel) : "",
                  resolution: dockShown.resolution,
                  duration: duration ?? dockShown.duration,
                  aspect_ratio: aspect,
                }
              : null,
          };
        })
      : [];

  const scenes = !authed
    ? guestScenes
    : project
    ? [...project.scenes]
        .sort((a, b) => a.order - b.order)
        // Героя сцены сменили — ролик новой пары известен сразу, не дожидаясь
        // ответа сервера: превью переключается мгновенно (просьба клиента).
        .map((s) =>
          s.video || s.preview_video || !s.character || s.custom_text
            ? s
            : {
                ...s,
                preview_video: videosByChar[s.character.id]?.[s.preset.id] || "",
                // Примерили из ленты — кадр уже есть в запасе, показываем сразу,
                // не дожидаясь, пока сервер подставит его в сцену при съёмке.
                keyframe: s.keyframe || framesByChar[s.character.id]?.[s.preset.id] || "",
              }
        )
    : [];

  // Герои этого мультфильма: все, кого человек уже поставил в сцены. Их
  // держим под рукой — в следующую сцену чаще берут кого-то из уже занятых.
  const cast: StudioCharacter[] = [];
  {
    const seen = new Set<number>();
    const push = (id: number | null | undefined) => {
      if (!id || seen.has(id)) return;
      const c = charById.get(id);
      if (c) {
        seen.add(id);
        cast.push(c);
      }
    };
    for (const s of scenes) push(s.character?.id);
  }
  const castIds = new Set(cast.map((c) => c.id));
  const timelineCharacters = [...cast, ...visibleCharacters.filter((c) => !castIds.has(c.id))];
  const readyCount = scenes.filter((s) => s.status === "ready").length;
  const drafts = scenes.filter((s) => s.status === "draft").length;
  const working = scenes.some((s) => WORKING.includes(s.status));
  // Озвучка всего мультфильма прямо сейчас: кнопка ждёт, лента опрашивается.
  const voicingNow = Boolean(project?.voicing && !project.voicing.finished);
  // «Итого»: сумма цен строк, которые ещё снимать.
  const total = timelineTotal(scenes);
  // Модель мультфильма выключили в админке — сцены снимутся моделью библиотеки.
  const modelOff = !local && Boolean(project?.video_model) && effective?.model_available === false;

  /** Длительность в карточке ленты: что умеет модель сцены и сколько «по умолчанию». */
  const durationFor = (s: StudioScene): SceneDurationChoice | null => {
    const all = findModel(modelList, s.config?.video_model ?? dockShown?.video_model)?.caps.durations || [];
    if (all.length < 2) return null;
    // «По умолчанию» у сцены со своей длительностью: длительность мультфильма,
    // иначе — её сцены из библиотеки.
    const base = local ? localExplicit?.duration : pending?.duration ?? project?.duration;
    const card = s.custom_text ? undefined : presetById.get(s.preset.id);
    const fallback = base ? clampDuration(all, base) : card ? cardPrice(card).duration : dockShown?.duration ?? null;
    return { options: durationChoices(all, s.duration), fallback };
  };

  const assemblingNow = assembling || project?.status === "assembling";
  // Главная кнопка дока — только то, что на сайте уже есть: «Собрать мультфильм»,
  // а гостю — «Снять мультфильм», то есть вход. «Снять все» есть лишь в боте.
  const primary: DockPrimary | null =
    loading ? null
    : !authed ? (scenes.length > 0 ? { kind: "guest", count: scenes.length, onClick: () => guestRender("cta") } : null)
    : !project || scenes.length === 0 ? null
    : readyCount === 0 ? { kind: "assemble_off", total: scenes.length }
    : {
        kind: "assemble",
        ready: readyCount,
        total: scenes.length,
        busy: assemblingNow,
        fresh: !project.result_video,
        onClick: () => void assemble(),
      };

  return {
    loading,
    authed,
    balance,
    balanceFailed,
    error,
    aspect,
    project,
    movies: myMovies,
    heroes: {
      list: visibleCharacters,
      cast,
      selected: character,
      needHero,
      audience,
      showAudience: presets.some((p) => p.audience === "adults"),
    },
    library: {
      presets: visiblePresets,
      restCount,
      categories: visibleCategories,
      hasPopular: popularPresets.length > 0,
      hasPicks: picks.length > 0,
      activeCat,
      frames: tryOn,
      heroVideos,
      adding,
      tryingOn,
      customText,
      cardPrice,
    },
    timeline: {
      show: Boolean(character) || scenes.length > 0,
      scenes,
      characters: timelineCharacters.map((c) => ({ id: c.id, name: c.name, image: c.image })),
      busyIds,
      repricing,
      framingId,
      frameCredits,
      notes: authed ? sceneNotes : undefined,
      readyCount,
      drafts,
      working,
      voicingNow,
      total,
      audioEnabled: Boolean(audioConfig?.enabled),
      planning,
      assembling: assemblingNow,
      handlers: {
        onMove: authed ? moveScene : guestMove,
        onRetry: authed ? retryScene : () => undefined,
        onDelete: authed ? deleteScene : guestDelete,
        onRender: authed ? renderScene : () => guestRender("scene"),
        onPickCharacter: authed ? setSceneCharacter : guestPickCharacter,
        onFrame: frameScene,
        onTryOn: tryOnTimelineScene,
        onRedraw: authed ? redrawFrame : undefined,
        onDialogue: authed ? setSceneDialogue : guestDialogue,
        onAudio: audioConfig?.enabled
          ? authed
            ? (s) => setAudioScene(s)
            : () => openAuth("render")
          : undefined,
        durationFor,
        onDuration: (s, v) => void setSceneDuration(s, v),
        onDismissNote: (s) => noteScene(s.id, null),
      },
    },
    result: { video: resultVideo, shareUrl },
    dock: {
      models: modelList,
      modelsError,
      value: {
        model: dockShown?.video_model ?? null,
        modelName: effective?.model_name || (dockModel ? modelLabel(dockModel) : ""),
        resolution: dockShown?.resolution ?? null,
        duration: dockShown?.duration ?? null,
        aspect,
      },
      notices,
      warning: modelOff ? "studio_ui.dock_model_off" : null,
      total,
      hasShot: readyCount > 0,
      frameCredits: models?.frame_credits,
      saving: !local && project != null && savingProject === project.id,
      error: dockError || null,
      primary,
    },
    dialogs: {
      shortfall,
      authFor,
      audioScene,
      audioConfig,
      voicePlan,
      audioCharacters: timelineCharacters.map((c) => ({ id: c.id, name: c.name })),
    },
    refs: { heroes: heroRef, timeline: timelineRef },
    actions: {
      clearError: () => setError(""),
      pickAudience,
      pickHero,
      heroCreated: (c) => setCharacters((prev) => [c, ...prev]),
      heroDeleted: (id) => {
        setCharacters((prev) => prev.filter((c) => c.id !== id));
        if (character?.id === id) setCharacter(null);
      },
      pickCategory: (slug) => {
        setShown(PAGE_SIZE);
        setActiveCat(slug);
      },
      showMore: () => setShown((n) => n + PAGE_SIZE),
      addScene,
      tryOnScene,
      setCustomText: (text) => setCustomText(text.slice(0, 300)),
      addCustomScene,
      openProject,
      startNewMovie,
      renameMovie,
      assemble,
      planVoiceAll,
      guestRender,
      retryModels: () => setModelsTry((n) => n + 1),
      pickDockModel,
      pickDockResolution,
      pickDockDuration,
      pickAspect: setAspect,
      dismissNotices,
      dismissDockError: () => setDockError(""),
      openAuth,
      closeAuth: () => setAuthFor(null),
      openPaywall,
      closePaywall: () => setShortfall(null),
      closeAudio: () => setAudioScene(null),
      audioChanged: () => {
        void loadBalance();
        if (project) void refresh(project.id);
      },
      closeVoicePlan: () => setVoicePlan(null),
      voiceStarted: () => {
        if (project) void refresh(project.id);
      },
      scrollToHeroes: () => heroRef.current?.scrollIntoView({ block: "start", behavior: scrollBehavior() }),
      scrollToTimeline: () => timelineRef.current?.scrollIntoView({ block: "start", behavior: scrollBehavior() }),
    },
  };
}

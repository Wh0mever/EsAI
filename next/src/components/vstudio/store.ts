/**
 * Видеостудия: редьюсер стора (§9.4). State и Action — из lib/vstudio/types.ts.
 *
 * Один редьюсер на всю студию: лента, композер, лоток, цена, запуск,
 * библиотека и интерфейс. Все треки фронта шлют сюда VsAction через
 * dispatch из контекста (useVStudio). Здесь нет сети, таймеров и случайных
 * чисел — только чистые переходы, поэтому стор проверяют node-тесты
 * (store.test.mjs) без браузера.
 *
 * Правила, которые держит именно редьюсер:
 * - статус дубля не откатывается назад: устаревший ответ ленты не вернёт
 *   «Снимается» дублю, который опрос уже увидел готовым;
 * - кадры ленты чужого проекта в ленту не попадают (ответ, пришедший после
 *   переключения проекта, выбрасывается);
 * - номера @Image N — это порядок лотка: перестановка и выключение сразу
 *   меняют метки (их считает labels.ts по tray);
 * - готовая картинка из «Создать картинку» сама превращает чип «создаётся»
 *   в обычный: чип и дубль связаны uid ассета;
 * - параметры всегда допустимы для выбранной модели: при смене модели
 *   значение, которого у неё нет, заменяется ближайшим разрешённым.
 */
import { EMPTY_PROMPT_DOC, OPEN_TAKE_STATUSES } from "@/lib/vstudio/types";
import type {
  AssetJSON,
  ComposerFrames,
  ComposerState,
  FrameSlot,
  LibraryFilter,
  LibraryState,
  ModelJSON,
  PanelName,
  ProjectJSON,
  ProjectsState,
  ShotInputJSON,
  ShotJSON,
  ShotParams,
  TakeLite,
  TakeStatus,
  Toast,
  TrayItem,
  TrayStatus,
  Uid,
  VsAction,
  VsKind,
  VsState,
} from "@/lib/vstudio/types";

/* ------------------------------------------------------------------ */
/* Начальное состояние                                                 */
/* ------------------------------------------------------------------ */

/** Не больше стольких всплывающих сообщений одновременно (старые уходят). */
export const MAX_TOASTS = 4;
/** ShotInput.role — max_length=60 на сервере. */
export const MAX_ROLE_CHARS = 60;

export function emptyDoc() {
  return { v: 1 as const, blocks: EMPTY_PROMPT_DOC.blocks.map((b) => [...b]) };
}

export function emptyComposer(): ComposerState {
  return {
    kind: "video",
    model: null,
    params: {},
    doc: emptyDoc(),
    tray: [],
    frames: { first_frame: null, last_frame: null },
    forkedFrom: null,
  };
}

export function emptyProjects(): ProjectsState {
  return { items: [], next: null, loading: false, loaded: false, q: "" };
}

export function emptyLibrary(filter: LibraryFilter = "all"): LibraryState {
  return { items: [], next: null, loading: false, loaded: false, filter };
}

/**
 * Состояние при открытии страницы. seed — то, что уже есть в памяти вкладки
 * (модели, история): студия рисуется сразу, а свежие данные догружаются фоном.
 */
export function createInitialState(seed?: Partial<Pick<VsState, "mode" | "available" | "models" | "projects">>): VsState {
  const state: VsState = {
    mode: null,
    available: false,
    models: null,
    projects: emptyProjects(),
    project: null,
    shots: new Map(),
    takes: new Map(),
    order: [],
    feed: { next: null, loading: false, loaded: false },
    composer: emptyComposer(),
    quote: { status: "idle", key: null, data: null, error: null },
    run: { status: "idle", clientRequestId: null, error: null },
    library: emptyLibrary(),
    ui: {
      page: "loading",
      panels: { rail: false, settings: false, library: false, picker: false },
      paywall: null,
      auth: false,
      topup: false,
      toasts: [],
      focusTake: null,
      fullscreen: false,
    },
  };
  if (!seed) return state;
  const out = { ...state, ...seed };
  if (seed.models) out.composer = pickModelFor(out.composer, seed.models, null);
  return out;
}

/* ------------------------------------------------------------------ */
/* Модели и параметры                                                  */
/* ------------------------------------------------------------------ */

type ModelLists = NonNullable<VsState["models"]>;

export function findModel(
  models: ModelLists | null | undefined,
  id: string | null | undefined,
): { model: ModelJSON; kind: VsKind } | null {
  if (!models || !id) return null;
  const v = models.video.find((m) => m.id === id);
  if (v) return { model: v, kind: "video" };
  const i = models.image.find((m) => m.id === id);
  if (i) return { model: i, kind: "image" };
  return null;
}

/** Модель по умолчанию: первая доступная по тарифу (порядок задаёт сервер), иначе просто первая. */
export function defaultModel(list: ModelJSON[] | null | undefined): ModelJSON | null {
  if (!list || !list.length) return null;
  return list.find((m) => !m.locked) || list[0];
}

/** Текущая модель композера (null — модели не загружены или id устарел). */
export function selectModel(state: Pick<VsState, "models" | "composer">): ModelJSON | null {
  return findModel(state.models, state.composer.model)?.model ?? null;
}

function nearestNumber(value: number, allowed: number[]): number {
  let best = allowed[0];
  for (const a of allowed) {
    const d = Math.abs(a - value);
    const bd = Math.abs(best - value);
    // При равном расстоянии — меньшее: короче значит дешевле.
    if (d < bd || (d === bd && a < best)) best = a;
  }
  return best;
}

function pickString(value: string | undefined, allowed: string[], fallback: string | undefined): string | undefined {
  if (!allowed.length) return value ?? fallback;
  if (value && allowed.includes(value)) return value;
  if (fallback && allowed.includes(fallback)) return fallback;
  return allowed[0];
}

/**
 * Параметры, допустимые для модели. Значение, которого у модели нет,
 * заменяется: длительность — ближайшей разрешённой, остальное — значением
 * по умолчанию модели. «Авто» пропорция разрешена всегда (провайдеру не уходит).
 * Звук, seed и негатив остаются, только если модель их принимает.
 */
export function normalizeParams(model: ModelJSON | null | undefined, kind: VsKind, params: ShotParams): ShotParams {
  if (!model) return { ...params };
  const caps = model.caps;
  const defs = model.defaults || {};
  const out: ShotParams = {};

  const aspects = caps.aspect_ratios || [];
  const ar = params.aspect_ratio;
  if (ar === "auto" || (ar && aspects.includes(ar))) out.aspect_ratio = ar;
  else if (defs.aspect_ratio === "auto" || (defs.aspect_ratio && aspects.includes(defs.aspect_ratio))) {
    out.aspect_ratio = defs.aspect_ratio;
  } else out.aspect_ratio = aspects[0] ?? "auto";

  if (kind === "video") {
    const durations = caps.durations || [];
    const d = params.duration;
    if (durations.length) {
      if (typeof d === "number" && durations.includes(d)) out.duration = d;
      else if (typeof d === "number") out.duration = nearestNumber(d, durations);
      else if (typeof defs.duration === "number" && durations.includes(defs.duration)) out.duration = defs.duration;
      else out.duration = durations[0];
    } else if (typeof d === "number") out.duration = d;
    else if (typeof defs.duration === "number") out.duration = defs.duration;

    const res = pickString(params.resolution, caps.resolutions || [], defs.resolution);
    if (res) out.resolution = res;
    if (caps.audio && typeof params.generate_audio === "boolean") out.generate_audio = params.generate_audio;
    if (caps.negative && params.negative_prompt) out.negative_prompt = params.negative_prompt;
  }
  if (caps.seed && params.seed != null) out.seed = params.seed;
  return out;
}

/**
 * Модель для композера после загрузки моделей или смены вида. Порядок:
 * текущая (если есть в списке) → wanted (настройки проекта, черновик) →
 * по умолчанию для вида.
 */
function pickModelFor(composer: ComposerState, models: ModelLists, wanted: string | null): ComposerState {
  const current = findModel(models, composer.model);
  const want = findModel(models, wanted);
  let chosen: { model: ModelJSON; kind: VsKind } | null = null;
  if (current && current.kind === composer.kind) chosen = current;
  else if (want && want.kind === composer.kind) chosen = want;
  else if (current) chosen = current;
  else {
    const m = defaultModel(models[composer.kind]);
    if (m) chosen = { model: m, kind: composer.kind };
    else {
      // У этого вида моделей нет вовсе — берём другой вид, лишь бы кнопка жила.
      const other: VsKind = composer.kind === "video" ? "image" : "video";
      const o = defaultModel(models[other]);
      if (o) chosen = { model: o, kind: other };
    }
  }
  if (!chosen) return composer;
  return {
    ...composer,
    kind: chosen.kind,
    model: chosen.model.id,
    params: normalizeParams(chosen.model, chosen.kind, composer.params),
  };
}

/* ------------------------------------------------------------------ */
/* Проекты                                                             */
/* ------------------------------------------------------------------ */

const byActivityDesc = (a: ProjectJSON, b: ProjectJSON) =>
  a.last_activity_at < b.last_activity_at ? 1 : a.last_activity_at > b.last_activity_at ? -1 : 0;

function matchesQuery(p: ProjectJSON, q: string): boolean {
  const needle = q.trim().toLowerCase();
  return !needle || (p.title || "").toLowerCase().includes(needle);
}

function upsertProjectList(list: ProjectsState, project: ProjectJSON): ProjectsState {
  const rest = list.items.filter((p) => p.uid !== project.uid);
  const known = rest.length !== list.items.length;
  if (project.is_archived || (!known && !matchesQuery(project, list.q))) {
    return known ? { ...list, items: rest } : list;
  }
  return { ...list, items: [...rest, project].sort(byActivityDesc) };
}

export type ProjectGroups = { today: ProjectJSON[]; yesterday: ProjectJSON[]; earlier: ProjectJSON[] };

/** Группы левой колонки «Сегодня / Вчера / Раньше» по местной дате последней активности. */
export function groupProjects(items: ProjectJSON[], now: Date = new Date()): ProjectGroups {
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const startYesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1).getTime();
  const out: ProjectGroups = { today: [], yesterday: [], earlier: [] };
  for (const p of items) {
    const at = Date.parse(p.last_activity_at);
    if (Number.isFinite(at) && at >= startToday) out.today.push(p);
    else if (Number.isFinite(at) && at >= startYesterday) out.yesterday.push(p);
    else out.earlier.push(p);
  }
  return out;
}

/* ------------------------------------------------------------------ */
/* Дубли и лента                                                       */
/* ------------------------------------------------------------------ */

const STATUS_RANK: Record<TakeStatus, number> = {
  queued: 0,
  submitting: 1,
  running: 2,
  saving: 3,
  done: 4,
  failed: 4,
  canceled: 4,
  lost: 4,
};

export const isOpenStatus = (s: TakeStatus) => OPEN_TAKE_STATUSES.includes(s);

/**
 * Какая версия дубля свежее. Статус не откатывается назад: ответ ленты,
 * запрошенный до того, как опрос увидел «готово», не вернёт «Снимается».
 * Из закрытого в закрытый (lost → done: «Довезти» в админке) — берём новую.
 */
export function mergeTake(prev: TakeLite | undefined, next: TakeLite): TakeLite {
  if (!prev) return next;
  const a = STATUS_RANK[prev.status] ?? 0;
  const b = STATUS_RANK[next.status] ?? 0;
  if (b < a) return prev;
  return next;
}

function sortOrder(shots: Map<Uid, ShotJSON>): Uid[] {
  return [...shots.values()]
    .sort((x, y) => (x.created_at < y.created_at ? -1 : x.created_at > y.created_at ? 1 : x.uid < y.uid ? -1 : 1))
    .map((s) => s.uid);
}

/** Кадр в карту вместе с его дублями; takes карты — источник правды о статусе. */
function putShot(shots: Map<Uid, ShotJSON>, takes: Map<Uid, TakeLite>, shot: ShotJSON): void {
  const merged = (shot.takes || []).map((t) => {
    const m = mergeTake(takes.get(t.uid), t);
    takes.set(t.uid, m);
    return m;
  });
  shots.set(shot.uid, { ...shot, takes: merged });
}

function putTakeIntoShot(shots: Map<Uid, ShotJSON>, take: TakeLite): void {
  const shot = shots.get(take.shot);
  if (!shot) return;
  const list = shot.takes || [];
  const i = list.findIndex((t) => t.uid === take.uid);
  const next = i >= 0 ? list.map((t, j) => (j === i ? take : t)) : [...list, take];
  if (i < 0) next.sort((x, y) => (x.created_at < y.created_at ? -1 : x.created_at > y.created_at ? 1 : 0));
  shots.set(shot.uid, { ...shot, takes: next });
}

/** Кадры ленты по порядку (старые сверху). */
export function feedShots(state: Pick<VsState, "order" | "shots">): ShotJSON[] {
  return state.order.map((uid) => state.shots.get(uid)).filter((s): s is ShotJSON => Boolean(s));
}

/** uid открытых дублей — их опрашивает useTakePolling (включая восстановленные из других проектов). */
export function openTakeUids(state: Pick<VsState, "takes">): Uid[] {
  const out: Uid[] = [];
  for (const t of state.takes.values()) if (isOpenStatus(t.status)) out.push(t.uid);
  return out;
}

/** Сколько кредитов студии сейчас в резерве по известным вкладке дублям. */
export function studioReserved(state: Pick<VsState, "takes">): number {
  let sum = 0;
  for (const t of state.takes.values()) {
    if (t.charge_state === "reserved" && isOpenStatus(t.status)) sum += Number(t.credits?.reserved) || 0;
  }
  return sum;
}

/** Баланс из последнего ответа сервера (quote или запуск) и резерв дублей вкладки в тот момент. */
export type BalanceSnapshot = { balance: number; reserved: number; local: number };

/**
 * «N кр ждут результата» сейчас. Сервер знает все резервы (видео чата и
 * бота, сцены мультстудии, дубли студии), но говорит о них только в quote и
 * при запуске. Дальше вкладка сама видит, какие её дубли закрылись или
 * появились, и поправляет число на эту разницу — не дожидаясь нового quote.
 */
export function reservedNow(snap: BalanceSnapshot | null, localReserved: number): number {
  const local = Math.max(0, Number(localReserved) || 0);
  if (!snap) return local;
  return Math.max(0, (Number(snap.reserved) || 0) + (local - (Number(snap.local) || 0)));
}

/* ------------------------------------------------------------------ */
/* Лоток и кадры                                                       */
/* ------------------------------------------------------------------ */

const FRAME_KEYS: readonly FrameSlot[] = ["first_frame", "last_frame"];

function trayStatusOf(asset: AssetJSON): TrayStatus {
  // Материал удалили после запуска: «Изменить» старый кадр — чип сразу красный.
  if (asset.deleted) return "deleted";
  if (asset.status === "pending") return "pending";
  if (asset.status === "failed") return "failed";
  return "ready";
}

/** Чип лотка из входа кадра («Изменить», «Другая модель»). lid стабилен: слот + uid ассета. */
export function trayItemFromInput(input: ShotInputJSON): TrayItem {
  const a = input.asset;
  return {
    lid: `${input.slot}:${a.uid}`,
    assetUid: a.uid,
    slot: input.slot,
    role: (input.role || "").slice(0, MAX_ROLE_CHARS),
    included: input.included !== false,
    status: trayStatusOf(a),
    progress: 100,
    preview: a.thumb_url || a.url,
    asset: a,
    ...(a.status === "failed" && a.error_code ? { errorCode: a.error_code } : {}),
  };
}

function hasAsset(composer: ComposerState, assetUid: Uid | undefined, slot: TrayItem["slot"]): boolean {
  if (!assetUid) return false;
  if (slot === "reference") return composer.tray.some((i) => i.assetUid === assetUid);
  return composer.frames[slot]?.assetUid === assetUid;
}

type Located = { where: "tray"; index: number; item: TrayItem } | { where: FrameSlot; item: TrayItem };

function locate(composer: ComposerState, lid: string): Located | null {
  const index = composer.tray.findIndex((i) => i.lid === lid);
  if (index >= 0) return { where: "tray", index, item: composer.tray[index] };
  for (const k of FRAME_KEYS) {
    const f = composer.frames[k];
    if (f && f.lid === lid) return { where: k, item: f };
  }
  return null;
}

function patchItem(composer: ComposerState, lid: string, patch: (item: TrayItem) => TrayItem): ComposerState {
  const at = locate(composer, lid);
  if (!at) return composer;
  if (at.where === "tray") {
    const tray = composer.tray.map((i, j) => (j === at.index ? patch(i) : i));
    return { ...composer, tray };
  }
  return { ...composer, frames: { ...composer.frames, [at.where]: patch(at.item) } };
}

/** Все чипы (лоток и кадры) с этим ассетом — одним патчем. */
function patchByAsset(composer: ComposerState, assetUid: Uid, patch: (item: TrayItem) => TrayItem): ComposerState {
  let changed = false;
  const tray = composer.tray.map((i) => {
    if (i.assetUid !== assetUid) return i;
    changed = true;
    return patch(i);
  });
  const frames: ComposerFrames = { ...composer.frames };
  for (const k of FRAME_KEYS) {
    const f = frames[k];
    if (f && f.assetUid === assetUid) {
      frames[k] = patch(f);
      changed = true;
    }
  }
  return changed ? { ...composer, tray, frames } : composer;
}

/** Картинка из «Создать картинку» готова или не удалась → чип лотка следом. */
function syncChipsWithAsset(composer: ComposerState, asset: AssetJSON): ComposerState {
  return patchByAsset(composer, asset.uid, (i) => {
    // Удалённый человеком материал так и остаётся красным.
    if (i.status === "deleted") return i;
    const status = trayStatusOf(asset);
    return {
      ...i,
      status,
      progress: 100,
      preview: asset.thumb_url || asset.url || i.preview,
      asset,
      ...(status === "failed" ? { errorCode: asset.error_code || i.errorCode || "asset_failed" } : { errorCode: undefined }),
    };
  });
}

function moveInTray(tray: TrayItem[], from: number, to: number): TrayItem[] {
  const target = Math.max(0, Math.min(tray.length - 1, Math.trunc(to)));
  if (from === target) return tray;
  const next = [...tray];
  const [item] = next.splice(from, 1);
  next.splice(target, 0, item);
  return next;
}

/** «Сделать первым кадром» / «Сделать референсом». Занятый слот кадра меняется местами с чипом. */
function changeSlot(composer: ComposerState, lid: string, slot: TrayItem["slot"]): ComposerState {
  const at = locate(composer, lid);
  if (!at) return composer;
  const from = at.where === "tray" ? "reference" : at.where;
  if (from === slot) return composer;
  const item: TrayItem = { ...at.item, slot };

  let tray = composer.tray;
  const frames: ComposerFrames = { ...composer.frames };

  if (slot === "reference") {
    // Кадр → референс: в конец лотка; если этот ассет уже есть среди референсов, кадр просто уходит.
    frames[from as FrameSlot] = null;
    if (!(item.assetUid && tray.some((i) => i.assetUid === item.assetUid))) tray = [...tray, item];
    return { ...composer, tray, frames };
  }

  const displaced = frames[slot];
  if (at.where === "tray") {
    // Референс → кадр: вытесненный кадр встаёт на место чипа в лотке.
    tray = [...tray];
    if (displaced && !(displaced.assetUid && tray.some((i) => i.assetUid === displaced.assetUid && i.lid !== lid))) {
      tray.splice(at.index, 1, { ...displaced, slot: "reference" });
    } else {
      tray.splice(at.index, 1);
    }
  } else {
    // Кадр → другой кадр: меняются местами.
    frames[at.where] = displaced ? { ...displaced, slot: at.where } : null;
  }
  frames[slot] = item;
  return { ...composer, tray, frames };
}

/* ------------------------------------------------------------------ */
/* Библиотека                                                          */
/* ------------------------------------------------------------------ */

const FILTER_SOURCES: Record<LibraryFilter, string[] | null> = {
  all: null,
  uploads: ["upload"],
  generated: ["generated_image"],
  frames: ["frame"],
};

function fitsFilter(asset: AssetJSON, filter: LibraryFilter): boolean {
  if (asset.kind !== "image") return false;
  const sources = FILTER_SOURCES[filter];
  return !sources || sources.includes(asset.source);
}

function upsertLibrary(lib: LibraryState, asset: AssetJSON): LibraryState {
  const i = lib.items.findIndex((a) => a.uid === asset.uid);
  if (i >= 0) return { ...lib, items: lib.items.map((a, j) => (j === i ? asset : a)) };
  if (!lib.loaded || !fitsFilter(asset, lib.filter)) return lib;
  return { ...lib, items: [asset, ...lib.items] };
}

/* ------------------------------------------------------------------ */
/* Интерфейс                                                           */
/* ------------------------------------------------------------------ */

function pushToast(list: Toast[], toast: Toast): Toast[] {
  const rest = list.filter((t) => t.id !== toast.id);
  return [...rest, toast].slice(-MAX_TOASTS);
}

/** Смена проекта: лента очищается, композер берёт параметры проекта (текст и лоток остаются). */
function switchProject(state: VsState, project: ProjectJSON | null): VsState {
  let composer = state.composer;
  const s = project?.settings;
  if (s && typeof s === "object") {
    const kind: VsKind = s.kind === "image" || s.kind === "video" ? s.kind : composer.kind;
    const params = s.params && typeof s.params === "object" ? { ...s.params } : composer.params;
    const wanted = typeof s.model === "string" ? s.model : null;
    composer = { ...composer, kind, params, model: wanted ?? composer.model };
    if (state.models) {
      const found = findModel(state.models, wanted);
      composer =
        found && found.kind === kind
          ? { ...composer, model: found.model.id, params: normalizeParams(found.model, kind, params) }
          : pickModelFor({ ...composer, model: null }, state.models, wanted);
    }
  }
  return {
    ...state,
    project,
    shots: new Map(),
    takes: keepForeignOpenTakes(state.takes),
    order: [],
    feed: { next: null, loading: false, loaded: false },
    composer,
    ui: { ...state.ui, focusTake: null },
  };
}

/** Открытые дубли остаются в карте при смене проекта: их опрос и тост «готово» не должны пропасть. */
function keepForeignOpenTakes(takes: Map<Uid, TakeLite>): Map<Uid, TakeLite> {
  const out = new Map<Uid, TakeLite>();
  for (const [uid, t] of takes) if (isOpenStatus(t.status)) out.set(uid, t);
  return out;
}

/* ------------------------------------------------------------------ */
/* Адрес                                                               */
/* ------------------------------------------------------------------ */

export const STUDIO_BASE = "/video-studio";
const UID_RE = /^[0-9a-f]{32}$/;

export type StudioRoute = { uid: Uid | null; invalid: boolean };

/**
 * /video-studio → новая генерация; /video-studio/<32 hex> → проект; кривой
 * uid → «Проект не найден» (запрос с ним не уходит вовсе). pathname может
 * быть null до гидратации — тогда берём uid со страницы.
 */
export function parseStudioPath(pathname: string | null | undefined, fallback: string | null = null): StudioRoute {
  const path = pathname ?? (fallback ? `${STUDIO_BASE}/${fallback}` : STUDIO_BASE);
  const m = /^\/video-studio(?:\/([^/]+))?\/?$/.exec(path);
  if (!m || !m[1]) return { uid: null, invalid: false };
  let seg = m[1];
  try {
    seg = decodeURIComponent(seg);
  } catch {
    return { uid: null, invalid: true };
  }
  return UID_RE.test(seg) ? { uid: seg, invalid: false } : { uid: null, invalid: true };
}

/* ------------------------------------------------------------------ */
/* Редьюсер                                                            */
/* ------------------------------------------------------------------ */

export function reducer(state: VsState, action: VsAction): VsState {
  switch (action.type) {
    /* ---------- модели и страница ---------- */
    case "models/loaded": {
      const p = action.payload;
      const models = { video: p.video || [], image: p.image || [] };
      const wanted = typeof state.project?.settings?.model === "string" ? state.project.settings.model : null;
      return {
        ...state,
        mode: p.mode,
        available: Boolean(p.available),
        models,
        composer: pickModelFor(state.composer, models, wanted),
      };
    }
    case "page/status":
      return state.ui.page === action.status ? state : { ...state, ui: { ...state.ui, page: action.status } };

    /* ---------- история проектов ---------- */
    case "projects/loading":
      return { ...state, projects: { ...state.projects, loading: true } };
    case "projects/loaded": {
      const incoming = (action.page.items || []).filter((p) => !p.is_archived);
      let items: ProjectJSON[];
      if (action.append) {
        const seen = new Set(state.projects.items.map((p) => p.uid));
        items = [...state.projects.items, ...incoming.filter((p) => !seen.has(p.uid))];
      } else {
        items = incoming;
      }
      return {
        ...state,
        projects: { ...state.projects, items, next: action.page.next ?? null, loading: false, loaded: true },
      };
    }
    case "projects/query":
      if (state.projects.q === action.q) return state;
      return { ...state, projects: { ...state.projects, q: action.q, next: null, loading: true } };
    case "projects/upsert": {
      const projects = upsertProjectList(state.projects, action.project);
      const same = state.project?.uid === action.project.uid;
      return { ...state, projects, project: same ? action.project : state.project };
    }
    case "projects/remove":
      return {
        ...state,
        projects: { ...state.projects, items: state.projects.items.filter((p) => p.uid !== action.uid) },
      };
    case "project/set": {
      const next = action.project;
      if ((state.project?.uid ?? null) === (next?.uid ?? null)) {
        return next === state.project ? state : { ...state, project: next };
      }
      return switchProject(state, next);
    }

    /* ---------- лента ---------- */
    case "feed/loading":
      return { ...state, feed: { ...state.feed, loading: true } };
    case "feed/loaded": {
      const current = state.project?.uid;
      // Ответ по проекту, с которого уже ушли, — выбрасываем.
      if (!current) return { ...state, feed: { ...state.feed, loading: false } };
      const items = (action.page.items || []).filter((s) => s.project === current);
      const shots = new Map(state.shots);
      const takes = new Map(state.takes);
      for (const s of items) putShot(shots, takes, s);
      // «Показать раньше» двигает курсор назад; первая страница задаёт его заново.
      const next = action.older || !state.feed.loaded ? action.page.next ?? null : state.feed.next;
      return {
        ...state,
        shots,
        takes,
        order: sortOrder(shots),
        feed: { next, loading: false, loaded: true },
      };
    }
    case "shot/upsert": {
      if (state.project && action.shot.project !== state.project.uid) return state;
      const shots = new Map(state.shots);
      const takes = new Map(state.takes);
      putShot(shots, takes, action.shot);
      return { ...state, shots, takes, order: sortOrder(shots) };
    }
    case "takes/upsert": {
      if (!action.takes.length) return state;
      const takes = new Map(state.takes);
      const shots = new Map(state.shots);
      let composer = state.composer;
      let library = state.library;
      for (const incoming of action.takes) {
        const merged = mergeTake(takes.get(incoming.uid), incoming);
        takes.set(merged.uid, merged);
        putTakeIntoShot(shots, merged);
        const r = merged.result;
        if (r && r.kind === "image") {
          composer = syncChipsWithAsset(composer, r);
          library = upsertLibrary(library, r);
        }
      }
      return { ...state, takes, shots, composer, library };
    }
    case "take/added": {
      const takes = new Map(state.takes);
      const merged = mergeTake(takes.get(action.take.uid), action.take);
      takes.set(merged.uid, merged);
      const shots = new Map(state.shots);
      putTakeIntoShot(shots, { ...merged, shot: action.shot });
      return { ...state, takes, shots };
    }

    /* ---------- композер ---------- */
    case "composer/kind": {
      const c = state.composer;
      if (c.kind === action.kind) return state;
      const next: ComposerState = { ...c, kind: action.kind, model: null };
      if (!state.models) return { ...state, composer: next };
      const settings = state.project?.settings;
      const wanted = settings?.kind === action.kind && typeof settings.model === "string" ? settings.model : null;
      const picked = pickModelFor(next, state.models, wanted);
      // Нет моделей такого вида — вид не меняем, иначе кнопка «Создать» останется без модели.
      return picked.kind === action.kind ? { ...state, composer: picked } : state;
    }
    case "composer/model": {
      const c = state.composer;
      const found = findModel(state.models, action.model);
      if (!found) return { ...state, composer: { ...c, model: action.model } };
      return {
        ...state,
        composer: {
          ...c,
          kind: found.kind,
          model: found.model.id,
          params: normalizeParams(found.model, found.kind, c.params),
        },
      };
    }
    case "composer/params": {
      const c = state.composer;
      const merged: ShotParams = { ...c.params, ...action.params };
      for (const [k, v] of Object.entries(action.params)) {
        if (v === undefined) delete (merged as Record<string, unknown>)[k];
      }
      return { ...state, composer: { ...c, params: merged } };
    }
    case "composer/doc":
      return action.doc === state.composer.doc ? state : { ...state, composer: { ...state.composer, doc: action.doc } };
    case "composer/fill": {
      const shot = action.shot;
      const inputs = [...(shot.inputs || [])].sort((a, b) => a.position - b.position);
      const tray = inputs.filter((i) => i.slot === "reference").map(trayItemFromInput);
      const first = inputs.find((i) => i.slot === "first_frame");
      const last = inputs.find((i) => i.slot === "last_frame");
      const modelId = action.model ?? shot.model?.id ?? state.composer.model;
      const found = findModel(state.models, modelId);
      const kind: VsKind = found?.kind ?? shot.kind;
      const composer: ComposerState = {
        kind,
        model: found?.model.id ?? modelId ?? null,
        params: normalizeParams(found?.model, kind, shot.params || {}),
        doc: shot.prompt_doc && shot.prompt_doc.v === 1 ? shot.prompt_doc : emptyDoc(),
        tray,
        frames: {
          first_frame: first ? trayItemFromInput(first) : null,
          last_frame: last ? trayItemFromInput(last) : null,
        },
        forkedFrom: shot.uid,
      };
      const filled = state.models && !found ? pickModelFor(composer, state.models, null) : composer;
      return { ...state, composer: filled };
    }
    case "composer/restore": {
      const d = action.draft;
      const kind: VsKind = d.kind === "image" ? "image" : "video";
      let composer: ComposerState = { ...state.composer, kind, model: d.model ?? state.composer.model, doc: d.doc };
      composer = { ...composer, params: { ...d.params } };
      if (state.models) {
        const found = findModel(state.models, d.model);
        composer =
          found && found.kind === kind
            ? { ...composer, model: found.model.id, params: normalizeParams(found.model, kind, d.params) }
            : pickModelFor({ ...composer, model: null }, state.models, d.model);
      }
      return { ...state, composer };
    }
    case "composer/reset": {
      const c = state.composer;
      return {
        ...state,
        composer: {
          ...c,
          doc: action.keepText ? c.doc : emptyDoc(),
          tray: [],
          frames: { first_frame: null, last_frame: null },
          forkedFrom: null,
        },
      };
    }

    /* ---------- лоток и кадры ---------- */
    case "tray/add": {
      const c = state.composer;
      const item = action.item;
      if (locate(c, item.lid) || hasAsset(c, item.assetUid, item.slot)) return state;
      if (item.slot === "reference") {
        const tray = [...c.tray];
        const at = action.at == null ? tray.length : Math.max(0, Math.min(tray.length, Math.trunc(action.at)));
        tray.splice(at, 0, item);
        return { ...state, composer: { ...c, tray } };
      }
      // Новый кадр заменяет прежний в этом слоте (прежний остаётся в «Моих материалах»).
      return { ...state, composer: { ...c, frames: { ...c.frames, [item.slot]: item } } };
    }
    case "tray/update": {
      const { slot: _ignored, lid: _lid, ...patch } = action.patch;
      void _ignored;
      void _lid;
      const composer = patchItem(state.composer, action.lid, (i) => ({ ...i, ...patch }));
      return composer === state.composer ? state : { ...state, composer };
    }
    case "tray/remove": {
      const c = state.composer;
      const at = locate(c, action.lid);
      if (!at) return state;
      if (at.where === "tray") return { ...state, composer: { ...c, tray: c.tray.filter((i) => i.lid !== action.lid) } };
      return { ...state, composer: { ...c, frames: { ...c.frames, [at.where]: null } } };
    }
    case "tray/move": {
      const c = state.composer;
      const from = c.tray.findIndex((i) => i.lid === action.lid);
      if (from < 0 || !c.tray.length) return state;
      const tray = moveInTray(c.tray, from, action.to);
      return tray === c.tray ? state : { ...state, composer: { ...c, tray } };
    }
    case "tray/slot": {
      const composer = changeSlot(state.composer, action.lid, action.slot);
      return composer === state.composer ? state : { ...state, composer };
    }
    case "tray/include": {
      let composer = state.composer;
      for (const lid of action.lids) composer = patchItem(composer, lid, (i) => ({ ...i, included: action.included }));
      return composer === state.composer ? state : { ...state, composer };
    }
    case "tray/role": {
      const role = action.role.slice(0, MAX_ROLE_CHARS);
      const composer = patchItem(state.composer, action.lid, (i) => ({ ...i, role }));
      return composer === state.composer ? state : { ...state, composer };
    }

    /* ---------- цена ---------- */
    case "quote/loading":
      return { ...state, quote: { ...state.quote, status: "loading", key: action.key, error: null } };
    case "quote/loaded":
      // Ответ на устаревшее тело (человек уже поменял текст) — не наш.
      if (action.key !== state.quote.key) return state;
      return { ...state, quote: { status: "ready", key: action.key, data: action.quote, error: null } };
    case "quote/failed":
      if (action.key !== state.quote.key) return state;
      return { ...state, quote: { ...state.quote, status: "error", error: action.error } };

    /* ---------- запуск ---------- */
    case "run/start":
      return { ...state, run: { status: "sending", clientRequestId: action.clientRequestId, error: null } };
    case "run/done": {
      const r = action.response;
      const run = { status: "idle" as const, clientRequestId: null, error: null };
      // Ответ пришёл, когда человек уже открыл другой проект, — ленту не трогаем.
      const ours = !state.project || state.project.uid === r.project.uid;
      const projects = upsertProjectList(state.projects, r.project);
      let library = state.library;
      if (r.asset) library = upsertLibrary(library, r.asset);
      if (!ours) {
        const takes = new Map(state.takes);
        takes.set(r.take.uid, mergeTake(takes.get(r.take.uid), r.take));
        return { ...state, run, projects, library, takes };
      }
      const wasNew = !state.project;
      const shots = new Map(state.shots);
      const takes = new Map(state.takes);
      putShot(shots, takes, r.shot);
      const take = mergeTake(takes.get(r.take.uid), r.take);
      takes.set(take.uid, take);
      putTakeIntoShot(shots, take);
      return {
        ...state,
        run,
        project: r.project,
        projects,
        library,
        shots,
        takes,
        order: sortOrder(shots),
        // Новый проект только что создан: раньше этого кадра в нём ничего нет.
        feed: wasNew ? { next: null, loading: false, loaded: true } : state.feed,
      };
    }
    case "run/failed":
      return { ...state, run: { status: "idle", clientRequestId: null, error: action.error } };

    /* ---------- библиотека ---------- */
    case "library/loading":
      return { ...state, library: { ...state.library, loading: true } };
    case "library/loaded": {
      const incoming = action.page.items || [];
      let items: AssetJSON[];
      if (action.append) {
        const seen = new Set(state.library.items.map((a) => a.uid));
        items = [...state.library.items, ...incoming.filter((a) => !seen.has(a.uid))];
      } else items = incoming;
      return { ...state, library: { ...state.library, items, next: action.page.next ?? null, loading: false, loaded: true } };
    }
    case "library/filter":
      if (state.library.filter === action.filter) return state;
      return { ...state, library: emptyLibrary(action.filter) };
    case "library/upsert": {
      const library = upsertLibrary(state.library, action.asset);
      const composer = action.asset.kind === "image" ? syncChipsWithAsset(state.composer, action.asset) : state.composer;
      return library === state.library && composer === state.composer ? state : { ...state, library, composer };
    }
    case "library/remove": {
      const library = { ...state.library, items: state.library.items.filter((a) => a.uid !== action.uid) };
      // Удалённый материал в запросе — красный чип «удалён» (§9.6), запуск его не возьмёт.
      const composer = patchByAsset(state.composer, action.uid, (i) => ({ ...i, status: "deleted" }));
      return { ...state, library, composer };
    }

    /* ---------- интерфейс ---------- */
    case "ui/panel": {
      const panel: PanelName = action.panel;
      const open = action.open ?? !state.ui.panels[panel];
      if (state.ui.panels[panel] === open) return state;
      return { ...state, ui: { ...state.ui, panels: { ...state.ui.panels, [panel]: open } } };
    }
    case "ui/paywall":
      return { ...state, ui: { ...state.ui, paywall: action.paywall } };
    case "ui/auth":
      return state.ui.auth === action.open ? state : { ...state, ui: { ...state.ui, auth: action.open } };
    case "ui/topup":
      return state.ui.topup === action.open ? state : { ...state, ui: { ...state.ui, topup: action.open } };
    case "ui/toast":
      return { ...state, ui: { ...state.ui, toasts: pushToast(state.ui.toasts, action.toast) } };
    case "ui/toastDismiss": {
      const toasts = state.ui.toasts.filter((t) => t.id !== action.id);
      return toasts.length === state.ui.toasts.length ? state : { ...state, ui: { ...state.ui, toasts } };
    }
    case "ui/focusTake":
      return state.ui.focusTake === action.take ? state : { ...state, ui: { ...state.ui, focusTake: action.take } };
    case "ui/fullscreen":
      return state.ui.fullscreen === action.open ? state : { ...state, ui: { ...state.ui, fullscreen: action.open } };

    default: {
      // Новый тип действия без обработки — tsc покажет здесь.
      const never: never = action;
      void never;
      return state;
    }
  }
}

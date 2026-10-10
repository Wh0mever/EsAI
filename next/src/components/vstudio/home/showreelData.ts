/**
 * Карусель первого экрана: из двух публичных ответов сервера — один ряд кадров.
 *
 * Источники (§0.6): работы самой видеостудии (GET vstudio/showcase/, их
 * отбирает владелец в админке) и превью сцен мультстудии (GET cartoon/presets/).
 * В карусели они не смешиваются: либо ролики студии — сначала по одному на
 * сценарий (scenarios.ts), затем остальные, всего столько, сколько задал
 * владелец (reel_size, от 5 до 48), — либо, пока их меньше пяти, сцены
 * мультстудии со своей подписью и дорогой в /studio. Чужого и постановочного
 * здесь нет.
 *
 * Ответы разбираем как «чужие руки»: поле не того типа или карточка без
 * единого кадра не должны уронить первый экран — такая запись просто
 * пропускается. Сервер может быть и прежней версии: без needs_photo,
 * start_frame_url и reel_size, со старыми ключами сценариев. Модуль чистый
 * (без React и сети): его проверяет node-тест home.test.mjs.
 */
import { SCENARIOS, isScenario, type ScenarioKey } from "./scenarios";

export type ReelItem = {
  /** "vs:12" — работа видеостудии, "ct:<slug>" — сцена мультстудии. */
  id: string;
  source: "vstudio" | "cartoon";
  kind: "video" | "image";
  title: string;
  /** Видеостудия — название модели; мультстудия — подзаголовок сцены. */
  subtitle: string;
  /** Сценарий карусели; null — «Другое», незнакомое значение и сцены мультстудии. */
  scenario: ScenarioKey | null;
  /** Мультстудия — slug раздела; видеостудия — значение сервера как есть (для подписи и порядка есть scenario). */
  category: string;
  /** Лёгкий ролик для ленты; у картинок — null. */
  video: string | null;
  poster: string | null;
  aspect: string;
  duration: number | null;
  /** Куда ведёт карточка мультстудии ("/studio"); у работ видеостудии — null. */
  href: string | null;
  modelId: string | null;
  /** Текст запроса — только если владелец разрешил его показывать. */
  prompt: string | null;
  params: { duration?: number; resolution?: string; aspect_ratio?: string } | null;
  /** Работа снята со своими картинками: чтобы снять похожее, человеку нужно добавить своё фото. */
  needsPhoto: boolean;
  /** Фото, с которого начинался ролик (Image → Video); приходит вместе с запросом. */
  startFrame: string | null;
  /** Выбор редакции мультстудии. */
  pick: boolean;
};

export type ShowreelData = {
  /** Карусель: кадры одного источника. Роликов студии — сколько задал владелец (до REEL_MAX), сцен мультстудии — до REEL_SIZE. */
  reel: ReelItem[];
  /** Чьи кадры в карусели; null — показать нечего. */
  source: ReelItem["source"] | null;
  /** Постер сцены мультстудии — для карточки «Мультстудия» в инструментах. */
  cartoonPoster: string | null;
};

/** Размер карусели, пока владелец не задал свой (и у сервера, который его ещё не присылает). */
export const REEL_SIZE = 12;
/** Меньше кадров — у карусели нет «крыльев» по обе стороны от активного. */
export const REEL_MIN = 5;
/** Больше работ сервер сайту не отдаёт (showcase.MAX_PUBLIC). */
export const REEL_MAX = 48;
export const CARTOON_HREF = "/studio";

export const EMPTY_SHOWREEL: ShowreelData = { reel: [], source: null, cartoonPoster: null };

/** Ключи сценариев, которые отдаёт сервер прежней версии. */
const LEGACY_SCENARIOS: ReadonlyMap<string, ScenarioKey> = new Map([
  ["social", "vertical"],
  ["anime", "anim"],
]);

type Row = Record<string, unknown>;

const isRow = (v: unknown): v is Row => typeof v === "object" && v !== null && !Array.isArray(v);
const rows = (v: unknown): Row[] => (Array.isArray(v) ? v.filter(isRow) : []);
const text = (v: unknown): string => (typeof v === "string" ? v.trim() : "");
/** Адрес файла: непустая строка, иначе null (сервер отдаёт и null, и ""). */
const url = (v: unknown): string | null => text(v) || null;
const positive = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) && v > 0 ? v : null);

function showcaseParams(v: unknown): ReelItem["params"] {
  if (!isRow(v)) return null;
  const out: NonNullable<ReelItem["params"]> = {};
  const duration = positive(v.duration);
  if (duration !== null) out.duration = duration;
  if (text(v.resolution)) out.resolution = text(v.resolution);
  if (text(v.aspect_ratio)) out.aspect_ratio = text(v.aspect_ratio);
  return Object.keys(out).length ? out : null;
}

function scenarioOf(category: string): ScenarioKey | null {
  return isScenario(category) ? category : (LEGACY_SCENARIOS.get(category) ?? null);
}

/**
 * Размер карусели роликов студии — настройка владельца (vstudio_reel_size).
 * Годится только целое от REEL_MIN до REEL_MAX. Всё остальное — строка, дробь,
 * число за границами, пустота — даёт REEL_SIZE, а не ближайшую границу: такое
 * значение говорит, что настройки нет, а не что владелец просил «побольше».
 */
export function clampReelSize(value: unknown): number {
  const ok = typeof value === "number" && Number.isInteger(value) && value >= REEL_MIN && value <= REEL_MAX;
  return ok ? value : REEL_SIZE;
}

/** Размер карусели из ответа GET vstudio/showcase/ (reel_size); сервер прежней версии его не присылает. */
export function reelSizeOf(payload: unknown): number {
  return clampReelSize(isRow(payload) ? payload.reel_size : undefined);
}

/** Ответ GET vstudio/showcase/ → карточки. Всё непонятное пропускаем. */
export function studioItems(payload: unknown): ReelItem[] {
  const out: ReelItem[] = [];
  const seen = new Set<string>();
  for (const row of rows(isRow(payload) ? payload.items : null)) {
    if (typeof row.id !== "number" && typeof row.id !== "string") continue;
    const id = `vs:${row.id}`;
    if (seen.has(id)) continue;
    const kind = row.kind === "image" ? "image" : "video";
    const video = kind === "video" ? url(row.video_url) : null;
    const poster = url(row.poster_url) ?? url(row.image_url);
    if (!video && !poster) continue;
    const model = isRow(row.model) ? row.model : null;
    const params = showcaseParams(row.params);
    const category = text(row.category) || "other";
    const startFrame = kind === "video" ? url(row.start_frame_url) : null;
    seen.add(id);
    out.push({
      id,
      source: "vstudio",
      kind,
      title: text(row.title),
      subtitle: text(model?.name),
      scenario: scenarioOf(category),
      category,
      video,
      poster,
      aspect: text(row.aspect_ratio) || params?.aspect_ratio || "16:9",
      duration: positive(row.duration_s) ?? params?.duration ?? null,
      href: null,
      modelId: text(model?.id) || null,
      prompt: text(row.prompt) || null,
      params,
      // Первый кадр сервер отдаёт только у работы, снятой с фото, — флаг мог и не дойти.
      needsPhoto: row.needs_photo === true || startFrame !== null,
      startFrame,
      pick: false,
    });
  }
  return out;
}

/** Ответ GET cartoon/presets/ → карточки сцен (в порядке сервера). */
export function cartoonItems(payload: unknown): ReelItem[] {
  const items: ReelItem[] = [];
  const seen = new Set<string>();
  for (const row of rows(isRow(payload) ? payload.presets : null)) {
    const key = text(row.slug) || (typeof row.id === "number" ? String(row.id) : "");
    const id = `ct:${key}`;
    if (!key || seen.has(id)) continue;
    const video = url(row.preview_video);
    const poster = url(row.preview_poster);
    if (!video && !poster) continue;
    seen.add(id);
    items.push({
      id,
      source: "cartoon",
      kind: "video",
      title: text(row.title),
      subtitle: text(row.subtitle),
      scenario: null,
      category: text(row.category),
      video,
      poster,
      aspect: text(row.aspect_ratio) || "16:9",
      duration: positive(row.duration),
      href: CARTOON_HREF,
      modelId: null,
      prompt: null,
      params: null,
      needsPhoto: false,
      startFrame: null,
      pick: row.is_pick === true,
    });
  }
  return items;
}

/**
 * Ролики студии для карусели: сначала по одному на сценарий, в порядке списка
 * сценариев, затем остальные — как их расставил владелец; всего не больше size.
 * Картинки в карусель не идут: она про видео.
 */
function studioReel(studio: ReelItem[], size: number): ReelItem[] {
  const videos = studio.filter((item) => item.kind === "video");
  const lead = new Map<ScenarioKey, ReelItem>();
  for (const item of videos) {
    if (item.scenario && !lead.has(item.scenario)) lead.set(item.scenario, item);
  }
  const first = SCENARIOS.flatMap((key) => lead.get(key) ?? []);
  const taken = new Set(first);
  return [...first, ...videos.filter((item) => !taken.has(item))].slice(0, size);
}

/**
 * Сцены мультстудии для карусели: выбор редакции, не больше REEL_SIZE — размер,
 * который задаёт владелец, их не касается: он про ролики студии. Если
 * отмеченных сцен мало и карусель вышла бы без «крыльев», добираем до REEL_MIN
 * обычными сценами: сначала из разделов, которых в карусели ещё нет, — чтобы
 * рядом не стояли пять похожих кадров.
 */
function cartoonReel(cartoon: ReelItem[]): ReelItem[] {
  const reel = cartoon.filter((item) => item.pick).slice(0, REEL_SIZE);
  if (reel.length >= REEL_MIN) return reel;

  // В карусели соседи показывают только постер — сцены без него не берём.
  const rest = cartoon.filter((item) => !item.pick && item.poster);
  const used = new Set(reel.map((item) => item.category));
  for (const fresh of [true, false]) {
    for (const item of rest) {
      if (reel.length >= REEL_MIN) return reel;
      if (reel.includes(item) || (fresh && used.has(item.category))) continue;
      reel.push(item);
      used.add(item.category);
    }
  }
  return reel;
}

/**
 * size — сколько роликов студии встаёт в карусель (reelSizeOf). Негодный размер
 * здесь тоже даёт REEL_SIZE: карусель короче REEL_MIN ушла бы к мультстудии,
 * хотя своих роликов хватает.
 */
export function buildShowreel(studio: ReelItem[], cartoon: ReelItem[], size: number = REEL_SIZE): ShowreelData {
  const own = studioReel(studio, clampReelSize(size));
  const scenes = cartoonReel(cartoon);
  // Роликов студии мало — карусель целиком отдаём мультстудии. Но если сцен
  // нет вовсе (их запрос не ответил), два своих ролика лучше пустого экрана.
  const ownReel = own.length >= REEL_MIN || (own.length > 0 && scenes.length === 0);
  const reel = ownReel ? own : scenes;

  // Постер берём из карусели, когда она мультстудии: он там уже загружен.
  const withPoster = (item: ReelItem) => item.poster !== null;
  const scene = (ownReel ? undefined : scenes.find(withPoster)) ?? cartoon.find(withPoster);

  return {
    reel,
    source: reel.length === 0 ? null : ownReel ? "vstudio" : "cartoon",
    cartoonPoster: scene?.poster ?? null,
  };
}

/**
 * Витрина первого экрана: из двух публичных ответов сервера — один список.
 *
 * Источники (§0.6): работы самой видеостудии (GET vstudio/showcase/, их
 * отбирает владелец в админке) и превью сцен мультстудии (GET cartoon/presets/).
 * Чужого и постановочного здесь нет: каждая карточка честно подписана своим
 * источником, а сцены мультстудии ведут в /studio.
 *
 * Ответы разбираем как «чужие руки»: поле не того типа или карточка без
 * единого кадра не должны уронить первый экран — такая запись просто
 * пропускается. Модуль чистый (без React и сети): его проверяет node-тест
 * home.test.mjs.
 */

export type ReelItem = {
  /** "vs:12" — работа видеостудии, "ct:<slug>" — сцена мультстудии. */
  id: string;
  source: "vstudio" | "cartoon";
  kind: "video" | "image";
  title: string;
  /** Видеостудия — название модели; мультстудия — подзаголовок сцены. */
  subtitle: string;
  /** Видеостудия: film | ad | social | anime | music | other; мультстудия — slug раздела. */
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
  /** Выбор редакции мультстудии. */
  pick: boolean;
};

export type ReelCategory = { slug: string; title: string; count: number };

export type ShowreelData = {
  /** Карусель: до REEL_SIZE кадров. */
  reel: ReelItem[];
  /** Галерея: работы видеостудии, затем все сцены мультстудии. */
  all: ReelItem[];
  /** Разделы мультстудии, в которых есть сцены, — от самых полных. */
  categories: ReelCategory[];
  hasStudio: boolean;
};

export const REEL_SIZE = 12;
/** Меньше кадров — у карусели нет «крыльев» по обе стороны от активного. */
export const REEL_MIN = 5;
export const CARTOON_HREF = "/studio";

export const EMPTY_SHOWREEL: ShowreelData = { reel: [], all: [], categories: [], hasStudio: false };

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
    seen.add(id);
    out.push({
      id,
      source: "vstudio",
      kind,
      title: text(row.title),
      subtitle: text(model?.name),
      category: text(row.category) || "other",
      video,
      poster,
      aspect: text(row.aspect_ratio) || params?.aspect_ratio || "16:9",
      duration: positive(row.duration_s) ?? params?.duration ?? null,
      href: null,
      modelId: text(model?.id) || null,
      prompt: text(row.prompt) || null,
      params,
      pick: false,
    });
  }
  return out;
}

/** Ответ GET cartoon/presets/ → карточки сцен и названия разделов (в порядке сервера). */
export function cartoonItems(payload: unknown): { items: ReelItem[]; titles: Map<string, string> } {
  const data = isRow(payload) ? payload : {};
  const titles = new Map<string, string>();
  for (const c of rows(data.categories)) {
    const slug = text(c.slug);
    if (slug && text(c.title)) titles.set(slug, text(c.title));
  }
  const items: ReelItem[] = [];
  const seen = new Set<string>();
  for (const row of rows(data.presets)) {
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
      category: text(row.category),
      video,
      poster,
      aspect: text(row.aspect_ratio) || "16:9",
      duration: positive(row.duration),
      href: CARTOON_HREF,
      modelId: null,
      prompt: null,
      params: null,
      pick: row.is_pick === true,
    });
  }
  return { items, titles };
}

/**
 * Карусель: работы видеостудии, за ними выбор редакции мультстудии — пока не
 * наберётся REEL_SIZE. Если отмеченных сцен мало и карусель вышла бы без
 * «крыльев», добираем до REEL_MIN обычными сценами: сначала из разделов,
 * которых в карусели ещё нет, — чтобы рядом не стояли пять похожих кадров.
 */
function pickReel(studio: ReelItem[], cartoon: ReelItem[]): ReelItem[] {
  const reel = studio.slice(0, REEL_SIZE);
  for (const item of cartoon) {
    if (reel.length >= REEL_SIZE) break;
    if (item.pick) reel.push(item);
  }
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

export function buildShowreel(
  studio: ReelItem[],
  cartoon: ReelItem[],
  titles: ReadonlyMap<string, string> = new Map(),
): ShowreelData {
  const counts = new Map<string, number>();
  for (const item of cartoon) {
    if (item.category) counts.set(item.category, (counts.get(item.category) ?? 0) + 1);
  }
  // Раздел без названия вкладкой не станет — показать на ней нечего.
  const categories: ReelCategory[] = [...counts]
    .filter(([slug]) => titles.has(slug))
    .map(([slug, count]) => ({ slug, title: titles.get(slug) ?? slug, count }))
    .sort((a, b) => b.count - a.count);

  return {
    reel: pickReel(studio, cartoon),
    all: [...studio, ...cartoon],
    categories,
    hasStudio: studio.length > 0,
  };
}

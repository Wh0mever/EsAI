/**
 * Сцены мультстудии в панели: весь контракт с сервером — в этом файле
 * (core/adminapi/studio_scenes.py, строки собирает core/cartoon/panel.py).
 *
 *   GET    manage/studio/scenes/                     → { count, results: [сцена], sections: [раздел],
 *                                                        audiences: [{ key, label }], aspects: [..], limits }
 *   POST   manage/studio/scenes/                     { title, scene_prompt, … } → сцена (201)
 *   GET    manage/studio/scenes/<id>/                → сцена (опрос сборки превью)
 *   PATCH  manage/studio/scenes/<id>/                { любые поля сцены } → сцена
 *   DELETE manage/studio/scenes/<id>/                → 204; 409 — сцену уже взяли в мультфильмы
 *   POST   manage/studio/scenes/<id>/preview/        multipart file=<mp4> → сцена (202, сборка в фоне)
 *   POST   manage/studio/scenes/<id>/preview/rebuild/ → сцена (202)
 *   POST   manage/studio/sections/                   { title, … } → раздел (201)
 *   PATCH  manage/studio/sections/<id>/              { любые поля раздела } → раздел
 *   POST   manage/studio/works/scene/<id>/publish-scene/ → { created, preset: сцена } (201 / 200)
 *
 * Страница работает с Scene и Section и имён полей сервера не знает. Ответы
 * разбираем как «чужие руки»: запись без id или с полем не того типа страницу
 * не роняет. Сервер отдаёт библиотеку целиком, без страниц, поэтому фильтры
 * считаются здесь же (matchesScene) — тем же правилом, что его filter_scenes:
 * чипы переключаются без запросов, а правка строки сразу видна в списке.
 * Модуль чистый (без React и сети) — его проверяет scenesAdmin.test.mjs.
 */

export const SCENES_PATH = "manage/studio/scenes/";
export const scenePath = (id: number): string => `${SCENES_PATH}${id}/`;
export const previewPath = (id: number): string => `${SCENES_PATH}${id}/preview/`;
export const rebuildPath = (id: number): string => `${SCENES_PATH}${id}/preview/rebuild/`;
export const SECTIONS_PATH = "manage/studio/sections/";
export const sectionPath = (id: number): string => `${SECTIONS_PATH}${id}/`;
export const publishScenePath = (workId: number): string => `manage/studio/works/scene/${workId}/publish-scene/`;

/** Страница сцен с открытой сценой: туда ведёт «Опубликовать как новую сцену» из «Работ». */
export const SCENES_PAGE = "/admin-new/studio-scenes";
export const sceneLink = (id: number): string => `${SCENES_PAGE}?scene=${id}`;

/** Номер сцены из ?scene= — открыть её сразу; null — не задан или не номер. */
export function sceneFromParams(params: { get(name: string): string | null } | null | undefined): number | null {
  const raw = params?.get("scene")?.trim() ?? "";
  return /^\d+$/.test(raw) && Number(raw) > 0 ? Number(raw) : null;
}

/* ------------------------------------------------------------------ */
/* Типы                                                                */
/* ------------------------------------------------------------------ */

export type Audience = "kids" | "adults";
export const isAudience = (v: unknown): v is Audience => v === "kids" || v === "adults";

/** Почему сцену не видно в библиотеке; live — видна. Тот же фильтр, что у публичного cartoon/presets/. */
export type SceneState = "live" | "unpublished" | "no_preview" | "section_hidden";
const SCENE_STATES: readonly SceneState[] = ["live", "unpublished", "no_preview", "section_hidden"];

/** none — ролика нет; building — собираются копии; ready — всё на месте; partial — копий не хватает. */
export type PreviewState = "none" | "building" | "ready" | "partial";
const PREVIEW_STATES: readonly PreviewState[] = ["none", "building", "ready", "partial"];

export type ScenePreview = {
  state: PreviewState;
  /** Почему сборка не удалась — словами сервера. */
  notes: string[];
  /** Загруженный ролик целиком. */
  video: string | null;
  /** Лёгкая копия для ленты (480 px, без звука). */
  clip: string | null;
  poster: string | null;
  /** Лёгкая обложка для сетки. */
  thumb: string | null;
};

export type Scene = {
  id: number;
  slug: string;
  title: string;
  titleEn: string;
  titleKg: string;
  subtitle: string;
  subtitleEn: string;
  subtitleKg: string;
  /** Раздел библиотеки; null — без раздела (видна только во «Всех»). */
  sectionId: number | null;
  audience: Audience;
  /** «Выбор EsAI» — подборка наверху библиотеки. */
  pick: boolean;
  sort: number;
  /** Опубликована (is_active). Видна ли на сайте — в state. */
  published: boolean;
  aspect: string;
  duration: number;
  /** Английский промпт кадра: герой в нём — словом character. */
  scenePrompt: string;
  /** Английский промпт движения; пусто — возьмётся промпт сцены. */
  motionPrompt: string;
  state: SceneState;
  preview: ScenePreview;
  /** Цена сцены для пользователя, кредитов; null — сервер не посчитал. */
  credits: number | null;
  /** В скольких сценах мультфильмов её уже взяли. */
  usedIn: number;
  canDelete: boolean;
  createdAt: string;
};

export type Section = {
  id: number;
  slug: string;
  title: string;
  titleEn: string;
  titleKg: string;
  emoji: string;
  sort: number;
  /** Раздел показан на сайте; скрытый прячет и свои сцены. */
  visible: boolean;
  /** Сцен в разделе всего и опубликованных с превью. */
  scenes: number;
  published: number;
};

export type AudienceOption = { key: Audience; label: string };

/** Границы полей — те же, что проверяет сервер (panel.limits). */
export type Limits = {
  titleMax: number;
  subtitleMax: number;
  slugMax: number;
  sectionTitleMax: number;
  emojiMax: number;
  scenePromptMax: number;
  motionPromptMax: number;
  sortMax: number;
  durationMin: number;
  durationMax: number;
  durationDefault: number;
  previewMaxBytes: number;
  previewMinSeconds: number;
  previewMaxSeconds: number;
};

/** Запасные границы: сервер присылает свои, эти — на случай ответа без них. */
export const DEFAULT_LIMITS: Limits = {
  titleMax: 120,
  subtitleMax: 160,
  slugMax: 140,
  sectionTitleMax: 80,
  emojiMax: 8,
  scenePromptMax: 2000,
  motionPromptMax: 1000,
  sortMax: 100_000,
  durationMin: 2,
  durationMax: 15,
  durationDefault: 5,
  previewMaxBytes: 24 * 1024 * 1024,
  previewMinSeconds: 1,
  previewMaxSeconds: 20,
};

/** Запасной список: аудитории присылает сервер, этот — на случай ответа без них. */
const AUDIENCES: AudienceOption[] = [
  { key: "kids", label: "Для детей" },
  { key: "adults", label: "Для взрослых" },
];

const ASPECTS = ["16:9", "9:16", "1:1"];

export type SceneList = {
  scenes: Scene[];
  sections: Section[];
  audiences: AudienceOption[];
  aspects: string[];
  limits: Limits;
};

/* ------------------------------------------------------------------ */
/* Разбор ответов                                                      */
/* ------------------------------------------------------------------ */

type Row = Record<string, unknown>;

const isRow = (v: unknown): v is Row => typeof v === "object" && v !== null && !Array.isArray(v);
const rows = (v: unknown): Row[] => (Array.isArray(v) ? v.filter(isRow) : []);
const text = (v: unknown): string => (typeof v === "string" ? v.trim() : "");
const url = (v: unknown): string | null => text(v) || null;
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const int = (v: unknown): number | null => {
  const n = num(v);
  return n !== null && Number.isInteger(n) ? n : null;
};

function parsePreview(value: unknown): ScenePreview {
  const row = isRow(value) ? value : {};
  const video = url(row.video);
  const state = PREVIEW_STATES.find((s) => s === row.state) ?? (video ? "partial" : "none");
  return {
    state,
    notes: Array.isArray(row.notes) ? row.notes.map(text).filter(Boolean) : [],
    video,
    clip: url(row.clip),
    poster: url(row.poster),
    thumb: url(row.thumb),
  };
}

/** Одна сцена — строка списка и ответ POST/PATCH/загрузки. */
export function parseScene(payload: unknown): Scene | null {
  if (!isRow(payload)) return null;
  const id = int(payload.id);
  if (id === null) return null;
  const published = payload.is_active === true;
  const used = int(payload.used_in);
  return {
    id,
    slug: text(payload.slug),
    title: text(payload.title),
    titleEn: text(payload.title_en),
    titleKg: text(payload.title_kg),
    subtitle: text(payload.subtitle),
    subtitleEn: text(payload.subtitle_en),
    subtitleKg: text(payload.subtitle_kg),
    sectionId: int(payload.section_id),
    audience: isAudience(payload.audience) ? payload.audience : "adults",
    pick: payload.is_pick === true,
    sort: int(payload.sort_order) ?? 0,
    published,
    aspect: text(payload.aspect_ratio) || "16:9",
    duration: int(payload.duration) ?? DEFAULT_LIMITS.durationDefault,
    scenePrompt: text(payload.scene_prompt),
    motionPrompt: text(payload.motion_prompt),
    state: SCENE_STATES.find((s) => s === payload.state) ?? (published ? "live" : "unpublished"),
    preview: parsePreview(payload.preview),
    credits: int(payload.credits),
    usedIn: used !== null && used > 0 ? used : 0,
    // Не сказано, можно ли удалить, — не обещаем: отказ сервера хуже серой кнопки.
    canDelete: payload.can_delete === true,
    createdAt: text(payload.created_at),
  };
}

export function parseSection(payload: unknown): Section | null {
  if (!isRow(payload)) return null;
  const id = int(payload.id);
  if (id === null) return null;
  return {
    id,
    slug: text(payload.slug),
    title: text(payload.title),
    titleEn: text(payload.title_en),
    titleKg: text(payload.title_kg),
    emoji: text(payload.emoji),
    sort: int(payload.sort_order) ?? 0,
    visible: payload.is_active !== false,
    scenes: Math.max(int(payload.scenes) ?? 0, 0),
    published: Math.max(int(payload.published) ?? 0, 0),
  };
}

/** Без повторов по id: строка, пришедшая дважды, не должна раздвоиться в списке. */
function unique<T extends { id: number }>(list: T[]): T[] {
  const seen = new Set<number>();
  const out: T[] = [];
  for (const item of list) {
    if (seen.has(item.id)) continue;
    seen.add(item.id);
    out.push(item);
  }
  return out;
}

export function parseSections(value: unknown): Section[] {
  return unique(rows(value).map(parseSection).filter((s): s is Section => s !== null));
}

/** Аудитории с сервера, с его подписями. Незнакомый ключ сервер не примет — такой список не годится. */
function parseAudiences(value: unknown): AudienceOption[] {
  const out: AudienceOption[] = [];
  for (const row of rows(value)) {
    const key = row.key;
    if (!isAudience(key)) return AUDIENCES;
    if (!out.some((o) => o.key === key)) out.push({ key, label: text(row.label) || key });
  }
  return out.length ? out : AUDIENCES;
}

function parseLimits(value: unknown): Limits {
  const row = isRow(value) ? value : {};
  const pick = (key: string, fallback: number): number => {
    const n = int(row[key]);
    return n !== null && n > 0 ? n : fallback;
  };
  const d = DEFAULT_LIMITS;
  const limits: Limits = {
    titleMax: pick("title_max", d.titleMax),
    subtitleMax: pick("subtitle_max", d.subtitleMax),
    slugMax: pick("slug_max", d.slugMax),
    sectionTitleMax: pick("section_title_max", d.sectionTitleMax),
    emojiMax: pick("emoji_max", d.emojiMax),
    scenePromptMax: pick("scene_prompt_max", d.scenePromptMax),
    motionPromptMax: pick("motion_prompt_max", d.motionPromptMax),
    sortMax: pick("sort_max", d.sortMax),
    durationMin: pick("duration_min", d.durationMin),
    durationMax: pick("duration_max", d.durationMax),
    durationDefault: pick("duration_default", d.durationDefault),
    previewMaxBytes: pick("preview_max_bytes", d.previewMaxBytes),
    previewMinSeconds: pick("preview_min_seconds", d.previewMinSeconds),
    previewMaxSeconds: pick("preview_max_seconds", d.previewMaxSeconds),
  };
  // Границы длительности, которые противоречат друг другу, — берём свои.
  const sane =
    limits.durationMin <= limits.durationDefault &&
    limits.durationDefault <= limits.durationMax &&
    limits.previewMinSeconds <= limits.previewMaxSeconds;
  if (sane) return limits;
  const { durationMin, durationMax, durationDefault, previewMinSeconds, previewMaxSeconds } = d;
  return { ...limits, durationMin, durationMax, durationDefault, previewMinSeconds, previewMaxSeconds };
}

/** Ответ GET; null — вместо панели ответил кто-то другой (страница nginx, не JSON). */
export function parseList(payload: unknown): SceneList | null {
  if (!isRow(payload) || !Array.isArray(payload.results)) return null;
  const aspects = Array.isArray(payload.aspects) ? payload.aspects.map(text).filter(Boolean) : [];
  return {
    scenes: unique(rows(payload.results).map(parseScene).filter((s): s is Scene => s !== null)),
    sections: parseSections(payload.sections),
    audiences: parseAudiences(payload.audiences),
    aspects: aspects.length ? [...new Set(aspects)] : ASPECTS,
    limits: parseLimits(payload.limits),
  };
}

/** Ответ «Опубликовать как новую сцену»: created=false — сцена уже была создана раньше. */
export function parsePublished(payload: unknown): { created: boolean; scene: Scene } | null {
  if (!isRow(payload)) return null;
  const scene = parseScene(payload.preset);
  return scene ? { created: payload.created === true, scene } : null;
}

/**
 * Текст отказа. Панель отвечает {detail}; fetchData из тела достаёт только
 * его, но и 413 nginx (страница, не JSON) человеку надо объяснить словами.
 */
export function errorText(res: { status: number; data?: unknown }, fallback: string): string {
  if (res.status === 0) return "Нет связи с сервером. Проверьте интернет и повторите.";
  if (res.status === 413) return "Файл больше, чем пропускает сервер. Сожмите или укоротите ролик.";
  if (res.status === 429) return "Слишком много запросов подряд. Подождите минуту и повторите.";
  const data = isRow(res.data) ? res.data : null;
  const told = data ? text(data.detail) || text(data.error) || text(data.message) : "";
  return told || `${fallback} (HTTP ${res.status})`;
}

/* ------------------------------------------------------------------ */
/* Фильтры и порядок                                                   */
/* ------------------------------------------------------------------ */

export type Tri = "all" | "yes" | "no";

export type Filters = {
  /** all — все; none — без раздела; число — раздел. */
  section: "all" | "none" | number;
  audience: "all" | Audience;
  published: Tri;
  pick: Tri;
  q: string;
};

export const NO_FILTERS: Filters = { section: "all", audience: "all", published: "all", pick: "all", q: "" };

export const filtersActive = (f: Filters): boolean =>
  f.section !== "all" || f.audience !== "all" || f.published !== "all" || f.pick !== "all" || f.q.trim() !== "";

const fold = (s: string): string => s.toLocaleLowerCase("ru");

const tri = (want: Tri, value: boolean): boolean => want === "all" || value === (want === "yes");

/**
 * Подходит ли сцена под фильтры — как у сервера (panel.filter_scenes):
 * «Опубликована» — флаг публикации, а не «видна на сайте»; поиск — по
 * названиям на трёх языках, подписи, коду и промпту сцены, без регистра.
 */
export function matchesScene(scene: Scene, f: Filters): boolean {
  if (f.section === "none" ? scene.sectionId !== null : f.section !== "all" && scene.sectionId !== f.section) {
    return false;
  }
  if (f.audience !== "all" && scene.audience !== f.audience) return false;
  if (!tri(f.published, scene.published) || !tri(f.pick, scene.pick)) return false;
  const q = fold(f.q.trim().slice(0, 200));
  if (!q) return true;
  return [scene.title, scene.titleEn, scene.titleKg, scene.subtitle, scene.slug, scene.scenePrompt].some((field) =>
    fold(field).includes(q),
  );
}

export const filterScenes = (scenes: readonly Scene[], f: Filters): Scene[] => scenes.filter((s) => matchesScene(s, f));

export type SceneGroup = { section: Section | null; scenes: Scene[] };

const byOrder = (a: { sort: number; id: number }, b: { sort: number; id: number }): number =>
  a.sort - b.sort || a.id - b.id;

/** Разделы в порядке библиотеки: по порядку, при равном — старший раньше. */
export const sortSections = (sections: readonly Section[]): Section[] => [...sections].sort(byOrder);

/**
 * Сцены по разделам — в том порядке, в каком их показывает библиотека
 * (порядок раздела, затем порядок сцены, при равном — старшая выше).
 * «Без раздела» — в конце. Пустые разделы не выводятся.
 */
export function groupScenes(scenes: readonly Scene[], sections: readonly Section[]): SceneGroup[] {
  const known = new Map(sections.map((s) => [s.id, s]));
  const groups = new Map<number | null, Scene[]>();
  for (const scene of scenes) {
    // Раздел, которого нет в списке, — как без раздела: показать сцену важнее.
    const key = scene.sectionId !== null && known.has(scene.sectionId) ? scene.sectionId : null;
    groups.set(key, [...(groups.get(key) ?? []), scene]);
  }
  const out: SceneGroup[] = [];
  for (const section of sortSections(sections)) {
    const list = groups.get(section.id);
    if (list?.length) out.push({ section, scenes: list.sort(byOrder) });
  }
  const loose = groups.get(null);
  if (loose?.length) out.push({ section: null, scenes: loose.sort(byOrder) });
  return out;
}

/** Строка сцены после ответа сервера: та же позиция в списке, новые поля. */
export const replaceScene = (scenes: readonly Scene[], saved: Scene): Scene[] =>
  scenes.some((s) => s.id === saved.id) ? scenes.map((s) => (s.id === saved.id ? saved : s)) : [...scenes, saved];

export const replaceSection = (sections: readonly Section[], saved: Section): Section[] =>
  sections.some((s) => s.id === saved.id)
    ? sections.map((s) => (s.id === saved.id ? saved : s))
    : [...sections, saved];

/**
 * Поле раздела в списке — сразу, до ответа сервера, как у быстрых правок
 * сцен; тем же путём откат после отказа. Новое значение меняет и key поля
 * «Порядок», так что в поле не остаётся несохранённое число.
 */
export const sectionWith = (sections: readonly Section[], id: number, change: Partial<Section>): Section[] =>
  sections.map((s) => (s.id === id ? { ...s, ...change } : s));

/** Сцены, у которых сейчас собирается превью, — их панель опрашивает. */
export const buildingIds = (scenes: readonly Scene[]): number[] =>
  scenes.filter((s) => s.preview.state === "building").map((s) => s.id);

/** Итог опроса сборки: свежие строки и сцены, которых на сервере уже нет. */
export type PollResult = { fresh: Scene[]; gone: number[] };

/**
 * Опрос по одной сцене. 404 — сцену удалили в другом окне или другой
 * сотрудник: без этого её строка навсегда осталась бы «собирается», а опрос
 * спрашивал бы о ней каждые три секунды. Прочие отказы (лимит, сеть) — просто
 * спросим в следующий раз.
 */
export function pollEach(
  ids: readonly number[],
  answers: readonly { ok: boolean; status: number; data?: unknown }[],
): PollResult {
  const fresh: Scene[] = [];
  const gone: number[] = [];
  answers.forEach((res, i) => {
    const scene = res.ok ? parseScene(res.data) : null;
    if (scene) fresh.push(scene);
    else if (res.status === 404 && i < ids.length) gone.push(ids[i]);
  });
  return { fresh, gone };
}

/** Опрос всем списком: чего в нём нет — удалено. */
export const pollList = (ids: readonly number[], list: Pick<SceneList, "scenes">): PollResult => ({
  fresh: list.scenes.filter((s) => ids.includes(s.id)),
  gone: ids.filter((id) => !list.scenes.some((s) => s.id === id)),
});

/** Сцены после опроса: свежие строки на своих местах, удалённых нет. */
export function afterPoll(scenes: readonly Scene[], { fresh, gone }: PollResult): Scene[] {
  const byId = new Map(fresh.map((s) => [s.id, s]));
  return scenes.filter((s) => !gone.includes(s.id)).map((s) => byId.get(s.id) ?? s);
}

export type SceneStats = {
  total: number;
  /** Видны в библиотеке. */
  live: number;
  /** Опубликованы, но не видны: нет превью или раздел скрыт. */
  stuck: number;
  unpublished: number;
};

export function sceneStats(scenes: readonly Scene[]): SceneStats {
  const count = (test: (s: Scene) => boolean) => scenes.filter(test).length;
  return {
    total: scenes.length,
    live: count((s) => s.state === "live"),
    stuck: count((s) => s.state === "no_preview" || s.state === "section_hidden"),
    unpublished: count((s) => s.state === "unpublished"),
  };
}

export type SectionCount = { total: number; published: number };

/**
 * Сцен в каждом разделе: всего и опубликованных с превью — как считает сервер
 * (panel.sections_rows). Считаем по своему списку, а не берём его числа:
 * после правки сцены они бы устарели до перечитки.
 */
export function sectionCounts(scenes: readonly Scene[]): Map<number, SectionCount> {
  const out = new Map<number, SectionCount>();
  for (const scene of scenes) {
    if (scene.sectionId === null) continue;
    const count = out.get(scene.sectionId) ?? { total: 0, published: 0 };
    count.total += 1;
    if (scene.published && scene.preview.video) count.published += 1;
    out.set(scene.sectionId, count);
  }
  return out;
}

/**
 * После правки раздела сервер пересчитывает его счётчики, но состояние сцен
 * в списке у нас прежнее. Скрыли раздел — его опубликованные сцены с превью
 * больше не видны; показали — снова видны. Так список не врёт до перечитки.
 */
export function scenesAfterSection(scenes: readonly Scene[], section: Section): Scene[] {
  return scenes.map((scene) => {
    if (scene.sectionId !== section.id || !scene.published || scene.state === "no_preview") return scene;
    const state: SceneState = section.visible ? "live" : "section_hidden";
    return state === scene.state ? scene : { ...scene, state };
  });
}

/* ------------------------------------------------------------------ */
/* Метки                                                               */
/* ------------------------------------------------------------------ */

/** Цвет метки — те же тона, что у меток витрины (vstudio-showcase/parts.tsx). */
export type Tone = "accent" | "wait" | "fail" | "muted";
export type Label = { tone: Tone; label: string; title: string };

export function stateLabel(scene: Pick<Scene, "state">): Label {
  switch (scene.state) {
    case "live":
      return { tone: "accent", label: "В библиотеке", title: "Видна всем в библиотеке мультстудии" };
    case "unpublished":
      return {
        tone: "muted",
        label: "Не опубликована",
        title: "Посетители её не видят. Включите «Опубликована», когда названия и превью готовы",
      };
    case "no_preview":
      return {
        tone: "wait",
        label: "Нет превью",
        title: "Опубликована, но без ролика превью библиотека её не показывает — загрузите ролик",
      };
    case "section_hidden":
      return {
        tone: "wait",
        label: "Раздел скрыт",
        title: "Опубликована, но её раздел скрыт — сцены скрытого раздела на сайте не видны",
      };
  }
}

/** Метка превью; null — превью в порядке и говорить не о чем. */
export function previewLabel(preview: Pick<ScenePreview, "state" | "notes">): Label | null {
  switch (preview.state) {
    case "building":
      return {
        tone: "wait",
        label: "Собираю превью…",
        title: "Сервер делает лёгкую копию, обложку и миниатюру. Пока библиотека играет сам ролик",
      };
    case "partial":
      return {
        tone: "wait",
        label: "Превью не собрано",
        title: preview.notes.length
          ? preview.notes.join(". ")
          : "Лёгкой копии или обложки нет — лента играет сам ролик. Нажмите «Пересобрать»",
      };
    case "none":
      return { tone: "muted", label: "Без ролика", title: "Ролик превью ещё не загружен" };
    case "ready":
      return null;
  }
}

/** Что стало со сценой после «Опубликована» в строке — видна ли она теперь и почему нет. */
export function publishNote(scene: Pick<Scene, "title" | "state">): string {
  const name = `«${scene.title}»`;
  switch (scene.state) {
    case "live":
      return `В библиотеке: ${name}.`;
    case "unpublished":
      return `Снята с публикации: ${name}. Готовые мультфильмы с ней остаются целы.`;
    case "no_preview":
      return `Опубликована ${name}, но без ролика превью библиотека её не покажет — загрузите ролик.`;
    case "section_hidden":
      return `Опубликована ${name}, но её раздел скрыт — на сайте её не видно.`;
  }
}

/** Итог окна сцены: создана или сохранена, ушёл ли ролик и видна ли она теперь. */
export function savedNote(scene: Pick<Scene, "title" | "state">, how: { created: boolean; uploaded: boolean }): string {
  const parts = [how.created ? `Сцена создана: «${scene.title}».` : `Сохранено: «${scene.title}».`];
  if (how.uploaded) parts.push("Превью собирается — это пара минут.");
  if (scene.state === "no_preview" && !how.uploaded) {
    parts.push("Без ролика превью библиотека её не покажет — загрузите ролик.");
  } else if (scene.state === "section_hidden") {
    parts.push("Её раздел скрыт — на сайте сцены не видно.");
  } else if (how.created && scene.state === "unpublished") {
    parts.push("Она не опубликована: включите «Опубликована», когда всё готово.");
  } else if (how.created && scene.state === "live") {
    parts.push("Она уже видна в библиотеке.");
  }
  return parts.join(" ");
}

/** Каких переводов не хватает: на этих языках сайт покажет русский текст. */
export function missingLangs(item: {
  titleEn: string;
  titleKg: string;
  subtitle?: string;
  subtitleEn?: string;
  subtitleKg?: string;
}): string[] {
  const out: string[] = [];
  const sub = Boolean(item.subtitle);
  if (!item.titleEn || (sub && !item.subtitleEn)) out.push("EN");
  if (!item.titleKg || (sub && !item.subtitleKg)) out.push("KG");
  return out;
}

export const sectionName = (section: Pick<Section, "emoji" | "title">): string =>
  [section.emoji, section.title].filter(Boolean).join(" ");

/** Раздел в списке выбора: у скрытого — пометка, иначе сцена «пропадёт» без объяснений. */
export const sectionOption = (section: Pick<Section, "emoji" | "title" | "visible">): string =>
  section.visible ? sectionName(section) : `${sectionName(section)} (скрыт)`;

/* ------------------------------------------------------------------ */
/* Форма сцены                                                         */
/* ------------------------------------------------------------------ */

export type SceneForm = {
  title: string;
  titleEn: string;
  titleKg: string;
  subtitle: string;
  subtitleEn: string;
  subtitleKg: string;
  /** Только у новой сцены: код задаётся при создании и больше не меняется. */
  slug: string;
  sectionId: number | null;
  audience: Audience;
  pick: boolean;
  /** Как набрано; пусто у новой сцены — сервер поставит её в конец раздела. */
  sort: string;
  published: boolean;
  aspect: string;
  duration: string;
  scenePrompt: string;
  motionPrompt: string;
};

/**
 * Новая сцена: не опубликована (превью ещё нет), 5 секунд, 16:9. Раздел и
 * аудитория — из фильтров, если владелец уже смотрит на них: так новая сцена
 * встаёт туда, где её ждут.
 */
export function newSceneForm(limits: Limits, filters: Filters = NO_FILTERS): SceneForm {
  return {
    title: "",
    titleEn: "",
    titleKg: "",
    subtitle: "",
    subtitleEn: "",
    subtitleKg: "",
    slug: "",
    sectionId: typeof filters.section === "number" ? filters.section : null,
    audience: filters.audience === "all" ? "adults" : filters.audience,
    pick: false,
    sort: "",
    published: false,
    aspect: "16:9",
    duration: String(limits.durationDefault),
    scenePrompt: "",
    motionPrompt: "",
  };
}

export function formFromScene(scene: Scene): SceneForm {
  return {
    title: scene.title,
    titleEn: scene.titleEn,
    titleKg: scene.titleKg,
    subtitle: scene.subtitle,
    subtitleEn: scene.subtitleEn,
    subtitleKg: scene.subtitleKg,
    slug: scene.slug,
    sectionId: scene.sectionId,
    audience: scene.audience,
    pick: scene.pick,
    sort: String(scene.sort),
    published: scene.published,
    aspect: scene.aspect,
    duration: String(scene.duration),
    scenePrompt: scene.scenePrompt,
    motionPrompt: scene.motionPrompt,
  };
}

/** Название и подпись сервер сохраняет с одним пробелом между словами — сравниваем так же. */
const collapse = (s: string): string => s.replace(/\s+/g, " ").trim();
/** Длина как у сервера: в символах, а не в UTF-16 (эмодзи — один символ). */
export const chars = (s: string): number => Array.from(s).length;

const SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const DIGITS = /^\d+$/;

/** Целое из поля в границах; null — набрано не то. */
function typedInt(typed: string, low: number, high: number): number | null {
  const s = typed.trim();
  if (!DIGITS.test(s)) return null;
  const n = Number(s);
  return n >= low && n <= high ? n : null;
}

/** Порядок из поля: целое от 0 до sortMax; null — набрано не то. */
export const typedSort = (typed: string, limits: Pick<Limits, "sortMax">): number | null =>
  typedInt(typed, 0, limits.sortMax);

export const sortError = (limits: Pick<Limits, "sortMax">): string =>
  `Порядок — целое число от 0 до ${limits.sortMax}`;

const PROMPT_REQUIRED = "Промпт сцены обязателен: по-английски, что происходит в кадре, герой — словом character";

/**
 * Что мешает сохранить сцену; null — можно. Тексты — как у сервера: форма
 * ловит то же, что он, до запроса, а не после.
 */
export function validateScene(
  form: SceneForm,
  limits: Limits,
  aspects: readonly string[],
  creating: boolean,
): string | null {
  if (!collapse(form.title)) return "Название обязательно";
  const texts: [string, string, number][] = [
    [form.title, "Название", limits.titleMax],
    [form.titleEn, "Название (EN)", limits.titleMax],
    [form.titleKg, "Название (KG)", limits.titleMax],
    [form.subtitle, "Подпись", limits.subtitleMax],
    [form.subtitleEn, "Подпись (EN)", limits.subtitleMax],
    [form.subtitleKg, "Подпись (KG)", limits.subtitleMax],
  ];
  for (const [value, label, max] of texts) {
    if (chars(collapse(value)) > max) return `${label} длиннее ${max} символов`;
  }
  if (creating && form.slug.trim()) {
    const slug = form.slug.trim();
    if (!SLUG_RE.test(slug) || chars(slug) > limits.slugMax) {
      return `Код — латиница в нижнем регистре, цифры и дефисы, до ${limits.slugMax} символов`;
    }
  }
  if (!form.scenePrompt.trim()) return PROMPT_REQUIRED;
  if (chars(form.scenePrompt.trim()) > limits.scenePromptMax) {
    return `Промпт сцены длиннее ${limits.scenePromptMax} символов`;
  }
  if (chars(form.motionPrompt.trim()) > limits.motionPromptMax) {
    return `Промпт движения длиннее ${limits.motionPromptMax} символов`;
  }
  if (!aspects.includes(form.aspect)) return `Пропорции: ${aspects.join(", ")}`;
  if (typedInt(form.duration, limits.durationMin, limits.durationMax) === null) {
    return `Длительность — целое число секунд от ${limits.durationMin} до ${limits.durationMax}`;
  }
  // У новой сцены пустой порядок — «в конец раздела», у готовой его надо назвать.
  if ((!creating || form.sort.trim()) && typedSort(form.sort, limits) === null) return sortError(limits);
  return null;
}

const CYRILLIC = /[Ѐ-ӿ]/;
const CHARACTER = /\bcharacters?\b/i;

/**
 * Предупреждения, которые сохранять не мешают: сервер такое примет, но сцена
 * выйдет не той. Модели понимают промпт по-английски, а героя мультфильма
 * подставляют вместо слова character — без него герой в кадр не попадёт.
 */
export function sceneWarnings(form: Pick<SceneForm, "scenePrompt" | "motionPrompt">): string[] {
  const out: string[] = [];
  const prompt = form.scenePrompt.trim();
  if (prompt && !CHARACTER.test(prompt)) {
    out.push("В промпте сцены нет слова character — герой мультфильма не попадёт в кадр.");
  }
  if (CYRILLIC.test(prompt) || CYRILLIC.test(form.motionPrompt)) {
    out.push("В промптах есть русские буквы — пишите их по-английски: так их понимают модели.");
  }
  return out;
}

/** Тело POST новой сцены. Числа и флаги — настоящие: строку сервер не примет. */
export function createBody(form: SceneForm, limits: Limits): Record<string, unknown> {
  const body: Record<string, unknown> = {
    title: collapse(form.title),
    title_en: collapse(form.titleEn),
    title_kg: collapse(form.titleKg),
    subtitle: collapse(form.subtitle),
    subtitle_en: collapse(form.subtitleEn),
    subtitle_kg: collapse(form.subtitleKg),
    section_id: form.sectionId,
    audience: form.audience,
    is_pick: form.pick,
    is_active: form.published,
    aspect_ratio: form.aspect,
    duration: typedInt(form.duration, limits.durationMin, limits.durationMax) ?? limits.durationDefault,
    scene_prompt: form.scenePrompt.trim(),
    motion_prompt: form.motionPrompt.trim(),
  };
  const sort = typedSort(form.sort, limits);
  if (sort !== null) body.sort_order = sort;
  if (form.slug.trim()) body.slug = form.slug.trim();
  return body;
}

/**
 * Тело PATCH: только то, что правда поменялось. Пусто — сохранять нечего
 * (пустое тело сервер отклоняет «Нечего менять»).
 */
export function sceneChanges(scene: Scene, form: SceneForm, limits: Limits): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  const put = (key: string, before: unknown, after: unknown) => {
    if (before !== after) body[key] = after;
  };
  put("title", scene.title, collapse(form.title));
  put("title_en", scene.titleEn, collapse(form.titleEn));
  put("title_kg", scene.titleKg, collapse(form.titleKg));
  put("subtitle", scene.subtitle, collapse(form.subtitle));
  put("subtitle_en", scene.subtitleEn, collapse(form.subtitleEn));
  put("subtitle_kg", scene.subtitleKg, collapse(form.subtitleKg));
  put("section_id", scene.sectionId, form.sectionId);
  put("audience", scene.audience, form.audience);
  put("is_pick", scene.pick, form.pick);
  put("is_active", scene.published, form.published);
  put("aspect_ratio", scene.aspect, form.aspect);
  const duration = typedInt(form.duration, limits.durationMin, limits.durationMax);
  if (duration !== null) put("duration", scene.duration, duration);
  const sort = typedSort(form.sort, limits);
  if (sort !== null) put("sort_order", scene.sort, sort);
  put("scene_prompt", scene.scenePrompt, form.scenePrompt.trim());
  put("motion_prompt", scene.motionPrompt, form.motionPrompt.trim());
  return body;
}

/* ------------------------------------------------------------------ */
/* Ролик превью                                                        */
/* ------------------------------------------------------------------ */

const MB = 1024 * 1024;

/** Число с одним знаком после запятой, по-русски: 24,1. */
const decimal = (n: number): string => String(n).replace(".", ",");

/** «5 МБ», «24,1 МБ». Вверх: файл чуть больше потолка не должен выглядеть равным ему. */
export const fmtMb = (bytes: number): string => `${decimal(Math.ceil((bytes / MB) * 10) / 10)} МБ`;

/**
 * Файл, который не стоит и отправлять: не MP4 или больше потолка. Потолок
 * проверяем до запроса: выше 25 МБ nginx отвечает страницей, а не текстом
 * сервера. Длительность — отдельно (previewSecondsError), её узнаёт браузер.
 */
export function previewFileError(file: { name: string; size: number }, limits: Pick<Limits, "previewMaxBytes">): string | null {
  if (!file.name.toLowerCase().endsWith(".mp4")) return "Это не MP4 — загрузите ролик в формате MP4 (H.264)";
  if (file.size <= 0) return "Файл пустой — выберите ролик ещё раз";
  if (file.size > limits.previewMaxBytes) {
    return `Ролик весит ${fmtMb(file.size)} — больше ${Math.floor(limits.previewMaxBytes / MB)} МБ. Сожмите или укоротите его`;
  }
  return null;
}

/** null — длительность подходит или браузер её не узнал (тогда проверит сервер). */
export function previewSecondsError(
  seconds: number | null,
  limits: Pick<Limits, "previewMinSeconds" | "previewMaxSeconds">,
): string | null {
  if (seconds === null || !Number.isFinite(seconds) || seconds <= 0) return null;
  if (seconds >= limits.previewMinSeconds && seconds <= limits.previewMaxSeconds) return null;
  const shown = decimal(Math.round(seconds * 10) / 10);
  return `Ролик длится ${shown} с — нужно от ${limits.previewMinSeconds} до ${limits.previewMaxSeconds} секунд`;
}

/* ------------------------------------------------------------------ */
/* Форма раздела                                                       */
/* ------------------------------------------------------------------ */

export type SectionForm = {
  title: string;
  titleEn: string;
  titleKg: string;
  emoji: string;
  /** Как набрано; пусто у нового раздела — сервер поставит его в конец. */
  sort: string;
  visible: boolean;
};

export const newSectionForm = (): SectionForm => ({
  title: "",
  titleEn: "",
  titleKg: "",
  emoji: "",
  sort: "",
  visible: true,
});

export const formFromSection = (section: Section): SectionForm => ({
  title: section.title,
  titleEn: section.titleEn,
  titleKg: section.titleKg,
  emoji: section.emoji,
  sort: String(section.sort),
  visible: section.visible,
});

/** Значок сервер хранит без пробелов. */
const emojiOf = (s: string): string => collapse(s).replace(/ /g, "");

export function validateSection(form: SectionForm, limits: Limits, creating: boolean): string | null {
  if (!collapse(form.title)) return "Название раздела обязательно";
  const texts: [string, string][] = [
    [form.title, "Название раздела"],
    [form.titleEn, "Название раздела (EN)"],
    [form.titleKg, "Название раздела (KG)"],
  ];
  for (const [value, label] of texts) {
    if (chars(collapse(value)) > limits.sectionTitleMax) return `${label} длиннее ${limits.sectionTitleMax} символов`;
  }
  if (chars(emojiOf(form.emoji)) > limits.emojiMax) return `Значок длиннее ${limits.emojiMax} символов`;
  if ((!creating || form.sort.trim()) && typedSort(form.sort, limits) === null) return sortError(limits);
  return null;
}

export function sectionCreateBody(form: SectionForm, limits: Limits): Record<string, unknown> {
  const body: Record<string, unknown> = {
    title: collapse(form.title),
    title_en: collapse(form.titleEn),
    title_kg: collapse(form.titleKg),
    emoji: emojiOf(form.emoji),
    is_active: form.visible,
  };
  const sort = typedSort(form.sort, limits);
  if (sort !== null) body.sort_order = sort;
  return body;
}

export function sectionChanges(section: Section, form: SectionForm, limits: Limits): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  const put = (key: string, before: unknown, after: unknown) => {
    if (before !== after) body[key] = after;
  };
  put("title", section.title, collapse(form.title));
  put("title_en", section.titleEn, collapse(form.titleEn));
  put("title_kg", section.titleKg, collapse(form.titleKg));
  put("emoji", section.emoji, emojiOf(form.emoji));
  put("is_active", section.visible, form.visible);
  const sort = typedSort(form.sort, limits);
  if (sort !== null) put("sort_order", section.sort, sort);
  return body;
}

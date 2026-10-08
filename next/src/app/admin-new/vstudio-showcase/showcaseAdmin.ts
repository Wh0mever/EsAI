/**
 * Витрина видеостудии в панели: весь контракт с сервером — в этом файле
 * (core/adminapi/vstudio.py, строки собирает core/vstudio/showcase.py).
 *
 *   GET    manage/vstudio/showcase/?scope=staff|all&q=&page=
 *            → { items: [работа], candidates: { count, page_size, results: [дубль] },
 *                categories: [{ key, label }], public_limit }
 *   POST   manage/vstudio/showcase/       { take, title, category, show_prompt, sort? } → работа
 *   PATCH  manage/vstudio/showcase/<id>/  { title?, category?, sort?, is_active?, show_prompt? } → работа
 *   DELETE manage/vstudio/showcase/<id>/  → 204
 *
 * Страница работает с ShowcaseItem и Candidate и имён полей сервера не знает:
 * поменялось имя — правится только здесь. Ответы разбираем как «чужие руки»:
 * запись без id или с полем не того типа страницу не роняет, а пропускается.
 * category — сценарий ролика: под его именем работа стоит в карусели первого
 * экрана. Какие работы в неё попадут, сервер не знает — это правило сайта, и
 * панель повторяет его здесь же (carousel, placesOf).
 * Модуль чистый (без React и сети) — его проверяет showcaseAdmin.test.mjs.
 */

export const SHOWCASE_PATH = "manage/vstudio/showcase/";
export const itemPath = (id: number): string => `${SHOWCASE_PATH}${id}/`;

/** Длина названия — как у поля ShowcaseItem.title. */
export const TITLE_MAX = 80;
/** Сколько работ уходит посетителям, если сервер не назвал public_limit. */
const PUBLIC_LIMIT = 48;
/** Размер страницы кандидатов, если сервер не назвал page_size. */
const PAGE_SIZE = 50;

/** Сценарий работы: на сервере это поле category, отсюда и имя типа. */
export type Category = { key: string; label: string };

/**
 * Двенадцать сценариев карусели — в том порядке, в каком она их показывает.
 * Тот же список у сервера (ShowcaseItem.SCENARIOS) и у первого экрана
 * (components/vstudio/home/scenarios.ts): меняется один — меняются все три.
 */
export const SCENARIOS: readonly Category[] = [
  { key: "film", label: "Киносцена" },
  { key: "ad", label: "Реклама товара" },
  { key: "person", label: "Персонаж" },
  { key: "car", label: "Автомобиль" },
  { key: "action", label: "Экшен" },
  { key: "scifi", label: "Фантастика" },
  { key: "fashion", label: "Fashion" },
  { key: "music", label: "Музыкальный клип" },
  { key: "i2v", label: "Image → Video" },
  { key: "anim", label: "Анимация" },
  { key: "real", label: "Реалистичная сцена" },
  { key: "vertical", label: "Reels / TikTok" },
];

/** «Другое» — работа без сценария: своего места в карусели у неё нет. */
const OTHER = "other";

/** Запасной список: сценарии присылает сервер, этот — на случай ответа без них. */
const CATEGORIES: Category[] = [...SCENARIOS, { key: OTHER, label: "Другое" }];

/** Ключи до переименования: сервер, который ещё не обновили, отдаёт работы с ними. */
const RENAMED: ReadonlyMap<string, string> = new Map([
  ["social", "vertical"],
  ["anime", "anim"],
]);

export type ShowcaseKind = "video" | "image";

/** Общее у работы витрины и у кандидата: что это за дубль, чей и чем его показать. */
export type ShowcaseMedia = {
  takeUid: string;
  kind: ShowcaseKind;
  video: string | null;
  image: string | null;
  poster: string | null;
  /** "16:9"; пусто — сервер не сообщил. */
  aspect: string;
  duration: number | null;
  /** "720p"; пусто — у картинок и когда модель его не называет. */
  resolution: string;
  modelName: string;
  /** Текст запроса целиком (в панели виден всегда, посетителям — по show_prompt). */
  prompt: string;
  authorEmail: string;
  /** Автор — сотрудник. */
  staff: boolean;
  /**
   * Фото, с которого начинался ролик (Image → Video); null — ролик снят без него.
   * С «Показывать запрос» его увидят все посетители, поэтому сервер отдаёт его
   * панели всегда — показать владельцу заранее.
   */
  startFrame: string | null;
};

export type ShowcaseItem = ShowcaseMedia & {
  id: number;
  title: string;
  category: string;
  sort: number;
  visible: boolean;
  showPrompt: boolean;
  createdAt: string;
  /** Кто поставил работу в витрину. */
  addedBy: string;
  /** false — автор удалил результат дубля: посетителям такая работа не отдаётся. */
  available: boolean;
};

export type Candidate = ShowcaseMedia & {
  finishedAt: string;
  /** false — чужая работа с загруженными фото: сервер её в витрину не примет. */
  publishable: boolean;
};

export type ShowcaseList = {
  items: ShowcaseItem[];
  candidates: Candidate[];
  /** Сколько всего кандидатов под фильтром (для «Показать ещё»). */
  count: number;
  pageSize: number;
  categories: Category[];
  publicLimit: number;
};

/* ------------------------------------------------------------------ */
/* Разбор ответов                                                      */
/* ------------------------------------------------------------------ */

type Row = Record<string, unknown>;

const isRow = (v: unknown): v is Row => typeof v === "object" && v !== null && !Array.isArray(v);
const rows = (v: unknown): Row[] => (Array.isArray(v) ? v.filter(isRow) : []);
const text = (v: unknown): string => (typeof v === "string" ? v.trim() : "");
/** Адрес файла: непустая строка, иначе null (сервер отдаёт и null, и ""). */
const url = (v: unknown): string | null => text(v) || null;
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** Дубль глазами панели (showcase.take_row): у работы он лежит в поле take, кандидат — он сам. */
function media(take: Row): ShowcaseMedia {
  const model = isRow(take.model) ? take.model : null;
  const params = isRow(take.params) ? take.params : null;
  const kind: ShowcaseKind = take.kind === "image" ? "image" : "video";
  const duration = num(take.duration_s);
  return {
    takeUid: text(take.uid),
    kind,
    video: kind === "video" ? url(take.video_url) : null,
    image: url(take.image_url),
    poster: url(take.poster_url),
    aspect: text(take.aspect_ratio),
    duration: duration !== null && duration > 0 ? duration : null,
    resolution: text(params?.resolution),
    modelName: text(model?.name) || text(model?.id),
    prompt: text(take.prompt),
    authorEmail: text(take.user_email),
    staff: take.user_is_staff === true,
    // У картинки первого кадра не бывает — как на сайте (home/showreelData.ts).
    startFrame: kind === "video" ? url(take.start_frame_url) : null,
  };
}

/** Одна работа витрины — строка списка и ответ POST/PATCH. */
export function parseItem(payload: unknown): ShowcaseItem | null {
  if (!isRow(payload)) return null;
  const id = num(payload.id);
  if (id === null) return null;
  return {
    ...media(isRow(payload.take) ? payload.take : {}),
    id,
    title: text(payload.title),
    category: text(payload.category) || OTHER,
    sort: num(payload.sort) ?? 0,
    visible: payload.is_active !== false,
    showPrompt: payload.show_prompt === true,
    createdAt: text(payload.created_at),
    addedBy: text(payload.created_by_email),
    available: payload.state !== "result_gone",
  };
}

function parseCandidate(row: Row): Candidate | null {
  const shown = media(row);
  if (!shown.takeUid) return null;
  return { ...shown, finishedAt: text(row.finished_at), publishable: row.public_ok !== false };
}

function parseCategories(value: unknown): Category[] {
  const out: Category[] = [];
  for (const row of rows(value)) {
    const key = text(row.key);
    if (key && !out.some((c) => c.key === key)) out.push({ key, label: text(row.label) || key });
  }
  return out.length ? out : CATEGORIES;
}

/** Ответ GET; null — вместо панели ответил кто-то другой (страница nginx, не JSON). */
export function parseList(payload: unknown): ShowcaseList | null {
  if (!isRow(payload)) return null;
  const items: ShowcaseItem[] = [];
  const seenItems = new Set<number>();
  for (const row of rows(payload.items)) {
    const item = parseItem(row);
    if (!item || seenItems.has(item.id)) continue;
    seenItems.add(item.id);
    items.push(item);
  }
  const page = isRow(payload.candidates) ? payload.candidates : {};
  const candidates: Candidate[] = [];
  const seenTakes = new Set<string>();
  for (const row of rows(page.results)) {
    const candidate = parseCandidate(row);
    if (!candidate || seenTakes.has(candidate.takeUid)) continue;
    seenTakes.add(candidate.takeUid);
    candidates.push(candidate);
  }
  const limit = num(payload.public_limit);
  const pageSize = num(page.page_size);
  return {
    items,
    candidates,
    count: Math.max(num(page.count) ?? 0, candidates.length),
    pageSize: pageSize !== null && pageSize >= 1 ? Math.trunc(pageSize) : PAGE_SIZE,
    categories: parseCategories(payload.categories),
    publicLimit: limit !== null && limit > 0 ? limit : PUBLIC_LIMIT,
  };
}

/* ------------------------------------------------------------------ */
/* Запросы                                                             */
/* ------------------------------------------------------------------ */

/**
 * Страница кандидатов, на которой лежит первый ещё не показанный дубль.
 * Считаем от числа строк на экране, а не «предыдущая + 1»: дубль, поставленный
 * в витрину, из кандидатов уходит, и следующие страницы сдвигаются на него.
 */
export const nextPage = (shown: number, pageSize: number): number => Math.floor(shown / Math.max(pageSize, 1)) + 1;

export function listPath(query: { staffOnly: boolean; search: string; page: number }): string {
  const params = new URLSearchParams({ scope: query.staffOnly ? "staff" : "all" });
  if (query.search) params.set("q", query.search);
  if (query.page > 1) params.set("page", String(query.page));
  return `${SHOWCASE_PATH}?${params.toString()}`;
}

export type AddForm = { title: string; category: string; showPrompt: boolean };

/**
 * С чем открывается окно «В витрину». Запрос показываем сразу: по нему
 * работает «Снять похожее», ради которого ролик и стоит в карусели. Запрос
 * сотрудника — рабочий материал студии; запрос пользователя — его находка,
 * такую галочку ставит только сам владелец.
 */
export function addDefaults(candidate: Pick<Candidate, "staff" | "prompt">): AddForm {
  return { title: "", category: "", showPrompt: candidate.staff && candidate.prompt !== "" };
}

/**
 * Название после выбора сценария `key`. В пустое поле ставим имя сценария:
 * его посетитель и видит под роликом. Набранное владельцем не трогаем —
 * «своим» не считается только имя сценария, которое подставили мы: оно
 * уходит вслед за сценарием. У «Другого» имени для подписи нет.
 */
export function titleForScenario(title: string, key: string, categories: readonly Category[]): string {
  const named = categories.filter((category) => category.key !== OTHER);
  const typed = title.trim();
  if (typed && !named.some((category) => category.label === typed)) return title;
  return named.find((category) => category.key === key)?.label ?? "";
}

/** sort — куда поставить новую работу (см. sortForNew); без него сервер ставит 0. */
export function addBody(takeUid: string, form: AddForm, sort?: number): Record<string, unknown> {
  const body: Record<string, unknown> = {
    take: takeUid,
    title: form.title.trim(),
    category: form.category,
    show_prompt: form.showPrompt,
  };
  if (sort !== undefined) body.sort = sort;
  return body;
}

export type ItemChanges = Partial<Pick<ShowcaseItem, "title" | "category" | "sort" | "visible" | "showPrompt">>;

/** Тело PATCH: только то, что меняем. Флаги — настоящие true/false, строку сервер не примет. */
export function patchBody(changes: ItemChanges): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (changes.title !== undefined) body.title = changes.title.trim();
  if (changes.category !== undefined) body.category = changes.category;
  if (changes.sort !== undefined) body.sort = changes.sort;
  if (changes.visible !== undefined) body.is_active = changes.visible;
  if (changes.showPrompt !== undefined) body.show_prompt = changes.showPrompt;
  return body;
}

/** Прежние значения тех же полей — откатить правку, которую сервер не принял. */
export function previousOf(item: ShowcaseItem, changes: ItemChanges): ItemChanges {
  const before: ItemChanges = {};
  if (changes.title !== undefined) before.title = item.title;
  if (changes.category !== undefined) before.category = item.category;
  if (changes.sort !== undefined) before.sort = item.sort;
  if (changes.visible !== undefined) before.visible = item.visible;
  if (changes.showPrompt !== undefined) before.showPrompt = item.showPrompt;
  return before;
}

/**
 * Текст отказа. Витрина отвечает {detail}, а «видеостудия не подключена» —
 * {error, error_code}; fetchData из тела достаёт только detail, поэтому
 * читаем его сами. У лимита запросов текст сервера служебный («ожидаемая
 * доступность через N секунд») — говорим своими словами.
 */
export function errorText(res: { status: number; data?: unknown }, fallback: string): string {
  if (res.status === 0) return "Нет связи с сервером. Проверьте интернет и повторите.";
  if (res.status === 429) return "Слишком много запросов подряд. Подождите минуту и повторите.";
  const data = isRow(res.data) ? res.data : null;
  const told = data ? text(data.detail) || text(data.error) || text(data.message) : "";
  return told || `${fallback} (HTTP ${res.status})`;
}

/* ------------------------------------------------------------------ */
/* Порядок                                                             */
/* ------------------------------------------------------------------ */

export const SORT_STEP = 10;
/** Сервер принимает sort от −100 000 до 100 000. */
const SORT_LIMIT = 100_000;

export type MovePlan = {
  /** id работ в новом порядке. */
  order: number[];
  /** Какие sort записать на сервер: id → новое значение. */
  sorts: Map<number, number>;
};

/** Целое строго между соседями (null — края списка нет); null — промежутка нет. */
function sortBetween(before: number | null, after: number | null): number | null {
  let value: number | null = null;
  if (before !== null && after !== null) value = after - before >= 2 ? Math.floor((before + after) / 2) : null;
  else if (after !== null) value = after - SORT_STEP;
  else if (before !== null) value = before + SORT_STEP;
  return value !== null && Math.abs(value) <= SORT_LIMIT ? value : null;
}

/**
 * Что записать, чтобы работа `id` встала на место `index` (с нуля).
 *
 * Сервер выдаёт витрину по sort по возрастанию, при равных — новые выше, и
 * каждая запись — отдельный запрос из общего лимита панели (120 в минуту).
 * Поэтому обычно пишем одно число — между новыми соседями. Промежутка нет
 * (у соседей sort одинаковый или подряд) — один раз нумеруем весь список с
 * шагом SORT_STEP, дальше снова хватает одной записи.
 */
export function planMove(
  items: readonly Pick<ShowcaseItem, "id" | "sort">[],
  id: number,
  index: number,
): MovePlan | null {
  const from = items.findIndex((item) => item.id === id);
  if (from < 0 || !Number.isFinite(index)) return null;
  const to = Math.min(Math.max(Math.trunc(index), 0), items.length - 1);
  if (to === from) return null;

  const next = items.slice();
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  const order = next.map((item) => item.id);

  // Одной записи хватит, только если остальные уже стоят по возрастанию:
  // иначе сервер расставит их не так, как на экране.
  const rest = next.filter((item) => item.id !== id);
  const ascending = rest.every((item, i) => i === 0 || rest[i - 1].sort <= item.sort);
  if (ascending) {
    const between = sortBetween(to > 0 ? next[to - 1].sort : null, to < next.length - 1 ? next[to + 1].sort : null);
    if (between !== null) return { order, sorts: new Map([[id, between]]) };
  }

  const sorts = new Map<number, number>();
  next.forEach((item, i) => {
    const sort = (i + 1) * SORT_STEP;
    if (item.sort !== sort) sorts.set(item.id, sort);
  });
  return { order, sorts };
}

export function applyMove(items: readonly ShowcaseItem[], plan: MovePlan): ShowcaseItem[] {
  const byId = new Map(items.map((item) => [item.id, item]));
  const out: ShowcaseItem[] = [];
  for (const id of plan.order) {
    const item = byId.get(id);
    if (item) out.push({ ...item, sort: plan.sorts.get(id) ?? item.sort });
  }
  return out;
}

/**
 * sort для новой работы: она встаёт первой — её добавили, чтобы показать.
 * undefined — витрина пуста или выше уже некуда: тогда решает сервер (0).
 */
export function sortForNew(items: readonly Pick<ShowcaseItem, "sort">[]): number | undefined {
  if (items.length === 0) return undefined;
  return sortBetween(null, items[0].sort) ?? undefined;
}

/** Работа встаёт туда же, куда её поставит сервер: по sort, при равных — новые выше. */
export function insertItem(items: readonly ShowcaseItem[], item: ShowcaseItem): ShowcaseItem[] {
  const rest = items.filter((x) => x.id !== item.id);
  const at = rest.findIndex((x) => x.sort > item.sort || (x.sort === item.sort && x.id < item.id));
  return at < 0 ? [...rest, item] : [...rest.slice(0, at), item, ...rest.slice(at)];
}

/** Что сервер отдаёт сайту прямо сейчас, по порядку: первые `limit` видимых работ с живым файлом. */
export function publicOrder(items: readonly ShowcaseItem[], limit: number): number[] {
  const out: number[] = [];
  for (const item of items) {
    if (out.length >= limit) break;
    if (item.visible && item.available) out.push(item.id);
  }
  return out;
}

/* ------------------------------------------------------------------ */
/* Карусель                                                            */
/* ------------------------------------------------------------------ */

export type ScenarioSlot = {
  key: string;
  label: string;
  /** Ролик, которым карусель показывает сценарий; null — пусто. */
  item: ShowcaseItem | null;
  /** Сколько ещё роликов сценария отдано сайту: в карусель они идут после первых, на свободные места. */
  spare: number;
};

export type Carousel = {
  /** Сценарии SCENARIOS в порядке карусели. */
  slots: ScenarioSlot[];
  /** Сколько из них заполнено. */
  filled: number;
  /** Роликов студии на сайте — вместе с теми, что без сценария. */
  videos: number;
  /** id роликов в порядке карусели, не больше её размера. */
  order: number[];
  /** false — роликов меньше, чем карусели нужно: вместо них идут сцены мультстудии. */
  studio: boolean;
};

/** limit — сколько работ сервер отдаёт сайту; size и min — размер карусели и её порог (REEL_SIZE, REEL_MIN). */
export type ReelRule = { limit: number; size: number; min: number };

/**
 * Карусель первого экрана глазами панели — тем же правилом, что на сайте
 * (components/vstudio/home/showreelData.ts). В неё идут только ролики,
 * отданные сайту: сначала верхний ролик каждого сценария в порядке
 * SCENARIOS, затем остальные в порядке витрины, всего не больше `size`.
 * Картинки карусель не берёт. Набралось меньше `min` — студию она не
 * показывает вовсе: с мультстудией ролики не смешиваются.
 */
export function carousel(items: readonly ShowcaseItem[], rule: ReelRule): Carousel {
  const sent = new Set(publicOrder(items, rule.limit));
  const videos = items.filter((item) => item.kind === "video" && sent.has(item.id));
  const byScenario = new Map<string, ShowcaseItem[]>();
  for (const item of videos) {
    const key = RENAMED.get(item.category) ?? item.category;
    byScenario.set(key, [...(byScenario.get(key) ?? []), item]);
  }
  const slots = SCENARIOS.map(({ key, label }): ScenarioSlot => {
    const own = byScenario.get(key) ?? [];
    return { key, label, item: own[0] ?? null, spare: Math.max(own.length - 1, 0) };
  });
  const heads = slots.flatMap((slot) => (slot.item ? [slot.item] : []));
  const taken = new Set(heads.map((item) => item.id));
  const order = [...heads, ...videos.filter((item) => !taken.has(item.id))].slice(0, rule.size).map((item) => item.id);
  return { slots, filled: heads.length, videos: videos.length, order, studio: order.length >= rule.min };
}

/** Где работа сейчас на сайте. */
export type Place = "reel" | "wait" | "out" | "hidden" | "over" | "nofile";

/**
 * Что с каждой работой на сайте. Кроме карусели, первый экран работ студии
 * не показывает, поэтому «отдана сайту» ещё не значит «видна»: ролик ждёт,
 * пока карусель наберёт свой минимум ("wait"), а картинка и ролик сверх
 * размера карусели в неё не попадают ("out").
 */
export function placesOf(
  items: readonly ShowcaseItem[],
  limit: number,
  reel: Pick<Carousel, "order" | "studio">,
): Map<number, Place> {
  const sent = new Set(publicOrder(items, limit));
  const shown = new Set(reel.order);
  const place = (item: ShowcaseItem): Place => {
    if (!item.available) return "nofile";
    if (!item.visible) return "hidden";
    if (!sent.has(item.id)) return "over";
    if (!shown.has(item.id)) return "out";
    return reel.studio ? "reel" : "wait";
  };
  return new Map(items.map((item) => [item.id, place(item)]));
}

/**
 * Витрина видеостудии в панели: весь контракт с сервером — в этом файле
 * (core/adminapi/vstudio.py, строки собирает core/vstudio/showcase.py).
 *
 *   GET    manage/vstudio/showcase/?scope=staff|all&q=&page=
 *            → { items: [работа], candidates: { count, page_size, results: [дубль] },
 *                categories: [{ key, label }], placements: [{ key, label }],
 *                public_limit, trends_limit, reel_size, reel_size_min, reel_size_max }
 *   POST   manage/vstudio/showcase/       { take, title, category, placement, show_prompt, sort? } → работа
 *   PATCH  manage/vstudio/showcase/       { reel_size } → { reel_size }
 *   PATCH  manage/vstudio/showcase/<id>/  { title?, category?, placement?, sort?, is_active?, show_prompt? } → работа
 *   DELETE manage/vstudio/showcase/<id>/  → 204
 *
 * Страница работает с ShowcaseItem и Candidate и имён полей сервера не знает:
 * поменялось имя — правится только здесь. Ответы разбираем как «чужие руки»:
 * запись без id или с полем не того типа страницу не роняет, а пропускается.
 * placement — где работа на первом экране: в карусели или в «Трендах». Одна
 * работа — одно место; у каждого места свой потолок (public_limit,
 * trends_limit), и сайту сервер отдаёт два отдельных списка. category —
 * сценарий ролика: под его именем работа стоит в карусели. Какие работы в неё
 * попадут, сервер не знает — это правило сайта, и панель повторяет его здесь
 * же (carousel, placesOf); «Тренды» сайт показывает подряд (trendsOf). Размер карусели
 * (reel_size) — настройка сервера, но сколько из неё покажет сайт, решает он
 * сам: число читаем его же функцией, границы — не шире его границ.
 * Модуль чистый (без React и сети) — его проверяет showcaseAdmin.test.mjs.
 */
import { REEL_MAX, REEL_MIN, TRENDS_MAX, clampReelSize } from "@/components/vstudio/home/showreelData";

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

/** Где работа стоит на первом экране (ShowcaseItem.placement). */
export type Placement = "reel" | "trends";
export type PlacementOption = { key: Placement; label: string };

/** Запасной список мест: его присылает сервер, этот — на случай ответа без него. */
const PLACEMENTS: PlacementOption[] = [
  { key: "reel", label: "Карусель" },
  { key: "trends", label: "Тренды" },
];

export const isPlacement = (v: unknown): v is Placement => v === "reel" || v === "trends";

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
  /** Карусель или «Тренды»; сервер прежней версии места не знает — тогда карусель. */
  placement: Placement;
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

/** «Роликов в карусели»: сколько их сейчас и в каких пределах число можно менять. */
export type ReelSize = { value: number; min: number; max: number };

export type ShowcaseList = {
  items: ShowcaseItem[];
  candidates: Candidate[];
  /** Сколько всего кандидатов под фильтром (для «Показать ещё»). */
  count: number;
  pageSize: number;
  categories: Category[];
  placements: PlacementOption[];
  /** Сколько работ уходит сайту в карусель (до её правила и размера). */
  publicLimit: number;
  /** Сколько работ уходит сайту в «Тренды». */
  trendsLimit: number;
  reelSize: ReelSize;
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
    placement: isPlacement(payload.placement) ? payload.placement : "reel",
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

/** Места с сервера, в его порядке и с его подписями. Список неполный или чужой — берём свой. */
function parsePlacements(value: unknown): PlacementOption[] {
  const out: PlacementOption[] = [];
  for (const row of rows(value)) {
    const key = text(row.key);
    if (!isPlacement(key) || out.some((p) => p.key === key)) continue;
    out.push({ key, label: text(row.label) || key });
  }
  return out.length === PLACEMENTS.length ? out : PLACEMENTS;
}

/** Целое, которое сайт умеет показать как размер карусели; иначе null. */
function reelInt(v: unknown): number | null {
  const n = num(v);
  return n !== null && Number.isInteger(n) && n >= REEL_MIN && n <= REEL_MAX ? n : null;
}

/**
 * Настройка «Роликов в карусели». Сервер прежней версии её не присылает —
 * тогда размер и границы как у сайта. Размер читаем функцией сайта: доска
 * обязана показать то же, что увидит посетитель.
 */
function parseReelSize(payload: Row): ReelSize {
  const value = clampReelSize(payload.reel_size);
  const min = reelInt(payload.reel_size_min) ?? REEL_MIN;
  const max = reelInt(payload.reel_size_max) ?? REEL_MAX;
  return min <= max ? { value, min, max } : { value, min: REEL_MIN, max: REEL_MAX };
}

/** Ответ PATCH с размером — что сервер записал; null — ответ не разобрать. */
export function savedReelSize(payload: unknown): number | null {
  return isRow(payload) ? reelInt(payload.reel_size) : null;
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
  const trendsLimit = num(payload.trends_limit);
  const pageSize = num(page.page_size);
  return {
    items,
    candidates,
    count: Math.max(num(page.count) ?? 0, candidates.length),
    pageSize: pageSize !== null && pageSize >= 1 ? Math.trunc(pageSize) : PAGE_SIZE,
    categories: parseCategories(payload.categories),
    placements: parsePlacements(payload.placements),
    publicLimit: limit !== null && limit > 0 ? limit : PUBLIC_LIMIT,
    trendsLimit: trendsLimit !== null && trendsLimit >= 1 ? Math.trunc(trendsLimit) : TRENDS_MAX,
    reelSize: parseReelSize(payload),
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

export type AddForm = { title: string; category: string; placement: Placement; showPrompt: boolean };

/**
 * С чем открывается окно «В витрину». Запрос показываем сразу: по нему
 * работает «Снять похожее», ради которого ролик и стоит в карусели. Запрос
 * сотрудника — рабочий материал студии; запрос пользователя — его находка,
 * такую галочку ставит только сам владелец. Место — карусель: «Тренды»
 * владелец выбирает сам.
 */
export function addDefaults(candidate: Pick<Candidate, "staff" | "prompt">): AddForm {
  return { title: "", category: "", placement: "reel", showPrompt: candidate.staff && candidate.prompt !== "" };
}

/** «Тренды» — сетка роликов: картинку туда сервер не примет. */
export const trendsAllowed = (media: Pick<ShowcaseMedia, "kind">): boolean => media.kind === "video";

/**
 * Окно можно отправлять: есть название, а у карусели — ещё и сценарий (под
 * его именем ролик в ней и стоит). Работе «Трендов» сценарий не нужен.
 */
export function addReady(form: Pick<AddForm, "title" | "category" | "placement">): boolean {
  return form.title.trim() !== "" && (form.placement === "trends" || form.category !== "");
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

/**
 * sort — куда поставить новую работу (см. sortForNew); без него сервер ставит 0.
 * Работа «Трендов» без сценария уходит «Другим»: пустой сценарий сервер не примет.
 */
export function addBody(takeUid: string, form: AddForm, sort?: number): Record<string, unknown> {
  const body: Record<string, unknown> = {
    take: takeUid,
    title: form.title.trim(),
    category: form.category || OTHER,
    placement: form.placement,
    show_prompt: form.showPrompt,
  };
  if (sort !== undefined) body.sort = sort;
  return body;
}

export type ItemChanges = Partial<
  Pick<ShowcaseItem, "title" | "category" | "placement" | "sort" | "visible" | "showPrompt">
>;

/** Тело PATCH: только то, что меняем. Флаги — настоящие true/false, строку сервер не примет. */
export function patchBody(changes: ItemChanges): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (changes.title !== undefined) body.title = changes.title.trim();
  if (changes.category !== undefined) body.category = changes.category;
  if (changes.placement !== undefined) body.placement = changes.placement;
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
  if (changes.placement !== undefined) before.placement = item.placement;
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

/** Тело PATCH с размером карусели: настоящее целое, строку сервер не примет. */
export const reelSizeBody = (value: number): Record<string, unknown> => ({ reel_size: value });

/**
 * Отказ сохранить размер. 405 отвечает сервер прежней версии: настройки у
 * него ещё нет, а его «Метод PATCH не разрешён» владельцу ничего не скажет.
 */
export function reelSizeError(res: { status: number; data?: unknown }): string {
  if (res.status === 405) return "Сервер ещё не обновлён: размер карусели на нём пока не меняется.";
  return errorText(res, "Не удалось сохранить размер карусели");
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

/**
 * Перестановка на экране. План считают по списку одного места (planMove), а
 * применяют к витрине целиком: работы плана встают в его порядке на те же
 * позиции, которые занимали, остальные — карусель при перестановке «Трендов»
 * и наоборот — не двигаются.
 */
export function applyMove(items: readonly ShowcaseItem[], plan: MovePlan): ShowcaseItem[] {
  const byId = new Map(items.map((item) => [item.id, item]));
  const queue: ShowcaseItem[] = [];
  for (const id of plan.order) {
    const item = byId.get(id);
    if (item) queue.push({ ...item, sort: plan.sorts.get(id) ?? item.sort });
  }
  const moved = new Set(queue.map((item) => item.id));
  let next = 0;
  return items.map((item) => (moved.has(item.id) ? queue[next++] : item));
}

/** Работы одного места — в том порядке, в каком они стоят в витрине. */
export const itemsIn = (items: readonly ShowcaseItem[], placement: Placement): ShowcaseItem[] =>
  items.filter((item) => item.placement === placement);

/** У работы нет сценария карусели («Другое» или незнакомый ключ): в карусели она идёт после сценариев. */
export function scenarioless(item: Pick<ShowcaseItem, "category">): boolean {
  const key = RENAMED.get(item.category) ?? item.category;
  return !SCENARIOS.some((scenario) => scenario.key === key);
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

/**
 * Что сервер отдаёт сайту прямо сейчас, по порядку: первые `limit` видимых
 * работ с живым файлом. Считается по списку одного места: у карусели и
 * «Трендов» потолки свои, и чужие работы места не занимают.
 */
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
  /** Ролик сценария вошёл в карусель. Снятый сценарий может и не войти: мест меньше, чем занятых сценариев перед ним. */
  fits: boolean;
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
  /** id всех этих роликов в порядке карусели: кому хватит места, решает её размер. */
  queue: number[];
  /** id тех, кому хватило: начало очереди, не больше размера карусели. */
  order: number[];
  /** Ролики карусели после сценариев — в порядке витрины. */
  tail: ShowcaseItem[];
  /** false — роликов меньше, чем карусели нужно: вместо них идут сцены мультстудии. */
  studio: boolean;
};

/**
 * limit — сколько работ сервер отдаёт сайту; size — размер карусели (настройка
 * сервера, ReelSize.value); min — её порог, правило сайта (REEL_MIN).
 */
export type ReelRule = { limit: number; size: number; min: number };

/**
 * Карусель первого экрана глазами панели — тем же правилом, что на сайте
 * (components/vstudio/home/showreelData.ts). В неё идут только ролики,
 * отданные сайту: сначала верхний ролик каждого сценария в порядке
 * SCENARIOS, затем остальные в порядке витрины, всего не больше `size`.
 * Картинки карусель не берёт. Набралось меньше `min` — студию она не
 * показывает вовсе: с мультстудией ролики не смешиваются. Работы «Трендов»
 * в карусели не бывает: витрину можно отдать целиком, они не в счёт.
 */
export function carousel(items: readonly ShowcaseItem[], rule: ReelRule): Carousel {
  const own = itemsIn(items, "reel");
  const sent = new Set(publicOrder(own, rule.limit));
  const videos = own.filter((item) => item.kind === "video" && sent.has(item.id));
  const byScenario = new Map<string, ShowcaseItem[]>();
  for (const item of videos) {
    const key = RENAMED.get(item.category) ?? item.category;
    byScenario.set(key, [...(byScenario.get(key) ?? []), item]);
  }
  const heads = SCENARIOS.flatMap(({ key }) => byScenario.get(key)?.slice(0, 1) ?? []);
  const taken = new Set(heads.map((item) => item.id));
  const queue = [...heads, ...videos.filter((item) => !taken.has(item.id))];
  const shown = queue.slice(0, rule.size);
  const fits = new Set(shown.map((item) => item.id));
  const slots = SCENARIOS.map(({ key, label }): ScenarioSlot => {
    const own = byScenario.get(key) ?? [];
    const item = own[0] ?? null;
    return { key, label, item, fits: item !== null && fits.has(item.id), spare: Math.max(own.length - 1, 0) };
  });
  return {
    slots,
    filled: heads.length,
    videos: videos.length,
    queue: queue.map((item) => item.id),
    order: shown.map((item) => item.id),
    tail: shown.slice(heads.length),
    studio: shown.length >= rule.min,
  };
}

/** Где работа сейчас на сайте; "trend" — видна в «Трендах». */
export type Place = "reel" | "wait" | "out" | "image" | "hidden" | "over" | "nofile" | "trend";

/**
 * Что с каждой работой карусели на сайте. «Отдана сайту» ещё не значит
 * «видна»: ролик ждёт, пока карусель наберёт свой минимум ("wait"), или стоит
 * в её очереди дальше выбранного размера ("out"); картинок карусель не берёт
 * вовсе ("image"). Работы «Трендов» здесь не считаются — у них trendsOf.
 */
export function placesOf(
  items: readonly ShowcaseItem[],
  limit: number,
  reel: Pick<Carousel, "order" | "studio">,
): Map<number, Place> {
  const own = itemsIn(items, "reel");
  const sent = new Set(publicOrder(own, limit));
  const shown = new Set(reel.order);
  const place = (item: ShowcaseItem): Place => {
    if (!item.available) return "nofile";
    if (!item.visible) return "hidden";
    if (!sent.has(item.id)) return "over";
    if (item.kind !== "video") return "image";
    if (!shown.has(item.id)) return "out";
    return reel.studio ? "reel" : "wait";
  };
  return new Map(own.map((item) => [item.id, place(item)]));
}

/* ------------------------------------------------------------------ */
/* «Тренды»                                                            */
/* ------------------------------------------------------------------ */

export type Trends = {
  /** id роликов, которые сайт показывает в «Трендах», в его порядке. */
  order: number[];
  /** Что с каждой работой «Трендов» на сайте. */
  places: Map<number, Place>;
};

/**
 * «Тренды» глазами панели. Сервер отдаёт сайту первые `limit` видимых работ
 * с живым файлом; сайт берёт из них только ролики (showreelData.trendItems) и
 * показывает подряд, без сценариев и без порога, не больше своего TRENDS_MAX.
 * Картинку сервер в «Тренды» не ставит; если она там всё же окажется, место у
 * сервера она займёт, а на сайте её не будет ("image").
 */
export function trendsOf(items: readonly ShowcaseItem[], limit: number): Trends {
  const own = itemsIn(items, "trends");
  const sent = new Set(publicOrder(own, limit));
  const order = own
    .filter((item) => sent.has(item.id) && item.kind === "video")
    .slice(0, TRENDS_MAX)
    .map((item) => item.id);
  const shown = new Set(order);
  const place = (item: ShowcaseItem): Place => {
    if (!item.available) return "nofile";
    if (!item.visible) return "hidden";
    if (item.kind !== "video" && sent.has(item.id)) return "image";
    return shown.has(item.id) ? "trend" : "over";
  };
  return { order, places: new Map(own.map((item) => [item.id, place(item)])) };
}

/* ------------------------------------------------------------------ */
/* Размер карусели                                                     */
/* ------------------------------------------------------------------ */

/** Значения для выбора одним нажатием — их назвал владелец. */
const REEL_QUICK: readonly number[] = [12, 18, 24, 36, 48];

const fitReelSize = (value: number, size: ReelSize): number => Math.min(Math.max(value, size.min), size.max);

/** Быстрые значения, которые сервер примет. */
export const reelSizeQuick = (size: ReelSize): number[] => REEL_QUICK.filter((n) => n >= size.min && n <= size.max);

/** Размер после кнопки − или + (by — на сколько); null — дальше границы некуда. */
export function reelSizeStep(size: ReelSize, by: number): number | null {
  const next = fitReelSize(size.value + by, size);
  return next === size.value ? null : next;
}

/** Набранное в поле → размер в границах; null — не число: человек передумал. */
export function reelSizeTyped(typed: string, size: ReelSize): number | null {
  const digits = typed.trim();
  return /^\d+$/.test(digits) ? fitReelSize(Number(digits), size) : null;
}

/**
 * Набранное в поле — если это уже размер, без подгонки к границе; иначе null.
 * Так поле сохраняется, когда из него просто ушли (кликнули мимо, сменили
 * окно): «4», набранное на пути к «48», иначе записалось бы пятью — и на сайт
 * ушла бы карусель из пяти роликов. К границе подгоняет только Enter
 * (reelSizeTyped). От этого же числа шагают − и +.
 */
export function reelSizeExact(typed: string | null, size: ReelSize): number | null {
  if (typed === null) return null;
  const value = reelSizeTyped(typed, size);
  return value !== null && value === Number(typed.trim()) ? value : null;
}

/** «1 ролик» / «3 ролика» / «12 роликов»: число теперь любое, одной формой не обойтись. */
export function plural(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return `${n} ${one}`;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return `${n} ${few}`;
  return `${n} ${many}`;
}

export type ReelHint = {
  /** Правило карусели и сколько роликов ей сейчас доступно. */
  text: string;
  /** Чем это число расходится с выбранным размером; null — сходится. */
  note: string | null;
};

/** Подсказка под «Роликов в карусели». */
export function reelSizeHint(reel: Pick<Carousel, "videos" | "studio">, rule: Pick<ReelRule, "size" | "min">): ReelHint {
  const { videos } = reel;
  const have = plural(videos, "включённый ролик", "включённых ролика", "включённых роликов");
  const text = `Карусель берёт верхний ролик каждого сценария, затем остальные по порядку списка. Сейчас в витрине ${have}.`;
  // Пока роликов меньше порога, карусель не показывает их вовсе — «покажет N» было бы неправдой.
  if (!reel.studio) return { text, note: `Роликов меньше ${rule.min}: карусель пока показывает сцены мультстудии.` };
  if (videos < rule.size) return { text, note: `Роликов меньше, чем мест: карусель покажет ${videos}.` };
  if (videos > rule.size) {
    return { text, note: `Не вошло роликов: ${videos - rule.size} — в списке они помечены «Вне карусели».` };
  }
  return { text, note: null };
}

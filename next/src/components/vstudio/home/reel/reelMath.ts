/**
 * Счёт и геометрия карусели первого экрана (§2.2 ReelCoverflow).
 *
 * Кадр, стоящий на d мест от активного, получает позу: сдвиг, поворот, размер,
 * затемнение. В целых d это таблица из макета, между ними — прямая
 * интерполяция: по ней кадры идут за пальцем и ровно доезжают, когда палец
 * отпустили. Четвёртая ступень (|d| ≥ 3) — невидимая «стоянка»: кадр уже в
 * разметке, постер загружен, и на следующем шаге он выезжает из-за края, а не
 * возникает на месте; ушедший кадр так же успевает погаснуть, а не обрывается.
 *
 * Позиция — целое без границ: карусель из LOOP_MIN и более кадров листается по
 * кругу, и место v занимает кадр v mod N. Короткая карусель кругом не идёт —
 * иначе один и тот же кадр стоял бы и слева, и справа от активного.
 *
 * Здесь же — то, что считается рядом с геометрией: как дальний кадр уходит в
 * «бумагу» на светлой сцене, имена кадров, прокрутка ряда названий под
 * каруселью и его стрелки, и то, какие кадры длинной ленты телефона живые.
 *
 * Модуль чистый (без React и DOM): его проверяет node-тест reelMath.test.mjs.
 */

import type { EdgeFade } from "../strip/stripLogic";

/** Сколько карусель стоит на кадре, прежде чем перелистнётся сама. */
export const REEL_INTERVAL_MS = 7000;
/** С этого числа кадров карусель бесконечная: пять мест видны сразу, и все разные. */
export const LOOP_MIN = 5;
/** С этого расстояния кадр стоит на невидимой стоянке; дальше поза не меняется. */
export const PARK = 3;
/**
 * Сколько мест по каждую сторону от активного живёт в разметке. Видны два,
 * остальные — стоянка с запасом: прыжок через кадр (нажали на дальнего соседа,
 * смахнули широко) и несколько быстрых нажатий подряд проходят без появления
 * и пропажи кадров на виду.
 */
export const REACH = 5;
/** Смахивание короче — не листаем, кадр возвращается на место. */
export const SWIPE_PX = 40;
/** С какого сдвига понятно, куда ведут палец: вбок (листаем) или вверх-вниз (страница). */
export const INTENT_PX = 8;
/** За одно смахивание — не дальше двух кадров. */
const DRAG_REACH = 2;
/** Насколько короткая карусель поддаётся за своим краем. */
const EDGE_GIVE = 0.3;

/* ---------- поза кадра ---------- */

export type Pose = {
  /** Сдвиг от центра, % ширины кадра. */
  x: number;
  /** Поворот к центру, градусы. */
  rot: number;
  scale: number;
  /** Чёрная вуаль поверх кадра, 0…1. */
  dim: number;
  opacity: number;
};

const STOPS: readonly Pose[] = [
  { x: 0, rot: 0, scale: 1, dim: 0, opacity: 1 },
  { x: 62, rot: 34, scale: 0.78, dim: 0.45, opacity: 1 },
  { x: 104, rot: 40, scale: 0.62, dim: 0.65, opacity: 0.7 },
  { x: 138, rot: 44, scale: 0.5, dim: 0.8, opacity: 0 },
];

const lerp = (a: number, b: number, f: number) => a + (b - a) * f;
const round3 = (n: number) => Math.round(n * 1000) / 1000;
const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n));

/** Поза кадра на расстоянии |d| от активного; дальше стоянки поза не меняется. */
export function poseAt(d: number): Pose {
  const a = Math.min(Math.abs(d), PARK);
  const i = Math.min(Math.floor(a), PARK - 1);
  const f = a - i;
  const from = STOPS[i];
  const to = STOPS[i + 1];
  return {
    x: lerp(from.x, to.x, f),
    rot: lerp(from.rot, to.rot, f),
    scale: lerp(from.scale, to.scale, f),
    dim: lerp(from.dim, to.dim, f),
    opacity: lerp(from.opacity, to.opacity, f),
  };
}

export type SlotLook = { transform: string; opacity: number; zIndex: number; dim: number };

/** Вид места в готовом для style виде. d < 0 — слева от активного, d > 0 — справа. */
export function slotLook(d: number): SlotLook {
  const pose = poseAt(d);
  const side = d < 0 ? -1 : 1;
  // Сосед поворачивается вокруг края, обращённого к центру (transform-origin из
  // макета). Сдвиг оси записан в самой цепочке: её состав одинаков для любого d,
  // и браузер ведёт кадр между позами по каждому числу отдельно — без скачка,
  // который дала бы смена transform-origin в момент, когда кадр становится активным.
  const hinge = 50 * Math.min(Math.abs(d), 1);
  const transform =
    `translateX(${round3(side * pose.x)}%) translateX(${round3(-side * hinge)}%) ` +
    `rotateY(${round3(-side * pose.rot)}deg) scale(${round3(pose.scale)}) translateX(${round3(side * hinge)}%)`;
  return {
    transform,
    opacity: round3(pose.opacity),
    // Ближний к центру — поверх дальнего; при перетаскивании порядок меняется на полпути.
    zIndex: 10 - Math.round(Math.min(Math.abs(d), PARK)),
    dim: round3(pose.dim),
  };
}

/** На сколько пикселей уезжает центр кадра за один шаг карусели. */
export function stepPx(cardWidth: number): number {
  return (STOPS[1].x / 100) * cardWidth;
}

/* ---------- светлая сцена ---------- */

/** Перспектива сцены — как у .vs-stage в globals.css. */
const PERSPECTIVE = 1500;
/** Зазор между внешним краем соседнего кадра и краем колонки. */
const EDGE_GAP = 16;
/** Во сколько раз быстрее дальний кадр бледнеет на светлой сцене (показатель степени). */
const PAPER_FADE = 3;
/** На скольких пикселях от края соседа дальний кадр сходит на нет — если до края колонки есть столько места. */
const FOG_REACH = 96;
/** За столько пикселей до края колонки от дальнего кадра уже ничего не осталось: срез колонки не виден. */
const FOG_REST = 8;
/** Какая доля «тумана» уже лежит на дальнем кадре там, где он выходит из-за соседа. */
const FOG_HEAD = 0.3;

/**
 * Прозрачность кадра на светлой сцене. Соседи притемнены чёрной вуалью (dim):
 * в тёмном зале дальний кадр так уходит в темноту, а на «бумаге» тот же кадр
 * встал бы у края сцены серой плитой. Поэтому там он бледнее, а главное —
 * уходит в «бумагу» не весь разом, а от ближнего края к дальнему (fogBand).
 * Активный кадр и ближние соседи (opacity 1) и невидимая стоянка (opacity 0)
 * остаются как есть, а между ними кривая гладкая — за пальцем кадр идёт без
 * скачка.
 */
export function paperOpacity(opacity: number): number {
  return round3(clamp(opacity, 0, 1) ** PAPER_FADE);
}

/** Сила «тумана» на кадре светлой сцены: у активного и соседей его нет, дальний кадр и стоянка в нём целиком. */
export function paperFog(d: number): number {
  return round3(clamp(Math.abs(d) - 1, 0, 1));
}

/**
 * Где на экране внешний край соседа (|d| = 1), в пикселях от центра сцены.
 * Край повёрнут к зрителю, и перспектива отодвигает его тем дальше, чем шире кадр.
 */
export function sideEdge(cardWidth: number): number {
  const side = STOPS[1];
  const turn = (side.rot * Math.PI) / 180;
  const flat = (side.x / 100 - 0.5 + side.scale * Math.cos(turn)) * cardWidth;
  const depth = side.scale * Math.sin(turn) * cardWidth;
  return (flat * PERSPECTIVE) / (PERSPECTIVE - depth);
}

export type FogBand = {
  /** Здесь «туман» начинается, % ширины кадра от его ближнего к центру края. */
  from: number;
  /** Отсюда и до внешнего края кадр закрыт целиком. */
  to: number;
};

/**
 * Светлая сцена: на какой полосе дальний кадр (|d| = 2) уходит в «бумагу».
 *
 * Из-за соседа он виден только внешней частью. В тёмном зале она гаснет сама,
 * а на светлой сцене стояла бы серой плитой, срезанной краем колонки. Поэтому
 * поверх кадра лежит вуаль цвета сцены: у края соседа она уже заметна
 * (FOG_HEAD) и закрывает кадр целиком через FOG_REACH пикселей — или раньше,
 * если край колонки ближе: до него не должно дойти ничего. На обычном экране
 * между соседом и краем колонки всего EDGE_GAP, и от дальнего кадра остаётся
 * мягкая кромка; на широком он растворяется на глазах.
 *
 * Считаем в пикселях экрана и переводим в доли ширины самого кадра — вуаль
 * лежит на нём и поворачивается вместе с ним. columnWidth === null — ширина
 * колонки неизвестна: берём самый тесный случай.
 */
export function fogBand(cardWidth: number, columnWidth: number | null): FogBand {
  const edge = sideEdge(cardWidth);
  // Кадра нет или он шире самой перспективы — считать нечего, вуали нет.
  if (!(cardWidth > 0) || !(edge > 0) || !Number.isFinite(edge)) return { from: 100, to: 100 };
  const far = STOPS[2];
  const turn = (far.rot * Math.PI) / 180;
  // Ближний край дальнего кадра и то, как его ширина и глубина ложатся на экран.
  const hinge = (far.x / 100 - 0.5) * cardWidth;
  const flat = far.scale * Math.cos(turn) * cardWidth;
  const depth = far.scale * Math.sin(turn) * cardWidth;
  /** Какая доля ширины кадра видна в точке экрана x (от центра сцены). */
  const share = (x: number) => clamp((PERSPECTIVE * (x - hinge)) / (flat * PERSPECTIVE + depth * x), 0, 1);

  const room = columnWidth === null ? EDGE_GAP : columnWidth / 2 - edge;
  const reach = clamp(room - FOG_REST, 0, FOG_REACH);
  const from = share(edge - (reach * FOG_HEAD) / (1 - FOG_HEAD));
  const to = Math.max(from, share(edge + reach));
  return { from: Math.round(from * 1000) / 10, to: Math.round(to * 1000) / 10 };
}

/* ---------- позиция ---------- */

export type Track = {
  /** id кадров в порядке показа — по ним видно, что состав карусели сменился. */
  ids: readonly string[];
  /** Какое место сейчас в центре; у бесконечной карусели растёт и убывает без границ. */
  pos: number;
};

export const mod = (n: number, m: number) => ((n % m) + m) % m;

export function isLoop(count: number): boolean {
  return count >= LOOP_MIN;
}

/** Номер активного кадра в списке. */
export function activeIndex(track: Track): number {
  return track.ids.length ? mod(track.pos, track.ids.length) : 0;
}

/** Кратчайший путь по кругу: из 12 кадров от 1-го к 11-му — два шага назад, а не десять вперёд. */
export function wrapDelta(delta: number, count: number): number {
  if (count <= 0) return 0;
  const forward = mod(delta, count);
  return forward > count / 2 ? forward - count : forward;
}

export function sameIds(a: readonly string[], b: readonly string[]): boolean {
  return a === b || (a.length === b.length && a.every((id, i) => id === b[i]));
}

/**
 * Состав карусели сменился (витрина обновилась, пока вкладка открыта).
 * Держимся за кадр, который был в центре; если его больше нет — за его место.
 */
export function retrack(track: Track, ids: readonly string[]): Track {
  if (!ids.length) return { ids, pos: 0 };
  const was = track.ids.length ? mod(track.pos, track.ids.length) : 0;
  const kept = track.ids.length ? ids.indexOf(track.ids[was]) : -1;
  return { ids, pos: kept >= 0 ? kept : Math.min(was, ids.length - 1) };
}

/** Позиция под текущий список кадров: прежняя, если состав тот же. */
export function syncTrack(track: Track, ids: readonly string[]): Track {
  return sameIds(track.ids, ids) ? track : retrack(track, ids);
}

/**
 * Сдвинуться на steps мест. У короткой карусели есть края: стрелка и палец за
 * них не ведут, а сама она (auto) с последнего кадра возвращается к первому.
 */
export function moveTrack(track: Track, steps: number, auto = false): Track {
  const count = track.ids.length;
  if (count < 2 || !steps) return track;
  if (isLoop(count)) return { ids: track.ids, pos: track.pos + steps };
  let pos = track.pos + steps;
  if (pos < 0 || pos >= count) pos = auto ? (pos < 0 ? count - 1 : 0) : clamp(pos, 0, count - 1);
  return pos === track.pos ? track : { ids: track.ids, pos };
}

/** Перейти к кадру с номером index — по кругу кратчайшим путём. */
export function jumpTrack(track: Track, index: number): Track {
  const count = track.ids.length;
  if (count < 2) return track;
  const target = clamp(Math.round(index), 0, count - 1);
  return moveTrack(track, isLoop(count) ? wrapDelta(target - activeIndex(track), count) : target - track.pos);
}

export type Slot = {
  /** Номер места; у бесконечной карусели — любое целое. */
  v: number;
  /** Какой кадр списка стоит на этом месте. */
  index: number;
  /** На сколько мест от центра; дробное, пока кадры ведут пальцем. */
  d: number;
};

/** Места, которые сейчас живут в разметке: активное и по REACH с каждой стороны. */
export function slotsAround(pos: number, shift: number, count: number): Slot[] {
  if (count <= 0) return [];
  const at = pos + shift;
  const mid = Math.round(at);
  const loop = isLoop(count);
  const from = loop ? mid - REACH : Math.max(0, mid - REACH);
  const to = loop ? mid + REACH : Math.min(count - 1, mid + REACH);
  const out: Slot[] = [];
  for (let v = from; v <= to; v++) out.push({ v, index: mod(v, count), d: v - at });
  return out;
}

/* ---------- перетаскивание ---------- */

/** На какую долю шага кадры ушли за пальцем (dx < 0 — тянут влево, к следующему). */
export function dragShift(dx: number, step: number, pos: number, count: number): number {
  if (step <= 0 || count < 2) return 0;
  const raw = clamp(-dx / step, -DRAG_REACH, DRAG_REACH);
  if (isLoop(count)) return raw;
  // За краем короткой карусели пусто: кадр тянется туго и недалеко — видно, что дальше ничего нет.
  const lo = -pos;
  const hi = count - 1 - pos;
  if (raw < lo) return lo - Math.min(EDGE_GIVE, (lo - raw) * EDGE_GIVE);
  if (raw > hi) return hi + Math.min(EDGE_GIVE, (raw - hi) * EDGE_GIVE);
  return raw;
}

/** Сколько мест пролистать, когда палец отпустили. */
export function dragSteps(dx: number, step: number): number {
  if (step <= 0 || Math.abs(dx) < SWIPE_PX) return 0;
  const steps = clamp(Math.round(Math.abs(dx) / step), 1, DRAG_REACH);
  return dx < 0 ? steps : -steps;
}

/* ---------- ширина кадра ---------- */

/** Потолок ширины кадра и его доля от ширины окна — из макета. */
export const CARD_MAX = 760;
export const CARD_VW = 0.58;
/** Сцена выше кадра на столько (по 24 px сверху и снизу). */
export const STAGE_PAD = 48;
/**
 * Что под сценой тоже должно остаться над панелью запроса: ряд названий (или
 * сегментов) — он на 24 px ниже сцены — и зазор до панели.
 */
export const REEL_FOOT = 44;
/** Ради места над панелью запроса карусель уступает не больше этой доли ширины. */
const FOLD_FLOOR = 0.62;
const CARD_MIN = 240;

/**
 * Самый широкий кадр, при котором соседи (|d| = 1) видны целиком в колонке
 * шириной stageWidth. Внешний край соседа повёрнут к зрителю, и перспектива
 * увеличивает его: чем шире кадр, тем сильнее.
 */
export function fanWidth(stageWidth: number): number {
  const side = STOPS[1];
  const turn = (side.rot * Math.PI) / 180;
  const reach = side.x / 100 - 0.5 + side.scale * Math.cos(turn);
  const depth = side.scale * Math.sin(turn);
  const half = stageWidth / 2 - EDGE_GAP;
  return half <= 0 ? 0 : (half * PERSPECTIVE) / (reach * PERSPECTIVE + depth * half);
}

/**
 * Ширина кадра по месту. По ширине — макет (58vw, не шире 760) и колонка
 * (соседи видны целиком). По высоте — room: сколько места между верхом сцены и
 * панелью запроса; первый экран обещает показать карусель над ней целиком.
 * Если места мало (невысокий ноутбук), уступаем до FOLD_FLOOR и не дальше:
 * маленькая карусель хуже, чем карусель, к которой надо чуть прокрутить.
 * room === null — высота неизвестна (карусель вне ленты студии).
 */
export function fitWidth(viewportWidth: number, stageWidth: number, room: number | null): number {
  const wide = Math.max(CARD_MIN, Math.min(CARD_VW * viewportWidth, CARD_MAX, fanWidth(stageWidth)));
  if (room === null) return Math.round(wide);
  const fold = ((room - STAGE_PAD) * 16) / 9;
  return Math.round(Math.max(Math.min(wide, fold), wide * FOLD_FLOOR));
}

/* ---------- названия кадров и их ряд ---------- */

/** Что нужно знать о кадре, чтобы его назвать. */
export type Nameable = {
  /** Ключ сценария; null — сценария нет. */
  scenario: string | null;
  title: string;
  /** Видеостудия — название модели. */
  subtitle: string;
};

/** Чем номер повтора отделён от имени: «Реклама товара · 2». */
export const NAME_SEP = " · ";

/**
 * Короткое имя каждого кадра — им подписан чип под каруселью и сам кадр.
 * Имя сценария; без сценария («Другое», ключ, которого нет в переводах) —
 * название работы, а нет и его — модель. Второй ролик того же сценария называем
 * его собственным названием, если оно есть и отличается. Пустая строка —
 * назвать нечем, чип подпишут номером.
 *
 * Двух одинаковых имён в ряду нет: человек не различит такие чипы. В карусели
 * на несколько десятков роликов совпадения — обычное дело: три «Киносцены» без
 * своих названий, пять работ «Другое» на одной модели. Повтору дописываем
 * номер, по порядку появления: «Киносцена», «Киносцена · 2», «Киносцена · 3».
 * Номер от языка не зависит — отдельной строки перевода ему не нужно.
 *
 * defaultName — имя сценария, каким его знает сервер (scenarios.scenarioDefault).
 * Панель и команда съёмки ставят его работе в название сами, и на другом языке
 * сайта оно не совпадает с переводом: без этой сверки второй ролик сценария
 * вышел бы с русским именем посреди английских.
 */
export function reelNames(
  items: readonly Nameable[],
  scenarioName: (key: string) => string,
  defaultName: (key: string) => string = () => "",
): string[] {
  const taken = new Set<string>();
  const used = new Set<string>();
  return items.map((item) => {
    const key = item.scenario;
    const scenario = key ? scenarioName(key) : "";
    let base = item.title || item.subtitle;
    if (key && scenario) {
      const own = item.title !== scenario && item.title !== defaultName(key) ? item.title : "";
      base = taken.has(scenario) && own ? own : scenario;
      taken.add(scenario);
    }
    if (!base) return "";
    // Номер ищем свободный: владелец мог и сам назвать работу «Киносцена · 2».
    let name = base;
    for (let n = 2; used.has(name); n++) name = `${base}${NAME_SEP}${n}`;
    used.add(name);
    return name;
  });
}

/**
 * Кадр назван одной лишь моделью (с номером повтора или без): у работы нет ни
 * сценария, ни своего названия. На кадре модель уже стоит плашкой — заголовком
 * её второй раз не пишут.
 */
export function namedByModel(name: string, item: Pick<Nameable, "title" | "subtitle">): boolean {
  if (!item.subtitle) return false;
  return name === item.subtitle || (!item.title && name.startsWith(`${item.subtitle}${NAME_SEP}`));
}

/**
 * Куда прокрутить ряд названий, чтобы чип встал посередине. У краёв ряд
 * упирается: первый и последний чип остаются у своего края, а ряд, который
 * помещается целиком, не двигается вовсе.
 */
export function railScroll(chipLeft: number, chipWidth: number, viewWidth: number, fullWidth: number): number {
  const room = Math.max(0, fullWidth - viewWidth);
  return Math.round(clamp(chipLeft + chipWidth / 2 - viewWidth / 2, 0, room));
}

/**
 * Ряд длиннее стольких названий получает стрелки по краям. Двенадцать тоже
 * помещаются не везде, но там спрятаны два-четыре чипа, и до них одно нажатие
 * на крайний. В ряду на 48 спрятано сорок: колесо мыши ведёт страницу, а не
 * ряд, и добраться до них без стрелок можно, только листая саму карусель.
 */
export const RAIL_WHOLE = 12;

export type RailArrows = { prev: boolean; next: boolean };

/**
 * Какие стрелки нужны ряду названий: только длинному и только с той стороны,
 * где у него есть продолжение (fade — что useEdgeFade намерил у краёв).
 */
export function railArrows(count: number, fade: EdgeFade): RailArrows {
  const paged = count > RAIL_WHOLE;
  return { prev: paged && (fade === "mid" || fade === "end"), next: paged && (fade === "start" || fade === "mid") };
}

/* ---------- лента телефона: переход к кадру ---------- */

/**
 * Дольше лента телефона к кадру не едет. Если за это время она на него так и не
 * встала (её перехватили пальцем, браузер не прокрутил), часы карусели отпускаем.
 */
export const JUMP_MS = 1500;

/**
 * Ленту телефона ведут к кадру `to` — нажали чип или соседа, карусель
 * перелистнулась сама. Какой кадр она теперь ждёт; null — ждать нечего, он уже
 * в центре. Пока лента едет, активным считается прежний кадр, и часы карусели
 * на это время стоят: иначе заливка его чипа, дойдя до конца в пути, увела бы
 * ленту к его соседу, а нажатие пропало бы.
 */
export function jumpTarget(to: number, centered: number): number | null {
  return to === centered ? null : to;
}

/**
 * Лента встала на кадр `settled`: доехала ли она, куда её вели. Кадр, на котором
 * она задержалась по пути, и прежний кадр в самом начале пути — не в счёт:
 * отпусти они часы, те успели бы перелистнуть карусель до приезда.
 */
export function jumpDone(target: number | null, settled: number): boolean {
  return target !== null && settled === target;
}

/* ---------- лента телефона: какие кадры живые ---------- */

/**
 * Лента до стольких кадров живёт целиком, как жила всегда: двенадцать постеров
 * телефону не в тягость. В более длинной (владелец задаёт до 48 роликов)
 * картинку, подпись и кнопки получают только кадры рядом с активным; остальные
 * стоят пустыми рамками и держат ширину ленты и места прилипания.
 */
export const STRIP_WHOLE = 12;
/** Сколько кадров по каждую сторону от активного живые: соседи видны краем, следующие за ними готовы к смахиванию. */
export const STRIP_NEAR = 2;

/**
 * Живой ли кадр i ленты телефона: есть ли у него картинка, ролик и подпись.
 * Считаем от кадра, вставшего в центр (active), а не от прокрутки: кадры,
 * мимо которых лента едет к далёкому, ничего не грузят. Кадр, к которому она
 * едет (aim), и его соседи оживают заранее — к приезду они на месте. Когда
 * ленту ведут пальцем, на месте aim — кадр под ним (stripSeen).
 */
export function stripLive(i: number, active: number, aim: number | null, count: number): boolean {
  if (count <= STRIP_WHOLE) return true;
  const near = (to: number) => Math.abs(i - to) <= STRIP_NEAR;
  // С последнего кадра карусель сама возвращается к первому.
  return near(active) || (aim !== null && near(aim)) || (i === 0 && active === count - 1);
}

/**
 * Где лента телефона. centered — кадр, вставший в центр: в нём играет ролик и от
 * него идут часы; таким кадр становится, только простояв в центре. passing —
 * кадр, который в центре прямо сейчас, пока ленту ведут пальцем и встать она
 * ещё не успела; null — лента стоит или едет сама.
 */
export type StripSpot = { centered: number; passing: number | null };

export const STRIP_START: StripSpot = { centered: 0, passing: null };

/**
 * Наблюдатель ленты увидел в центре кадр seen. Активным он станет, когда лента
 * встанет, а живым (stripLive — вторым кадром отсчёта, на месте aim) должен
 * быть уже сейчас: между быстрыми смахиваниями лента встать не успевает, и
 * под пальцем шли бы пустые рамки. Когда лента едет сама (target — чип, сосед,
 * часы карусели), кадры по дороге по-прежнему ничего не грузят. Короткой ленте
 * следить не за чем: она живёт целиком.
 */
export function stripSeen(spot: StripSpot, target: number | null, seen: number, count: number): StripSpot {
  const passing = target === null && count > STRIP_WHOLE ? seen : null;
  return passing === spot.passing ? spot : { centered: spot.centered, passing };
}

/**
 * Лента простояла на кадре settled: теперь активный он. Кадра «под пальцем»
 * больше нет — живые снова считаются только от активного (и от aim).
 */
export function stripSettled(spot: StripSpot, settled: number): StripSpot {
  return spot.centered === settled && spot.passing === null ? spot : { centered: settled, passing: null };
}

/** Вертикальный ролик («9:16»). Запись, которую не разобрать, вертикальной не считаем. */
export function isPortrait(aspect: string): boolean {
  const m = /^\s*(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)\s*$/.exec(aspect);
  if (!m) return false;
  const width = Number(m[1]);
  return width > 0 && Number(m[2]) > width;
}

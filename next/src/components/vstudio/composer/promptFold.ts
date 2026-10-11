/**
 * Видеостудия, панель запроса: когда поле запроса свёрнуто (чистая логика).
 *
 * Длинный запрос занимает полэкрана и закрывает готовый ролик. Поэтому поле
 * отдыхает свёрнутым (пара строк с затуханием), пока человек не работает в
 * панели, и разворачивается, когда он возвращается к тексту. Решение — здесь:
 * состояние, события и условия, при которых сворачивать нельзя. Паузу после
 * ухода и нажатия ведёт foldDriver, фокус и окна в события переводит
 * usePromptFold, а редактор меряет текст и обрезает то же самое поле
 * (editor/useFoldClip). Проверяют node-тесты promptFold.test.mjs.
 */
import type { PromptFold } from "@/lib/vstudio/types";

/** Пауза после ухода из панели: клик по её же кнопке успевает вернуть фокус, а лента не дёргается под пальцем. */
export const FOLD_LEAVE_MS = 250;
/** Сколько длится движение высоты поля. */
export const FOLD_SLIDE_MS = 240;
/** Строк на виду в свёрнутом поле: с 768 px и на телефоне. */
export const FOLD_LINES = { wide: 2, phone: 1 } as const;
/**
 * Насколько текст должен быть выше свёрнутого поля, чтобы его сворачивать, и
 * ниже чего — перестать; в долях строки. Сворачивать стоит, когда прячется
 * хотя бы строка: на телефоне свёрнутое поле — это высота пустого (52 px), в
 * нём видны первая строка и почти вся вторая, и запрос в две строки от
 * сворачивания выиграл бы 12 px, а получил бы кнопку и рывок при каждом фокусе.
 * Между порогами решение не меняется: строка с чипом на пиксель-другой выше
 * обычной, и у самой границы кнопка мигала бы.
 */
export const FOLD_ENTER_LINES = 0.75;
export const FOLD_EXIT_LINES = 0.5;

export type FoldMachine = {
  fold: PromptFold;
  /** Человек ушёл из панели: ждём паузу и условия, чтобы свернуть. */
  leaving: boolean;
  /** Развернуть попросили под нажатой кнопкой мыши: сделаем, когда её отпустят. */
  waking: boolean;
};

/** Пока хоть одно из этого правда, само поле не сворачивается. */
export type FoldGuards = {
  /** Кнопка мыши или палец ещё нажаты — где угодно на странице. */
  pointerDown: boolean;
  /** Фокус в панели или в её окошке. */
  focusInside: boolean;
  /** Идёт набор через IME. */
  composing: boolean;
  /** В поле выделен текст. */
  selection: boolean;
  /** Поле развёрнуто на весь экран. */
  fullscreen: boolean;
  /** Открыто окошко, шторка или окно панели, выбор «@» или выбор файла. */
  overlay: boolean;
  /** Из панели что-то тащат (чип в лотке). */
  dragging: boolean;
  /** Панель показывает то, что мешает запуску: подсказки-ошибки, конфликт кадров, «Сжать с ИИ». */
  problem: boolean;
};

export const NO_GUARDS: FoldGuards = {
  pointerDown: false,
  focusInside: false,
  composing: false,
  selection: false,
  fullscreen: false,
  overlay: false,
  dragging: false,
  problem: false,
};

/** Кто просит развернуть поле. typed — в текст запроса что-то ввели. */
export type FoldOpenBy = "field" | "toggle" | "typed" | "filled" | "mention" | "drop" | "problem";

export type FoldEvent =
  | { type: "open"; by: FoldOpenBy }
  /** Кнопка «Свернуть запрос». */
  | { type: "shut" }
  /** Фокус ушёл из панели или нажали мимо неё. */
  | { type: "leave" }
  /** Человек снова в панели, но не в поле: фокус на её кнопке, нажатие внутри неё, открылась её шторка. */
  | { type: "return" }
  | { type: "pointerUp" }
  /** Пауза после ухода истекла. */
  | { type: "timer" }
  /** Запуск принят. typing — его отправили с клавиатуры и курсор всё ещё в поле. */
  | { type: "run"; typing: boolean }
  /** Текст снова помещается в свёрнутое поле. */
  | { type: "fits" }
  /** Открыли другой проект. */
  | { type: "reset" };

/** Мягкие причины не спорят с человеком: свернул кнопкой — так и остаётся. */
const SOFT: readonly FoldOpenBy[] = ["drop", "problem"];
/**
 * Эти причины нажатой кнопки мыши не ждут. Кнопка «Показать весь запрос» срабатывает по
 * отпусканию сама. Ввод — страховка: нажатие, отпускания которого страница так и не увидела,
 * иначе оставило бы человека печатать в обрезанное поле.
 */
const AT_ONCE: readonly FoldOpenBy[] = ["toggle", "typed"];

const GUARD_ORDER: readonly (keyof FoldGuards)[] = [
  "pointerDown",
  "focusInside",
  "composing",
  "selection",
  "fullscreen",
  "overlay",
  "dragging",
  "problem",
];

/** Что сейчас не даёт свернуть поле; null — можно. */
export function foldBlocked(g: FoldGuards): keyof FoldGuards | null {
  return GUARD_ORDER.find((k) => g[k]) ?? null;
}

const OPEN: FoldMachine = { fold: "open", leaving: false, waking: false };

/**
 * Следующее состояние. Ничего не изменилось — возвращается тот же объект:
 * по этому вызывающий понимает, что таймер ухода упёрся в условие и его надо
 * перезапустить, когда условие изменится.
 */
export function foldStep(m: FoldMachine, e: FoldEvent, g: FoldGuards): FoldMachine {
  switch (e.type) {
    case "open": {
      const soft = SOFT.includes(e.by);
      if (m.fold === "open") {
        // Мягкая причина уход не отменяет: к тексту человек не вернулся.
        return soft || !m.leaving ? m : OPEN;
      }
      if (soft && m.fold === "shut") return m;
      // Под нажатой кнопкой текст не двигаем: клик по свёрнутому полю иначе стал бы выделением
      // от первой строки до той, что приехала под указатель.
      if (g.pointerDown && !AT_ONCE.includes(e.by)) return m.waking ? m : { ...m, waking: true };
      // Проблему показали, а человек не в панели: когда она исчезнет, поле свернётся обратно само.
      if (e.by === "problem") return { fold: "open", leaving: !g.focusInside, waking: false };
      return OPEN;
    }
    case "shut":
      return m.fold === "shut" && !m.leaving && !m.waking ? m : { fold: "shut", leaving: false, waking: false };
    case "leave": {
      // Шторка или окно панели открыты: фокус и нажатия в них — всё ещё работа в панели, а не уход.
      const stays = g.overlay || g.fullscreen;
      const leaving = m.fold === "open" && (stays ? m.leaving : true);
      return m.leaving === leaving && !m.waking ? m : { ...m, leaving, waking: false };
    }
    case "return":
      return m.leaving ? { ...m, leaving: false } : m;
    case "pointerUp":
      return m.waking ? OPEN : m;
    case "timer":
      if (!m.leaving) return m;
      if (m.fold !== "open") return { ...m, leaving: false };
      if (foldBlocked(g)) return m;
      return { fold: "rest", leaving: false, waking: false };
    case "run":
      // С клавиатуры и курсор в поле — человек пишет дальше; иначе он ждёт результат, поле уступает место.
      if (e.typing || m.fold !== "open") return m;
      return { fold: "rest", leaving: false, waking: false };
    case "fits":
    case "reset":
      // Кнопки при коротком тексте нет, а новый проект начинает с правила по умолчанию.
      return m.fold === "shut" ? { ...m, fold: "rest" } : m;
    default: {
      const never: never = e;
      void never;
      return m;
    }
  }
}

/** Поле обрезано до свёрнутой высоты. Во весь экран — никогда. */
export function foldCompact(fold: PromptFold, fullscreen: boolean): boolean {
  return fold !== "open" && !fullscreen;
}

/**
 * Мешает ли что-то запуску, когда ответа на изменённый запрос ещё нет. Подсказки приходят
 * вместе с ценой: сменили модель или параметр — и до ответа их нет вовсе. Это «неизвестно», а
 * не «исправлено»: держим прошлый ответ (last), иначе поле на каждый такой клик сворачивалось
 * бы и разворачивалось обратно, когда ошибка вернётся с ценой.
 */
export function lastKnown(known: boolean, now: boolean, last: boolean): boolean {
  return known ? now : last;
}

/* ------------------------------------------------------------------ */
/* Высота                                                              */
/* ------------------------------------------------------------------ */

export type FoldBox = {
  /** Высота текста вместе с полями поля, px. */
  content: number;
  lineHeight: number;
  padTop: number;
  padBottom: number;
  /** Ниже этого поле не бывает и с одной строкой. */
  minHeight: number;
};

const num = (v: number) => (Number.isFinite(v) && v > 0 ? v : 0);

/**
 * Свёрнутая высота: столько-то строк с полями, но не ниже обычной высоты
 * пустого поля — короткий запрос сворачивание не должно задевать вовсе.
 */
export function compactHeight(box: Omit<FoldBox, "content">, lines: number): number {
  const rows = Math.max(1, Math.floor(num(lines)) || 1);
  return Math.ceil(Math.max(num(box.minHeight), rows * num(box.lineHeight) + num(box.padTop) + num(box.padBottom)));
}

/** Есть ли тексту что прятать в свёрнутом поле. prev — прошлый ответ (см. FOLD_ENTER_LINES). */
export function foldNeeded(prev: boolean, box: Pick<FoldBox, "content" | "lineHeight">, compact: number): boolean {
  const line = num(box.lineHeight);
  if (!(compact > 0) || !(line > 0) || !Number.isFinite(box.content)) return false;
  return box.content - compact > line * (prev ? FOLD_EXIT_LINES : FOLD_ENTER_LINES);
}

/**
 * Видеостудия, панель запроса: «водитель» свёрнутого поля — состояние из
 * promptFold плюс всё, что тянется во времени: пауза после ухода из панели,
 * нажатые указатели, окно, потерявшее фокус.
 *
 * Без DOM и без React: таймер, «где фокус», «выделен ли текст» и «открыто ли
 * окошко» приходят снаружи (FoldDriverEnv). Поэтому порядок событий браузера —
 * нажали, фокус ушёл, отпустили, пауза — проверяется node-тестами
 * (foldDriver.test.mjs), а usePromptFold только переводит события в вызовы.
 */
import type { PromptFold } from "@/lib/vstudio/types";
import { FOLD_LEAVE_MS, foldStep, type FoldEvent, type FoldGuards, type FoldMachine, type FoldOpenBy } from "./promptFold";

export type FoldDriverEnv = {
  /** Новое состояние поля — в стор. */
  commit: (fold: PromptFold) => void;
  /**
   * Фокус сейчас в панели или в её окошке. Спрашиваем каждый раз, а не помним:
   * кнопка, которую выключили или убрали, теряет фокус без события blur.
   */
  focused: () => boolean;
  /** В поле выделен текст. */
  selection: () => boolean;
  /** Открыто окошко панели, выбор «@» или выбор файла (dockHold). */
  held: () => boolean;
  setTimer: (fn: () => void, ms: number) => unknown;
  clearTimer: (id: unknown) => void;
};

/** То, что композер знает из стора и своего состояния. */
export type FoldInputs = {
  fullscreen: boolean;
  /** Открыта шторка или окно: библиотека, параметры, пополнение, вход, «Создать картинку», «Сжать с ИИ». */
  overlay: boolean;
  problem: boolean;
};

export type FoldDriver = ReturnType<typeof createFoldDriver>;

export function createFoldDriver(env: FoldDriverEnv, fold: PromptFold = "rest") {
  let m: FoldMachine = { fold, leaving: false, waking: false };
  let inputs: FoldInputs = { fullscreen: false, overlay: false, problem: false };
  let timer: unknown = null;
  const pointers = new Set<number>();
  /** Нажатая сейчас мышь: только её отпускание может не дойти до страницы вовсе (см. menu). */
  let mouse: number | null = null;
  /** Последнее нажатие началось в панели (в том числе в её окошке). */
  let pressInside = false;
  /** Фокус ушёл из панели, и с тех пор в неё не возвращались ни фокусом, ни нажатием. */
  let left = false;
  let composing = false;
  let dragging = false;
  /** Фокус ушёл вместе с фокусом окна: уход ли это, станет ясно, когда окно вернётся. */
  let away = false;

  const guards = (): FoldGuards => ({
    pointerDown: pointers.size > 0,
    focusInside: env.focused(),
    composing,
    selection: env.selection(),
    fullscreen: inputs.fullscreen,
    overlay: inputs.overlay || env.held(),
    dragging,
    problem: inputs.problem,
  });

  const stop = () => {
    if (timer != null) env.clearTimer(timer);
    timer = null;
  };
  const arm = () => {
    stop();
    timer = env.setTimer(() => {
      timer = null;
      send({ type: "timer" });
    }, FOLD_LEAVE_MS);
  };

  function send(e: FoldEvent): FoldMachine {
    const prev = m;
    m = foldStep(prev, e, guards());
    if (m.fold !== prev.fold) env.commit(m.fold);
    if (!m.leaving) stop();
    // Пауза считается от последнего повода: упёршийся в условие таймер сам себя не заводит —
    // его заведёт nudge, когда условие изменится.
    else if (e.type !== "timer") arm();
    return m;
  }

  /** Условие могло измениться: если поле ждёт ухода, пауза отсчитывается заново. */
  const nudge = () => {
    if (m.leaving) arm();
  };

  const pointerUp = (id: number) => {
    if (id === mouse) mouse = null;
    if (!pointers.delete(id) || pointers.size > 0) return;
    send({ type: "pointerUp" });
    // Нажали мимо панели, а фокуса в ней и не было (Safari, поле развёрнуто кнопкой): это уход.
    if (!pressInside && !env.focused()) send({ type: "leave" });
    else nudge();
  };

  return {
    state: (): FoldMachine => m,

    open: (by: FoldOpenBy) => send({ type: "open", by }),
    /** Кнопка «Свернуть запрос» / «Показать весь запрос». */
    toggle: () => send(m.fold === "open" ? { type: "shut" } : { type: "open", by: "toggle" }),
    /**
     * Запуск принят. typing — человек пишет дальше (как это понять, знает usePromptFold). Ответ —
     * убрать ли курсор из поля: только если не пишет. По виду поля этого не решить: поле, в
     * которое нажали и ещё не отпустили, тоже не развёрнуто, а курсор в нём — свежий.
     */
    ran(typing: boolean): boolean {
      send({ type: "run", typing });
      return !typing;
    },
    fits: () => send({ type: "fits" }),
    reset: () => send({ type: "reset" }),

    setInputs(next: FoldInputs) {
      const prev = inputs;
      inputs = next;
      // Шторка открылась раньше, чем фокус ушёл в неё, или позже — в любом порядке это не уход.
      if (next.overlay && !prev.overlay) send({ type: "return" });
      if (next.problem && !prev.problem) send({ type: "open", by: "problem" });
      nudge();
    },

    /** Фокус пришёл в панель: в само поле или на её кнопку. */
    focusIn(inField: boolean) {
      away = false;
      left = false;
      send(inField ? { type: "open", by: "field" } : { type: "return" });
    },
    /** Фокус ушёл с элемента панели. windowFocused — document.hasFocus() в этот момент. */
    focusOut(windowFocused: boolean) {
      // Другая вкладка, другое окно, выбор файла: из панели человек не уходил.
      if (!windowFocused) {
        away = true;
        return;
      }
      // Нажали кнопку самой панели. Chrome переведёт на неё фокус следом, Safari не переведёт
      // вовсе — в обоих случаях человек остался в панели.
      if (pointers.size > 0 && pressInside) return;
      left = true;
      send({ type: "leave" });
    },
    /** Окно снова с фокусом (звать после того, как браузер вернул фокус элементу). */
    windowFocus() {
      if (!away) return;
      away = false;
      if (env.focused()) return;
      left = true;
      send({ type: "leave" });
    },
    windowBlur() {
      // Отпускание вне окна до нас может не дойти.
      if (pointers.size === 0) return;
      pointers.clear();
      mouse = null;
      send({ type: "pointerUp" });
      nudge();
    },

    /** Любое нажатие на странице (окно, фаза перехвата — раньше, чем pressedInside). */
    pointerDown(id: number, byMouse = false) {
      pointers.add(id);
      if (byMouse) mouse = id;
      pressInside = false;
    },
    /** То же нажатие дошло до панели по дереву React — значит, оно в ней или в её окошке. */
    pressedInside() {
      pressInside = true;
      left = false;
      send({ type: "return" });
    },
    pointerUp,
    /**
     * Открылось контекстное меню. На macOS и Linux оно открывается по нажатию и забирает
     * отпускание себе: нажатие осталось бы висеть до следующего клика, а с ним — отложенный
     * разворот поля, в котором уже стоит курсор, и уход, который некому досчитать. Поэтому меню —
     * тоже конец нажатия. Только для мыши: палец при долгом нажатии ещё на экране. На Windows
     * отпускание приходит раньше меню, и снимать здесь уже нечего.
     */
    menu() {
      if (mouse !== null) pointerUp(mouse);
    },

    /** Окошко панели открылось или закрылось (dockHold). */
    holdChanged() {
      // Уход, пока окошко ещё было открыто, уходом не посчитался: нажатие мимо панели (в окошке —
      // значит, в панели) или фокус, ушедший с клавиатуры. Раз окошек больше нет, а человек не в
      // панели, — уход. Последнее нажатие в панели само по себе не значит «он ещё здесь»: после
      // него фокус мог уйти клавишей Tab (left).
      const gone = !env.held() && !inputs.overlay && pointers.size === 0 && (left || !pressInside) && !env.focused();
      if (gone) send({ type: "leave" });
      else nudge();
    },

    composition(on: boolean) {
      composing = on;
      if (!on) nudge();
    },
    drag(on: boolean) {
      dragging = on;
      if (!on) nudge();
    },
    nudge,
    dispose: stop,
  };
}

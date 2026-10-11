"use client";

/**
 * Видеостудия, панель запроса: свёрнутое поле — проводка.
 *
 * Решает promptFold (чистая логика), паузу и нажатия ведёт foldDriver. Этот хук
 * только переводит события в его вызовы: фокус и нажатия — с корня композера
 * (события React всплывают и из окошек, нарисованных порталом, поэтому «в
 * панели» значит и «в её окошке»), отпускание, выделение и фокус окна — с
 * window и document. Состояние поля лежит в сторе (ui.promptFold), «тексту есть
 * что прятать» приходит от редактора (editor/useFoldClip).
 */
import { useCallback, useEffect, useMemo, useRef, useState, type Dispatch, type SyntheticEvent } from "react";
import type { PromptFold, Uid, VsAction } from "@/lib/vstudio/types";
import type { PromptFoldProps } from "../editor/editorTypes";
import { dockHeld, subscribeDockHold } from "./dockHold";
import { createFoldDriver, type FoldDriver } from "./foldDriver";
import { FOLD_LINES, foldCompact, type FoldOpenBy } from "./promptFold";

/** Блок с текстом запроса: его ставит редактор (и запасная textarea). */
const PROMPT = "[data-vs-prompt]";

function inPrompt(node: EventTarget | null): boolean {
  return node instanceof Element && node.closest(PROMPT) !== null;
}

/** Элемент с курсором, если курсор в тексте запроса. */
function promptFocus(): HTMLElement | null {
  const el = document.activeElement;
  return el instanceof HTMLElement && inPrompt(el) ? el : null;
}

/**
 * Элемент панели, который последним получил фокус. «Фокус в панели» — пока он
 * же и активен в документе: кнопка, которую выключили или убрали, теряет фокус
 * без события blur, и флаг по событиям остался бы взведённым навсегда.
 */
function focusKeeper() {
  let el: Element | null = null;
  return {
    set(next: Element | null) {
      el = next;
    },
    here: () => el !== null && document.activeElement === el,
  };
}

function promptSelected(): boolean {
  const sel = document.getSelection();
  if (!sel || sel.isCollapsed) return false;
  const at = sel.anchorNode;
  return inPrompt(at instanceof Element ? at : (at?.parentElement ?? null));
}

export type PromptFoldOptions = {
  fold: PromptFold;
  dispatch: Dispatch<VsAction>;
  mobile: boolean;
  fullscreen: boolean;
  /** Открыта шторка или окно, о которых знает стор или сам композер. */
  overlay: boolean;
  /** Панель показывает то, что мешает запуску. */
  problem: boolean;
  projectUid: Uid | null;
};

export type PromptFoldWiring = {
  /** Пропс fold редактора. */
  editor: PromptFoldProps;
  /** Обработчики на корень композера. */
  root: {
    onFocus: (e: SyntheticEvent) => void;
    onBlur: () => void;
    onPointerDownCapture: (e: SyntheticEvent) => void;
    onKeyDownCapture: (e: SyntheticEvent) => void;
    onInput: (e: SyntheticEvent) => void;
    onCompositionStart: () => void;
    onCompositionEnd: () => void;
    onDragStart: () => void;
  };
  /** Развернуть: пример заполнил запрос, нажали «@», бросили файл. */
  open: (by: FoldOpenBy) => void;
  /**
   * Запуск принят. fromKeys — его отправили с клавиатуры (Ctrl/⌘+Enter); since — когда его
   * отправили (performance.now()): вернулся ли человек к тексту, пока ждали ответ.
   */
  ran: (fromKeys: boolean, since: number) => void;
};

export function usePromptFold(o: PromptFoldOptions): PromptFoldWiring {
  const { fold, dispatch, mobile, fullscreen, overlay, problem, projectUid } = o;
  const [cut, setCut] = useState(false);
  const cutNow = useRef(false);
  /** Когда человек последний раз что-то делал в самом тексте: фокус, нажатие, клавиша. */
  const touchedAt = useRef(0);

  // Один «водитель» на всю жизнь композера; dispatch у редьюсера постоянный.
  const [{ driver, focus }] = useState<{ driver: FoldDriver; focus: ReturnType<typeof focusKeeper> }>(() => {
    const keeper = focusKeeper();
    return {
      focus: keeper,
      driver: createFoldDriver(
        {
          commit: (next) => dispatch({ type: "ui/promptFold", fold: next }),
          focused: keeper.here,
          selection: promptSelected,
          held: dockHeld,
          setTimer: (fn, ms) => window.setTimeout(fn, ms),
          clearTimer: (id) => window.clearTimeout(id as number),
        },
        fold,
      ),
    };
  });

  useEffect(() => {
    driver.setInputs({ fullscreen, overlay, problem });
  }, [driver, fullscreen, overlay, problem]);

  // Другой проект начинает с правила по умолчанию: «свернул сам» относилось к прошлому запросу.
  const project = useRef(projectUid);
  useEffect(() => {
    if (project.current === projectUid) return;
    project.current = projectUid;
    driver.reset();
  }, [driver, projectUid]);

  useEffect(() => {
    const down = (e: PointerEvent) => driver.pointerDown(e.pointerId, e.pointerType === "mouse");
    const up = (e: PointerEvent) => driver.pointerUp(e.pointerId);
    const dragEnd = () => driver.drag(false);
    let refocus = 0;
    // Сначала браузер возвращает фокус элементу, на котором он был, — проверяем уже после этого.
    const winFocus = () => {
      window.clearTimeout(refocus);
      refocus = window.setTimeout(driver.windowFocus, 0);
    };
    // Перехват на окне: раньше обработчиков React и мимо любых stopPropagation ниже.
    window.addEventListener("pointerdown", down, true);
    window.addEventListener("pointerup", up, true);
    window.addEventListener("pointercancel", up, true);
    // Меню по правой кнопке: на macOS и Linux отпускания после него не будет.
    window.addEventListener("contextmenu", driver.menu, true);
    window.addEventListener("dragend", dragEnd, true);
    window.addEventListener("drop", dragEnd, true);
    window.addEventListener("blur", driver.windowBlur);
    window.addEventListener("focus", winFocus);
    document.addEventListener("selectionchange", driver.nudge);
    const offHold = subscribeDockHold(driver.holdChanged);
    // Композер вернулся на страницу, а стор помнит поле развёрнутым: в панели никого — это уход.
    if (!promptFocus()) driver.focusOut(true);
    return () => {
      window.removeEventListener("pointerdown", down, true);
      window.removeEventListener("pointerup", up, true);
      window.removeEventListener("pointercancel", up, true);
      window.removeEventListener("contextmenu", driver.menu, true);
      window.removeEventListener("dragend", dragEnd, true);
      window.removeEventListener("drop", dragEnd, true);
      window.removeEventListener("blur", driver.windowBlur);
      window.removeEventListener("focus", winFocus);
      document.removeEventListener("selectionchange", driver.nudge);
      offHold();
      window.clearTimeout(refocus);
      driver.dispose();
    };
  }, [driver]);

  const onCut = useCallback(
    (next: boolean) => {
      cutNow.current = next;
      setCut(next);
      // Кнопки при коротком тексте нет — «свернул сам» отменить было бы нечем.
      if (!next) driver.fits();
      // Текст дорос до обрезки, пока в нём курсор, — обрезать его под руками нельзя.
      else if (promptFocus()) driver.open("field");
    },
    [driver],
  );

  const onToggle = useCallback(() => {
    // Свёрнутое поле курсор не держит: печатать в обрезанный текст вслепую незачем.
    if (driver.toggle().fold !== "open") promptFocus()?.blur();
  }, [driver]);

  const ran = useCallback(
    (fromKeys: boolean, since: number) => {
      const field = promptFocus();
      // Курсор в поле, и запуск ушёл с клавиатуры или человек успел вернуться к тексту, пока ждали
      // ответ, — он пишет дальше. Нечего прятать — тоже не трогаем: иначе следующая же строка
      // легла бы в обрезанное поле. Остаётся курсор, который не ушёл с поля при нажатии кнопки
      // (Safari, iOS): человек ждёт результат, поле сворачиваем и курсор из него убираем.
      const typing = field !== null && (fromKeys || !cutNow.current || touchedAt.current > since);
      if (driver.ran(typing)) field?.blur();
    },
    [driver],
  );

  const root = useMemo<PromptFoldWiring["root"]>(() => {
    const touch = (e: SyntheticEvent) => {
      if (inPrompt(e.target)) touchedAt.current = performance.now();
    };
    return {
      onFocus: (e) => {
        touch(e);
        focus.set(e.target instanceof Element ? e.target : null);
        driver.focusIn(inPrompt(e.target));
      },
      onBlur: () => {
        const windowFocused = document.hasFocus();
        // Окно без фокуса: элемент остаётся «текущим», и фокус вернётся на него же.
        if (windowFocused) focus.set(null);
        driver.focusOut(windowFocused);
      },
      onPointerDownCapture: (e) => {
        touch(e);
        driver.pressedInside();
      },
      onKeyDownCapture: touch,
      // Экранная клавиатура клавиш может и не прислать — ввод приходит всегда.
      onInput: (e) => {
        touch(e);
        // В обрезанное поле не печатают — каким бы путём оно ни осталось свёрнутым под курсором.
        if (inPrompt(e.target)) driver.open("typed");
      },
      onCompositionStart: () => driver.composition(true),
      onCompositionEnd: () => driver.composition(false),
      onDragStart: () => driver.drag(true),
    };
  }, [driver, focus]);

  const compact = foldCompact(fold, fullscreen);
  const lines = mobile ? FOLD_LINES.phone : FOLD_LINES.wide;
  const editor = useMemo<PromptFoldProps>(() => ({ compact, lines, cut, onCut, onToggle }), [compact, lines, cut, onCut, onToggle]);

  return { editor, root, open: driver.open, ran };
}

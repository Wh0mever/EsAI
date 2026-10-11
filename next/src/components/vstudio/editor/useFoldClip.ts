"use client";

/**
 * Видеостудия, редактор промпта: свёрнутый вид поля.
 *
 * Свёрнутое поле — то же самое поле, только обрезанное: блоку с текстом
 * ставятся data-fold («панель просит свернуть») и data-fold-cut («тексту есть
 * что прятать»), а CSS (.vs-fold в globals.css) при обоих ограничивает высоту,
 * прячет прокрутку и гасит текст у среза. Редактор не пересоздаётся и никуда
 * не переезжает, поэтому курсор, история правок, выделение и черновик остаются
 * как были, а экранный диктор по-прежнему читает весь текст.
 *
 * Хук делает три вещи:
 *  — меряет текст (ResizeObserver на содержимом, а не счёт символов) и
 *    сообщает, помещается ли он в свёрнутую высоту;
 *  — ставит и снимает оба атрибута и ведёт высоту от одного вида к другому;
 *  — следит за прокруткой: в свёрнутом поле видно начало запроса, после
 *    разворота — место, где стоит курсор (или где человек остановился).
 *
 * Атрибуты ставятся прямо в DOM, а не рендером: замер приходит из
 * ResizeObserver перед отрисовкой кадра, и длинный черновик встаёт уже
 * обрезанным — без кадра, на котором панель занимает пол-экрана.
 *
 * Когда сворачивать, решает панель запроса (composer/promptFold.ts).
 */
import { useCallback, useEffect, useLayoutEffect, useRef, type RefObject } from "react";
import { compactHeight, foldNeeded, FOLD_SLIDE_MS, type FoldBox } from "../composer/promptFold";
import type { PromptFoldProps } from "./editorTypes";

/** То же движение, что у окошек панели (--vs-ease). */
const SLIDE_EASE = "cubic-bezier(0.16, 1, 0.3, 1)";

export type FoldClipOptions = {
  fold: PromptFoldProps | undefined;
  fullscreen: boolean;
  /** Блок, который обрезается. */
  clip: RefObject<HTMLElement | null>;
  /** Размеры текста; null — поле ещё не в документе. */
  box: () => FoldBox | null;
  /** Элемент, размер которого меняется вместе с текстом. */
  target: () => Element | null;
  /** Меняется, когда target стал другим элементом (пересоздан редактор). */
  targetKey?: unknown;
  /**
   * Показать строку с курсором (после разворота поля с фокусом). Без этого хук
   * прокрутку не трогает вовсе: textarea прокручивается сама в себе, и в
   * свёрнутом виде у неё видны те строки, на которых человек остановился.
   */
  revealCaret?: () => void;
};

/**
 * Размеры поля из его стилей; content — высота текста вместе с полями.
 * rows — сколько строк поле занимает и пустым (textarea с rows): ниже оно не
 * бывает, значит, и сворачивать до меньшего нечего.
 */
export function readFoldBox(el: HTMLElement, content: number, rows = 0): FoldBox {
  const cs = window.getComputedStyle(el);
  const px = (v: string) => parseFloat(v) || 0;
  const lineHeight = px(cs.lineHeight) || px(cs.fontSize) * 1.5;
  const padTop = px(cs.paddingTop);
  const padBottom = px(cs.paddingBottom);
  return {
    content,
    lineHeight,
    padTop,
    padBottom,
    minHeight: Math.max(px(cs.minHeight), rows > 0 ? rows * lineHeight + padTop + padBottom : 0),
  };
}

function reducedMotion(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Вне хука: внутри него линтер считает элемент из ref неизменяемым значением. */
function scrollToTop(el: HTMLElement, top: number): void {
  el.scrollTop = top;
}

/**
 * Довести высоту блока от from до той, что у него уже стоит. Возвращает
 * «оборвать»: высота, на которой оборвали, уходит в handoff — следующее
 * движение начнётся с неё, а не с прыжка.
 */
function slide(el: HTMLElement, from: number, done: () => void, handoff: (height: number) => void): (() => void) | undefined {
  const to = el.getBoundingClientRect().height;
  if (Math.abs(to - from) < 1 || typeof el.animate !== "function" || reducedMotion()) {
    done();
    return undefined;
  }
  // На время движения прокрутка спрятана: иначе на растущем поле мигала бы полоса прокрутки.
  el.setAttribute("data-fold-moving", "");
  const anim = el.animate([{ maxHeight: `${from}px` }, { maxHeight: `${to}px` }], { duration: FOLD_SLIDE_MS, easing: SLIDE_EASE });
  let over = false;
  const end = (settled: boolean) => {
    if (over) return;
    over = true;
    window.removeEventListener("resize", stop);
    window.visualViewport?.removeEventListener("resize", stop);
    el.removeAttribute("data-fold-moving");
    if (settled) done();
  };
  // Окно меняет высоту (клавиатура телефона, поворот): пределы поля считает оболочка от --vvh,
  // и движение к высоте, замеренной до этого, с ней бы спорило. Сразу встаём на место.
  function stop() {
    anim.cancel();
    end(true);
  }
  anim.onfinish = () => end(true);
  window.addEventListener("resize", stop);
  window.visualViewport?.addEventListener("resize", stop);
  return () => {
    if (over) return;
    handoff(el.getBoundingClientRect().height);
    anim.cancel();
    end(false);
  };
}

export function useFoldClip(o: FoldClipOptions): void {
  const live = useRef(o);
  useLayoutEffect(() => {
    live.current = o;
  });

  /** Последний ответ «текст не помещается» — для порога с запасом; null — ещё не мерили. */
  const cut = useRef<boolean | null>(null);
  const height = useRef(0);
  /** Где стояла прокрутка поля перед сворачиванием. */
  const savedTop = useRef(0);
  const mounted = useRef(false);
  const wasFull = useRef(false);
  const handoff = useRef<number | null>(null);

  const measure = useCallback(() => {
    const { fold, fullscreen, clip, box } = live.current;
    const el = clip.current;
    // Во весь экран поле растянуто на окно: его высота ничего не говорит о длине текста.
    if (!fold || fullscreen || !el) return;
    const b = box();
    if (!b) return;
    const h = compactHeight(b, fold.lines);
    if (h !== height.current) {
      height.current = h;
      el.style.setProperty("--vs-fold-h", `${h}px`);
    }
    const next = foldNeeded(cut.current === true, b, h);
    if (next === cut.current) return;
    cut.current = next;
    el.toggleAttribute("data-fold-cut", next);
    fold.onCut(next);
  }, []);

  const enabled = Boolean(o.fold);
  const lines = o.fold?.lines ?? 0;
  const fullscreen = o.fullscreen;
  const targetKey = o.targetKey;

  // Первый замер — до отрисовки: длинный черновик сразу встаёт с затуханием и кнопкой.
  useLayoutEffect(() => {
    measure();
  }, [measure, enabled, lines, fullscreen, targetKey]);

  useEffect(() => {
    if (!enabled || typeof ResizeObserver === "undefined") return;
    const el = live.current.target();
    if (!el) return;
    const ro = new ResizeObserver(() => measure());
    ro.observe(el);
    return () => ro.disconnect();
  }, [measure, enabled, targetKey]);

  // Поле убрали (редактор упал и уступил место textarea): её замер начнётся с чистого листа.
  // Именно layout-эффект: его очистка идёт раньше первого замера нового поля, обычная — позже,
  // и тогда «помещается» от старого поля затёрло бы ответ нового. Свой ответ тоже забываем:
  // в режиме разработки React снимает и ставит эффекты дважды, и следующий замер должен
  // сообщить результат заново.
  useLayoutEffect(
    () => () => {
      if (cut.current) live.current.fold?.onCut(false);
      cut.current = null;
    },
    [],
  );

  const compact = Boolean(o.fold?.compact) && !fullscreen;
  useLayoutEffect(() => {
    const { clip, revealCaret } = live.current;
    const el = clip.current;
    // Первый показ и переход во весь экран и обратно — без движения: это не сворачивание.
    const jump = !mounted.current || wasFull.current !== fullscreen;
    mounted.current = true;
    wasFull.current = fullscreen;
    const carried = handoff.current;
    handoff.current = null;
    if (!el || el.hasAttribute("data-fold") === compact) return;
    const from = carried ?? el.getBoundingClientRect().height;
    const focused = el.contains(document.activeElement);
    if (compact) {
      el.setAttribute("data-fold", "");
      if (revealCaret) {
        savedTop.current = el.scrollTop;
        // В свёрнутом поле — начало запроса: по первым строкам его и узнают.
        scrollToTop(el, 0);
      }
    } else {
      el.removeAttribute("data-fold");
      if (revealCaret) {
        // Без фокуса возвращаем место, где человек остановился; с фокусом — строку с курсором:
        // клик в свёрнутый текст ставит его в первые строки, и прежнее место увело бы их из вида.
        if (focused) revealCaret();
        else scrollToTop(el, savedTop.current);
      }
    }
    const settle = () => {
      // Поле доросло до полной высоты — курсор мог остаться ниже её края.
      if (!compact && focused) live.current.revealCaret?.();
    };
    // Короткий текст обрезка не задевает — двигать нечего.
    if (jump || !cut.current) {
      settle();
      return;
    }
    return slide(el, from, settle, (h) => {
      handoff.current = h;
    });
  }, [compact, fullscreen]);
}

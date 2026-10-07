/**
 * Видеостудия: связь композера с частями, которые живут вне него.
 *
 * Зона перетаскивания (DropOverlay) лежит поверх всей центральной колонки,
 * а «Мои материалы» (AssetLibrarySheet) — среди окон студии. Загрузку и
 * вставку чипа в текст умеет только композер: у него очередь загрузки и
 * ручка редактора. Поэтому композер регистрирует здесь свои обработчики, а
 * остальные зовут их, не зная, смонтирован ли композер (нет — кнопка
 * загрузки не показывается, перетаскивание не принимается).
 *
 * Первый экран зовёт те же ручки: карточки «Свои герои через @», «Первый и
 * последний кадр», «Картинка для кадра» открывают выбор файла, окно «Создать
 * картинку» и слоты кадров, которые есть только у композера.
 *
 * Модуль без React-состояния: одна студия на вкладку.
 */
import type { AssetJSON, FrameSlot, InputSlot, Uid } from "@/lib/vstudio/types";

export type ComposerUploadVia = "drop" | "picker" | "button";

export type ComposerHandlers = {
  /** Загрузить файлы в лоток (или в слот кадра); промис — uid загруженных. */
  upload: (files: File[], opts?: { slot?: InputSlot; via?: ComposerUploadVia }) => Promise<Uid[]>;
  /** Материал из библиотеки → в запрос (референс или кадр). */
  pick: (asset: AssetJSON, slot?: InputSlot) => void;
  /** Открыть выбор файлов: фото-референсы или кадр (slot). Гостю — окно входа. */
  openUpload: (slot?: InputSlot) => void;
  /** Открыть «Создать картинку» у панели запроса. Гостю — окно входа. */
  openImageGen: () => void;
  /** Показать слоты кадров: подсветить и поставить фокус. Модель без кадров — фокус в поле запроса. */
  focusFrames: () => void;
  /** Фокус в поле запроса (на телефоне панель прокручивается в поле зрения). */
  focusPrompt: () => void;
};

let handlers: ComposerHandlers | null = null;
let libraryTarget: FrameSlot | null = null;
const listeners = new Set<() => void>();

function notify() {
  for (const l of [...listeners]) {
    try {
      l();
    } catch {
      /* подписчик упал — остальные всё равно узнают */
    }
  }
}

/** Композер смонтирован: зарегистрировать обработчики. Возвращает отписку. */
export function registerComposer(h: ComposerHandlers): () => void {
  handlers = h;
  notify();
  return () => {
    if (handlers === h) {
      handlers = null;
      notify();
    }
  };
}

export function composerHandlers(): ComposerHandlers | null {
  return handlers;
}

/** Для useSyncExternalStore: смонтирован ли композер и куда выбирать материал. */
export function subscribeComposerBus(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

export function composerPresent(): boolean {
  return handlers !== null;
}

/**
 * «Из моих материалов» у пустого слота кадра: библиотека открывается с
 * подсказкой «Выберите первый кадр», и выбор уходит в этот слот.
 */
export function setLibraryTarget(slot: FrameSlot | null): void {
  if (libraryTarget === slot) return;
  libraryTarget = slot;
  notify();
}

export function getLibraryTarget(): FrameSlot | null {
  return libraryTarget;
}

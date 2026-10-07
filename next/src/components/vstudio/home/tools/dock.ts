/**
 * Первый экран → панель запроса: карточки зовут её действия, не зная, что у
 * неё внутри (§4.3).
 *
 * Панель запроса одна на студию и сама регистрирует свои ручки в composerBus.
 * Четыре ручки первого экрана описаны здесь отдельно и необязательными:
 * карточки не должны зависеть от того, успела ли панель их зарегистрировать
 * (и смонтирована ли она вообще). Если ручки нет, человек просто попадает в
 * поле запроса, где те же действия лежат кнопками.
 */
import type { InputSlot } from "@/lib/vstudio/types";
import { composerHandlers, type ComposerHandlers } from "../../composer/composerBus";
import { COMPOSER_FILLED_EVENT } from "../../feed/feedLogic";

type DockHandlers = ComposerHandlers & {
  /** Открыть выбор файла (по умолчанию — фото-референс). */
  openUpload?: (slot?: InputSlot) => void;
  /** Открыть мини-генератор картинки. */
  openImageGen?: () => void;
  /** Показать панель запроса и подсветить слоты кадров. */
  focusFrames?: () => void;
  /** Поставить курсор в поле запроса. */
  focusPrompt?: () => void;
};

export type DockAction = "openUpload" | "openImageGen" | "focusFrames" | "focusPrompt";

/** Позвать действие панели запроса. false — панели нет на экране или она его ещё не умеет. */
export function callDock(action: DockAction): boolean {
  const handlers = composerHandlers() as DockHandlers | null;
  const run = handlers?.[action];
  if (typeof run !== "function") return false;
  run();
  return true;
}

/**
 * Курсор в поле запроса — тем же событием, что у примеров и «Снять похожее»:
 * панель слушает его сама, а на телефоне ещё и выезжает на экран.
 */
export function focusComposer(): void {
  try {
    window.dispatchEvent(new CustomEvent(COMPOSER_FILLED_EVENT, { detail: { reason: "example" } }));
  } catch {
    /* старый браузер без CustomEvent — панель просто не возьмёт фокус */
  }
}

/** Действие панели, а если его нет — хотя бы курсор в поле запроса. */
export function callDockOrFocus(action: Exclude<DockAction, "focusPrompt">): void {
  if (callDock(action) || callDock("focusPrompt")) return;
  focusComposer();
}

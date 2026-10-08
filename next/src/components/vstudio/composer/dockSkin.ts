/**
 * Видеостудия, панель запроса: строки классов, общие для её частей.
 *
 * Основа — ui/skin.ts; здесь только то, чего там нет и что нужно сразу
 * нескольким файлам композера.
 */
import { VS_FOCUS } from "../ui/skin";

/** Кнопки в плашках над панелью (подсказки, конфликт кадров): главная — светлая, вторая — тихая. */
export const HINT_BTN = `inline-flex min-h-9 shrink-0 cursor-pointer items-center rounded-full px-3 text-xs font-semibold transition-colors max-md:min-h-11 ${VS_FOCUS}`;
export const HINT_BTN_PRIMARY = "bg-foreground text-background hover:opacity-90";
export const HINT_BTN_QUIET = "border border-vs-ink/12 bg-vs-ink/[0.05] text-foreground/85 hover:border-vs-ink/25 hover:text-foreground";

/**
 * Поле ввода в окнах панели («Создать картинку»). На телефоне шрифт 16 px:
 * мельче — и iOS приближает страницу при фокусе.
 */
export const DOCK_FIELD =
  "w-full rounded-xl border border-vs-ink/10 bg-vs-ink/[0.04] text-base text-foreground outline-none transition-colors placeholder:text-muted-2 hover:border-vs-ink/18 focus:border-vs-accent/60 md:text-sm";

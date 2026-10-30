/**
 * Строки классов мультстудии поверх skin.ts видеостудии.
 *
 * Несколько констант скопированы из файлов видеостудии дословно (DOT из
 * ProjectRail, MENU_POP и TALL_HIT из StudioTopBar): импорт даже одной из них
 * притянул бы в мультстудию весь стор видеостудии.
 */
import { VS_BTN_GHOST, VS_BTN_GOLD, VS_FOCUS, VS_PILL, VS_PILL_ON, vx } from "@/components/vstudio/ui/skin";

/** Отступ между секциями мультстудии: рабочий экран, плотнее первого экрана видеостудии (VS_SECTION_GAP). */
export const CS_GAP = "mt-8 sm:mt-10";
/**
 * Куда встаёт секция по «прокрутить к героям / к ленте»: верх — ниже затухания
 * под верхней строкой (у первого экрана оболочки оно h-6), низ («+ В ленту»
 * докручивает ленту до её низа) — выше затухания над доком (vs-dock, 56 px).
 */
export const CS_ANCHOR = "scroll-mt-6 scroll-mb-14";
/** Шапка секции: заголовок с пояснением слева, действие справа; на узком — под заголовком. */
export const CS_HEAD = "flex flex-wrap items-end justify-between gap-x-6 gap-y-3";
/**
 * Горизонтальная лента во всю ширину колонки (как ContinueStrip). + EDGE_FADE[fade].
 * relative: скрытые подписи в карточках (sr-only — position:absolute) иначе привязываются к колонке
 * студии мимо ленты — лента их не режет и не прокручивает, колонка становится шире экрана на каждую
 * сцену после второй, и свайп по ленте уводит вбок всю студию. overscroll-x-contain: дойдя до края
 * ленты, свайп не передаётся колонке.
 */
export const CS_STRIP = "vs-noscroll relative -mx-4 overflow-x-auto overscroll-x-contain px-4 py-1 sm:-mx-6 sm:px-6";
/** Чип 40 px с зоной нажатия 44 px на телефоне (как TemplateChips). */
export const CS_CHIP = vx(VS_PILL, "relative active:scale-[0.97] before:absolute before:inset-x-0 before:-inset-y-0.5 before:content-[''] md:before:hidden");
/** Кнопка в карточке: тихая, во всю ширину, 44 px на телефоне. */
export const CS_CARD_BTN = vx(VS_BTN_GHOST, "w-full !min-h-11 !px-3 !text-[13px] md:!min-h-9");
/** Главное действие карточки («Снять сцену», «Озвучить голосом героя»): золотой контур, а не заливка — золотая кнопка на экране одна, в доке. */
export const CS_CARD_GOLD = vx(VS_BTN_GHOST, VS_PILL_ON, "w-full !font-semibold hover:!bg-accent/[0.16]");
/** Золотая кнопка дока — как RUN_GOLD у RunButton. */
export const CS_RUN_GOLD = vx(VS_BTN_GOLD, "whitespace-nowrap md:!min-h-11");
/** Кнопка дока, когда действие закрыто, — как RUN_OFF у RunButton. */
export const CS_RUN_OFF = `inline-flex min-h-11 items-center justify-center gap-2 whitespace-nowrap rounded-full border border-vs-ink/10 bg-vs-ink/[0.06] px-5 text-sm font-semibold tracking-[0.01em] text-muted transition-colors ${VS_FOCUS}`;
/** Заглушка-строка (как SKELETON_FILL видеостудии). */
export const CS_SKELETON = "bg-vs-ink/[0.08] dark:bg-vs-ink/[0.06]";
/** Золотая точка «вы здесь» / «идёт съёмка» (как DOT в ProjectRail). */
export const CS_DOT = "size-1.5 shrink-0 rounded-full bg-vs-accent dark:shadow-[0_0_8px_rgba(245,197,24,0.8)]";
/** Всплывающее меню вырастает из угла (как MENU_POP в StudioTopBar). */
export const CS_MENU_POP = "origin-top-right scale-100 opacity-100 transition-[opacity,scale] duration-150 starting:scale-95 starting:opacity-0 motion-reduce:transition-none";
/** Зона нажатия 44 px у контрола ниже ростом (как TALL_HIT в StudioTopBar). */
export const CS_TALL_HIT = "relative before:absolute before:inset-x-0 before:-inset-y-1";
/** Подсказка-выноска («сначала выберите героя»). */
export const CS_NOTE_GOLD = "rounded-2xl border border-vs-accent/35 bg-accent/[0.08] px-4 py-3 text-sm text-foreground";
/** Отказ или сбой — красная выноска. */
export const CS_NOTE_FAIL = "rounded-2xl border border-status-fail/40 bg-status-fail/10 px-4 py-3 text-sm text-status-fail";
/** Пустое состояние секции. */
export const CS_EMPTY = "flex flex-col items-center gap-2 rounded-2xl border border-dashed border-vs-ink/15 px-6 py-8 text-center text-sm text-muted";

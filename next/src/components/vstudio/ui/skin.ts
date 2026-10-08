/**
 * Видеостудия: общий вид кнопок, чипов, карточек и подписей.
 *
 * Все экраны студии берут строки классов отсюда — тогда кнопка «Создать» на
 * первом экране, в ленте и в шторке выглядит одинаково, а поменять вид можно
 * в одном месте. Цвета и фактуры (vs-glass, vs-card, vs-gold …) описаны в
 * app/globals.css, блок «Видеостудия».
 *
 * Правила:
 *  — одно золотое действие на экран (VS_BTN_GOLD), остальное — VS_BTN_GHOST;
 *  — студия живёт в двух темах: линии и заливки хрома — утилитами vs-ink
 *    (border-vs-ink/10, bg-vs-ink/[0.05]), золотой текст и тонкие золотые
 *    линии — vs-accent (text-vs-accent, border-vs-accent/45), текст — токенами
 *    text-foreground / text-muted / text-muted-2. Чистые white/black в хроме
 *    не пишем: в светлой теме они пропадут или станут грязью;
 *  — поверх видео только фиксированные чёрно-белые плашки (VS_ON_MEDIA): кадр
 *    тёмный в любой теме;
 *  — зона нажатия не меньше 44 px на телефоне (min-h-11), 40 px с 768 px.
 */

/** Склейка классов: ложные значения отбрасываются. */
export function vx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

/**
 * Кольцо фокуса с клавиатуры. У vs-card и vs-gold своя тень (обычный CSS вне
 * слоёв Tailwind), и кольцо-тень под ней не видно — им фокус рисует контур в
 * app/globals.css; отдельно дописывать его в компонентах не нужно.
 */
export const VS_FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-vs-accent/80";

/* ---------- кнопки ---------- */

/**
 * Выключенная золотая кнопка в светлой теме плотнее: на белом золото в 45 %
 * выцветает вместе с подписью, и её уже не прочесть.
 */
export const VS_BTN_GOLD = `vs-gold inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-full px-5 text-sm font-semibold tracking-[0.01em] transition-[filter,box-shadow,transform] duration-200 active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-60 md:min-h-10 dark:disabled:opacity-45 ${VS_FOCUS}`;

export const VS_BTN_GHOST = `inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-full border border-vs-ink/12 bg-vs-ink/[0.05] px-4 text-sm font-medium text-foreground/85 transition-colors hover:border-vs-ink/25 hover:bg-vs-ink/[0.09] hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50 md:min-h-10 ${VS_FOCUS}`;

/** Тихая текстовая кнопка: «Показать ещё», «Все модели». */
export const VS_BTN_LINK = `inline-flex min-h-11 cursor-pointer items-center gap-1.5 rounded-full px-2 text-sm font-medium text-muted transition-colors hover:text-foreground md:min-h-9 ${VS_FOCUS}`;

export const VS_ICON_BTN = `grid size-11 shrink-0 cursor-pointer place-items-center rounded-full border border-vs-ink/10 bg-vs-ink/[0.05] text-muted transition-colors hover:border-vs-ink/22 hover:bg-vs-ink/[0.1] hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50 md:size-10 ${VS_FOCUS}`;

/* ---------- чипы и переключатели ---------- */

/** Чип параметра или сценария: «16:9», «5 с», «Реклама товара». */
export const VS_PILL = `inline-flex h-10 shrink-0 cursor-pointer items-center gap-1.5 rounded-full border border-vs-ink/10 bg-vs-ink/[0.04] px-3.5 text-[13px] font-medium text-foreground/75 transition-colors hover:border-vs-ink/22 hover:bg-vs-ink/[0.07] hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50 md:h-9 ${VS_FOCUS}`;
/** Добавляется к VS_PILL у выбранного значения. */
export const VS_PILL_ON = "!border-vs-accent/45 !bg-accent/[0.1] !text-vs-accent shadow-[inset_0_1px_10px_rgba(245,197,24,0.12)]";

/**
 * Переключатель из двух половинок («Видео / Картинка»): дорожка и плашка
 * выбранной половины. В тёмной теме плашка светлее дорожки; в светлой —
 * привычный вид такого переключателя: белая плашка на утопленной дорожке.
 * Подпись выбранной половины — text-vs-accent в обеих темах.
 */
export const VS_SEG_TRACK = "bg-surface-3 dark:bg-vs-ink/[0.05]";
export const VS_SEG_THUMB = "bg-surface shadow-sm dark:bg-vs-ink/[0.1] dark:shadow-none";

/** Маленькая подпись-метка: «Новинка», «от 160 кр». */
export const VS_TAG = "inline-flex items-center gap-1 rounded-full border border-vs-ink/10 bg-vs-ink/[0.05] px-2 py-0.5 text-[11px] font-medium leading-4 text-foreground/70";
export const VS_TAG_GOLD = "inline-flex items-center gap-1 rounded-full border border-vs-accent/35 bg-accent/[0.1] px-2 py-0.5 text-[11px] font-semibold leading-4 text-vs-accent";

/**
 * Плашка поверх видео и постеров. Без размытия фона: плашка стоит на каждом
 * кадре ленты и карусели, и каждая размытая — отдельный проход по кадру
 * играющего под ней ролика на каждом шаге прокрутки. Плотная подложка читается
 * так же.
 */
export const VS_ON_MEDIA = "rounded-full bg-black/65 px-2 py-0.5 text-[10px] font-medium leading-4 text-white";
/**
 * Ставится рядом с vs-sheen там, где блик проходит по кадру или постеру. В
 * светлой теме блик плотный — иначе на белой карточке его не видно, — и по
 * тёмному кадру он шёл бы молочной полосой. На кадре блик в обеих темах тот же
 * тихий, что в тёмной: видео тёмное в любой теме.
 */
export const VS_SHEEN_ON_MEDIA = "[--vs-sheen:rgba(255,255,255,0.13)]";

/* ---------- текст ---------- */

/** Надзаголовок секции или первого экрана. */
export const VS_EYEBROW = "inline-flex items-center gap-2 rounded-full border border-vs-accent/30 bg-accent/[0.08] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-vs-accent";
export const VS_H2 = "vs-display text-[22px] text-foreground sm:text-[26px]";
export const VS_SUB = "text-sm leading-snug text-muted";
export const VS_LABEL = "text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-2";

/* ---------- поверхности ---------- */

export const VS_CARD = "vs-card rounded-2xl";
/** Карточка, на которую можно нажать. */
export const VS_CARD_BTN = `vs-card vs-card-hover rounded-2xl cursor-pointer text-left ${VS_FOCUS}`;
/**
 * Панель запроса. Непрозрачная (vs-solid), без размытия: она стоит под лентой,
 * а не поверх неё, размывать под ней нечего — а backdrop-filter на всегда
 * видимом блоке заметно нагружает слабый телефон.
 */
export const VS_PANEL = "vs-solid rounded-[24px]";
/** Всплывающее меню и небольшое окно. */
export const VS_MENU = "vs-glass rounded-2xl p-1.5";
export const VS_MENU_ITEM = `flex min-h-11 w-full cursor-pointer items-center gap-2.5 rounded-xl px-3 text-left text-sm text-foreground/85 transition-colors hover:bg-vs-ink/[0.08] hover:text-foreground md:min-h-9 ${VS_FOCUS}`;
/** Рамка кадра: видео и картинки. */
export const VS_MEDIA = "relative overflow-hidden rounded-xl bg-black";
export const VS_INPUT = `min-h-11 w-full rounded-xl border border-vs-ink/10 bg-vs-ink/[0.04] px-3 text-sm text-foreground placeholder:text-muted-2 transition-colors hover:border-vs-ink/18 focus:border-vs-accent/60 focus:outline-none md:min-h-10`;

/* ---------- раскладка первого экрана ---------- */

/** Ширина и поля секций первого экрана. */
export const VS_SECTION = "mx-auto w-full max-w-[1240px] px-4 sm:px-6";
/** Отступ между секциями первого экрана. */
export const VS_SECTION_GAP = "mt-12 sm:mt-16";

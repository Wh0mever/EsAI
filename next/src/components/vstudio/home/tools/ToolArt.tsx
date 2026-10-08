"use client";

import { memo } from "react";
import { FiArrowRight, FiArrowUpRight } from "react-icons/fi";
import { IoSparkles } from "react-icons/io5";
import { chipClassName } from "../../editor/chipStyle";
import LazyClip from "../../ui/LazyClip";
import { vx } from "../../ui/skin";

/**
 * Картинки карточек «Инструменты режиссёра» — только разметка и CSS, без файлов
 * (§2.2 ToolCards). Каждая — маленькая сцена из тех же деталей, что и сам
 * интерфейс: плашки фото, настоящий чип «@Image 1», золотая искра.
 *
 * Движение одно на всю сцену. Карточка под курсором или в фокусе с клавиатуры
 * ставит переменную --vs-on в 1 (класс в ToolCards), а детали считают позу по
 * формуле «покой + сдвиг × var(--vs-on, 0)» и плавно переходят в неё — один
 * раз, без повторов. При «меньше движения» карточка переменную не ставит, и
 * сцена остаётся неподвижной. Вне экрана ничего не движется: без курсора
 * переходу неоткуда взяться.
 *
 * Все размеры — в долях сцены, шрифт — от её ширины (cqw): карточка бывает и
 * 150, и 350 px шириной, а рисунок должен читаться одинаково.
 *
 * Две темы. Рисунок — «чернилами» темы (vs-ink) с теми же долями, что были у
 * белого: в тёмной теме светлые фигуры на тёмных плашках, в светлой — серые на
 * белых. Плашка-фото в светлой теме белая, как отпечаток на столе, и тень под
 * ней тёплая и лёгкая. Солнце и заливки остаются ярким золотом; тонкие золотые
 * линии, точки и значки — vs-accent: яркое золото на светлом не читается.
 */

/** Сцена 16:10: подложка темы и зерно плёнки. Нажатия проходят сквозь неё к карточке. */
const STAGE =
  "vs-grain @container pointer-events-none relative block aspect-[16/10] w-full shrink-0 overflow-hidden rounded-t-[15px] border-b border-vs-ink/[0.06] bg-surface-2";
/** Тёплый свет сверху — тот же луч проектора, что за первым экраном. */
const GLOW = "absolute inset-0 bg-radial-[at_50%_0%] from-accent/[0.14] to-transparent to-70%";
/** Переход из спокойной позы в «рабочую» и обратно. */
const MOVE = "transition-[translate,rotate,scale,opacity] duration-500 ease-[var(--vs-ease)]";
/** Подложка плашки и тень под ней: белый отпечаток на светлой сцене, приподнятая тёмная плашка — на тёмной. */
const PRINT = "bg-surface shadow-lg shadow-vs-ink/15 dark:bg-surface-3 dark:shadow-black/50";
/** Плашка-фото. */
const PHOTO = `absolute overflow-hidden rounded-md border ${PRINT}`;
/** Блик сверху — только на тёмной плашке: на белой свету ложиться не на что. */
const PHOTO_LIGHT = "absolute inset-0 dark:bg-linear-to-b dark:from-white/[0.1] dark:to-transparent";

/* ---------- «Свои герои через @» ---------- */

/** Три фото — товар, человек, место — и строка запроса, где одно из них отмечено чипом. */
export const RefsArt = memo(function RefsArt() {
  return (
    <span aria-hidden className={STAGE}>
      <span className={GLOW} />

      <span
        className={vx(
          PHOTO,
          MOVE,
          "left-[15%] top-[13%] aspect-[3/4] w-[23%] translate-x-[calc(-12%*var(--vs-on,0))] rotate-[calc(-8deg_-_6deg*var(--vs-on,0))] border-vs-ink/15",
        )}
      >
        <span className={PHOTO_LIGHT} />
        <span className="absolute left-1/2 top-[18%] h-[10%] w-[18%] -translate-x-1/2 rounded-t-[2px] bg-vs-ink/30" />
        <span className="absolute left-1/2 top-[28%] h-[56%] w-[44%] -translate-x-1/2 rounded-[4px] bg-vs-ink/[0.18]" />
        <span className="absolute left-1/2 top-[46%] h-[18%] w-[44%] -translate-x-1/2 bg-accent/40" />
      </span>

      <span
        className={vx(
          PHOTO,
          MOVE,
          "right-[15%] top-[13%] aspect-[3/4] w-[23%] translate-x-[calc(12%*var(--vs-on,0))] rotate-[calc(8deg_+_6deg*var(--vs-on,0))] border-vs-ink/15",
        )}
      >
        <span className={PHOTO_LIGHT} />
        <span className="absolute right-[16%] top-[14%] aspect-square w-[24%] rounded-full bg-accent/70" />
        <span className="absolute -left-[10%] top-[62%] aspect-square w-[80%] rotate-45 rounded-[2px] bg-vs-ink/[0.14]" />
        <span className="absolute left-[33%] top-[76%] aspect-square w-[90%] rotate-45 rounded-[2px] bg-vs-ink/[0.22]" />
      </span>

      {/* Человек — главный кадр: лежит поверх соседей, а под курсором выравнивается и выходит вперёд. */}
      <span
        className={vx(
          PHOTO,
          MOVE,
          "inset-x-0 top-[8%] mx-auto aspect-[3/4] w-[27%] translate-y-[calc(-6%*var(--vs-on,0))] scale-[calc(1_+_0.05*var(--vs-on,0))] rotate-[calc(-3deg_+_3deg*var(--vs-on,0))] border-vs-ink/25",
        )}
      >
        <span className={PHOTO_LIGHT} />
        <span className="absolute left-1/2 top-[20%] aspect-square w-[36%] -translate-x-1/2 rounded-full bg-vs-ink/30" />
        <span className="absolute left-1/2 top-[54%] aspect-square w-[84%] -translate-x-1/2 rounded-full bg-vs-ink/[0.18]" />
      </span>

      {/* Строка запроса: чип — тот же, что в настоящем поле (editor/chipStyle). */}
      <span className="absolute inset-x-[8%] bottom-[8%] flex items-center justify-center gap-[3%] text-[clamp(11px,7cqw,14px)]">
        <span className="h-[3px] w-[16%] rounded-full bg-vs-ink/15" />
        <span className={vx(MOVE, "inline-flex scale-[calc(1_+_0.1*var(--vs-on,0))] delay-150")}>
          <span className={chipClassName("ok")}>@Image 1</span>
        </span>
        <span className="h-[3px] w-[24%] rounded-full bg-vs-ink/15" />
      </span>
    </span>
  );
});

/* ---------- «Первый и последний кадр» ---------- */

const FRAME = `absolute top-[20%] aspect-video w-[32%] overflow-hidden rounded-md border border-vs-ink/20 ${PRINT}`;
/** Земля непрозрачная (подложка кадра + тон поверх): солнце за ней должно именно прятаться. */
const GROUND =
  "absolute inset-x-0 bottom-0 h-[30%] bg-surface before:absolute before:inset-0 before:bg-vs-ink/[0.12] before:content-[''] dark:bg-surface-3";
const STEM = "absolute top-[49%] h-[25%] w-px bg-vs-ink/15";
const KEY_DOT = "absolute top-1/2 size-[7px] -translate-y-1/2 rounded-full";

/** Два кадра одной сцены — солнце встаёт и уже высоко — и шкала ролика между ними. */
export const FramesArt = memo(function FramesArt() {
  return (
    <span aria-hidden className={STAGE}>
      <span className={GLOW} />

      <span className={vx(FRAME, "left-[9%]")}>
        <span className={PHOTO_LIGHT} />
        <span className="absolute bottom-[14%] left-[16%] aspect-square w-[22%] rounded-full bg-accent/60" />
        <span className={GROUND} />
      </span>

      <span className={vx(FRAME, "right-[9%]")}>
        <span className={PHOTO_LIGHT} />
        <span className="absolute right-[16%] top-[12%] aspect-square w-[22%] rounded-full bg-accent" />
        <span className={GROUND} />
        {/* Ролик «дошёл» до последнего кадра — он подсвечивается. */}
        <span className="absolute inset-0 rounded-[5px] opacity-[var(--vs-on,0)] ring-1 ring-vs-accent transition-opacity delay-500 duration-300 ring-inset" />
      </span>

      <span
        className={vx(
          MOVE,
          "absolute left-1/2 top-[34%] grid -translate-y-1/2 translate-x-[calc(-50%_+_30%*var(--vs-on,0))] place-items-center text-[clamp(14px,8cqw,22px)] text-vs-accent",
        )}
      >
        <FiArrowRight />
      </span>

      <span className={vx(STEM, "left-[25%]")} />
      <span className={vx(STEM, "right-[25%]")} />
      {/* Шкала — тонкая линия с точками: золото для линий (vs-accent), на светлой сцене яркая полоска в 2 px пропала бы. */}
      <span className="absolute left-[25%] right-[25%] top-[74%] h-0.5 rounded-full bg-vs-ink/15">
        <span className="absolute inset-0 origin-left scale-x-[calc(0.08_+_0.92*var(--vs-on,0))] rounded-full bg-vs-accent transition-[scale] duration-[900ms] ease-[var(--vs-ease)]" />
        <span className={vx(KEY_DOT, "left-0 -translate-x-1/2 bg-vs-accent")} />
        <span className={vx(KEY_DOT, "right-0 translate-x-1/2 border border-vs-accent bg-surface-2")}>
          <span className="absolute inset-0 rounded-full bg-vs-accent opacity-[var(--vs-on,0)] transition-opacity delay-700 duration-300" />
        </span>
      </span>
    </span>
  );
});

/* ---------- «Картинка для кадра» ---------- */

const PATH_DOT =
  "size-[3px] rounded-full bg-vs-accent opacity-[calc(0.3_+_0.7*var(--vs-on,0))] transition-opacity duration-300";

/** Искра (та же, что на кнопке «Создать картинку») → картинка, которая «проявляется». */
export const ImageArt = memo(function ImageArt() {
  return (
    <span aria-hidden className={STAGE}>
      <span className={GLOW} />

      <span
        className={vx(
          MOVE,
          "absolute left-[11%] top-1/2 grid aspect-square w-[21%] -translate-y-1/2 rotate-[calc(-18deg*var(--vs-on,0))] scale-[calc(1_+_0.08*var(--vs-on,0))] place-items-center rounded-full border border-vs-accent/45 bg-accent/[0.1] text-[clamp(13px,9cqw,24px)] text-vs-accent",
        )}
      >
        <IoSparkles />
      </span>

      <span className="absolute left-[36%] top-1/2 flex w-[13%] -translate-y-1/2 items-center justify-between">
        <span className={PATH_DOT} />
        <span className={vx(PATH_DOT, "delay-100")} />
        <span className={vx(PATH_DOT, "delay-200")} />
      </span>

      <span
        className={vx(
          PHOTO,
          MOVE,
          "right-[10%] top-1/2 aspect-[4/3] w-[38%] -translate-y-1/2 scale-[calc(0.96_+_0.07*var(--vs-on,0))] border-vs-ink/20 delay-200",
        )}
      >
        <span className="absolute inset-0 opacity-[calc(0.35_+_0.65*var(--vs-on,0))] transition-opacity delay-200 duration-700">
          <span className="absolute inset-0 bg-linear-to-b from-accent/25 to-transparent" />
          <span className="absolute right-[14%] top-[14%] aspect-square w-[16%] rounded-full bg-accent" />
          <span className="absolute left-0 top-[59%] aspect-square w-[60%] rotate-45 rounded-[2px] bg-vs-ink/[0.16]" />
          <span className="absolute left-[37%] top-[75%] aspect-square w-[70%] rotate-45 rounded-[2px] bg-vs-ink/[0.26]" />
        </span>
      </span>

      <span
        className={vx(
          MOVE,
          "absolute right-[44%] top-[19%] scale-[calc(0.4_+_0.6*var(--vs-on,0))] text-[clamp(8px,4.5cqw,12px)] text-vs-accent opacity-[var(--vs-on,0)] delay-300",
        )}
      >
        <IoSparkles />
      </span>
    </span>
  );
});

/* ---------- «Мультстудия» ---------- */

/**
 * Настоящий кадр мультстудии из витрины; пока его нет — плёнка-заглушка
 * (LazyClip без ролика показывает только картинку и сам переживает её ошибку).
 * Стрелка в углу — карточка уводит в другой раздел; она лежит на кадре и
 * потому чёрно-белая в обеих темах.
 *
 * Затемнение низа — только в тёмной теме: там оно сводит кадр с тёмной
 * карточкой под ним. Под белой карточкой чёрная полоса стала бы самым тяжёлым
 * местом рисунка — на светлой сцене кадр просто заканчивается кромкой шапки.
 */
export const CartoonArt = memo(function CartoonArt({ poster }: { poster: string | null }) {
  return (
    <span aria-hidden className={STAGE}>
      <span className="absolute inset-0 scale-[calc(1_+_0.06*var(--vs-on,0))] transition-[scale] duration-[900ms] ease-[var(--vs-ease)]">
        <LazyClip src={null} poster={poster} mode="visible" alt="" className="absolute inset-0" rounded="rounded-none" />
      </span>
      <span className="vs-shade absolute inset-x-0 bottom-0 hidden h-1/2 dark:block" />
      <span className="absolute right-2 top-2 grid size-7 place-items-center rounded-full bg-black/55 text-white backdrop-blur-sm">
        <FiArrowUpRight className="size-3.5" />
      </span>
    </span>
  );
});

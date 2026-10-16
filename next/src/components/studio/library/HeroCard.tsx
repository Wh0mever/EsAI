"use client";

import type { ReactNode, Ref } from "react";
import { useTranslation } from "react-i18next";
import { FiCheck, FiFilm, FiX } from "react-icons/fi";
import { HOME_CARD, HOME_CARD_ON } from "@/components/vstudio/home/tools/cardSkin";
import { useOnScreen } from "@/components/vstudio/home/tools/useOnScreen";
import { VS_CARD, VS_FOCUS, vx } from "@/components/vstudio/ui/skin";
import type { StudioCharacter } from "../CharacterPicker";
import { CS_SKELETON, CS_STRIP } from "../ui/cartoonSkin";

/**
 * Ячейка ленты героев. Ширина — у ячейки, а не у кнопки: в HOME_CARD уже
 * стоят w-full h-full. flex — чтобы карточка тянулась на высоту ряда, когда
 * подпись соседней карточки-действия занимает две строки.
 */
export const HERO_ITEM = "relative flex w-[92px] shrink-0 snap-start min-[390px]:w-[96px] md:w-[112px] xl:w-[120px]";

const CARD_BODY = "gap-1.5 p-1.5";

/** Кнопка «удалить» лежит на кадре: 28 px на вид, 44 px под пальцем. Видна всегда — в Telegram наводить нечем. */
const DELETE_BTN = vx(
  "absolute right-1.5 top-1.5 grid size-7 cursor-pointer place-items-center rounded-full bg-black/60 text-white transition-colors hover:bg-status-fail before:absolute before:-inset-2 before:content-['']",
  VS_FOCUS,
);

export type HeroCardProps = {
  character: StudioCharacter;
  selected: boolean;
  /** Герой уже стоит в сценах открытого мультфильма. */
  inMovie: boolean;
  onPick: (c: StudioCharacter) => void;
  /** Только у своих героев: библиотечные общие, их не удалить. */
  onDelete?: () => void;
};

/**
 * Карточка героя: портрет и имя. Отметки поверх портрета чёрно-белые — они
 * лежат на картинке в любой теме. «Удалить» — соседняя кнопка, а не вложенная:
 * кнопка внутри кнопки — невалидная разметка.
 */
export default function HeroCard({ character, selected, inMovie, onPick, onDelete }: HeroCardProps) {
  const { t } = useTranslation("common");
  const inMovieLabel = t("studio_ui.heroes_in_movie", { defaultValue: "В мультфильме" });
  const deleteLabel = t("studio_ui.hero_delete");
  return (
    <>
      <button
        type="button"
        data-hero-card=""
        data-hero-pick=""
        onClick={() => onPick(character)}
        aria-pressed={selected}
        title={character.name}
        className={vx(selected ? HOME_CARD_ON : HOME_CARD, CARD_BODY)}
      >
        <span className="relative block aspect-square w-full overflow-hidden rounded-xl bg-surface-2">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={character.image}
            alt=""
            loading="lazy"
            decoding="async"
            draggable={false}
            className="h-full w-full object-cover"
          />
          {inMovie && (
            <span
              aria-hidden
              title={inMovieLabel}
              className="pointer-events-none absolute left-1 top-1 grid size-6 place-items-center rounded-full bg-black/65 text-[12px] text-white"
            >
              <FiFilm />
            </span>
          )}
          {selected && (
            <span
              aria-hidden
              className="pointer-events-none absolute bottom-1 right-1 grid size-6 place-items-center rounded-full bg-accent text-sm text-on-accent"
            >
              <FiCheck />
            </span>
          )}
        </span>
        <span
          className={vx(
            "block truncate px-0.5 text-[12px] font-medium leading-4",
            selected ? "text-vs-accent" : "text-foreground/85",
          )}
        >
          {character.name}
        </span>
        {inMovie && <span className="sr-only">{inMovieLabel}</span>}
      </button>
      {onDelete && (
        <button type="button" onClick={onDelete} title={deleteLabel} aria-label={deleteLabel} className={DELETE_BTN}>
          <FiX aria-hidden className="text-sm" />
        </button>
      )}
    </>
  );
}

export type HeroActionCardProps = {
  ref?: Ref<HTMLButtonElement>;
  icon: ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  busy?: boolean;
  /** Карточка раскрывает форму: открыта ли она и как её найти. */
  expanded?: boolean;
  controls?: string;
};

/**
 * Карточка-действие в начале ленты («Загрузить своего», «Нарисовать по
 * описанию»): того же размера, что герои, с пунктирной кромкой — это не герой,
 * а способ его завести. Значок занимает всё место над подписью, поэтому
 * карточка ровно в высоту соседних, сколько бы строк ни заняла подпись.
 */
export function HeroActionCard({ ref, icon, label, onClick, disabled, busy, expanded, controls }: HeroActionCardProps) {
  return (
    <button
      ref={ref}
      type="button"
      data-hero-card=""
      onClick={onClick}
      disabled={disabled}
      aria-busy={busy || undefined}
      aria-expanded={expanded}
      aria-controls={controls}
      title={label}
      className={vx(
        expanded ? HOME_CARD_ON : HOME_CARD,
        CARD_BODY,
        "!border-dashed disabled:cursor-not-allowed disabled:opacity-60",
      )}
    >
      <span
        aria-hidden
        className="grid min-h-12 w-full flex-1 place-items-center rounded-xl bg-vs-ink/[0.04] text-2xl text-vs-accent"
      >
        {icon}
      </span>
      <span className="line-clamp-2 px-0.5 text-[12px] font-medium leading-tight text-foreground/85">{label}</span>
    </button>
  );
}

/**
 * Лента-заглушка, пока грузится витрина: карточки той же геометрии, что
 * настоящие. «Плёнка» переливается, только пока лента на экране.
 */
export function HeroStripSkeleton({ count }: { count: number }) {
  const [watch, seen] = useOnScreen<HTMLDivElement>();
  return (
    <div ref={watch} aria-hidden className={vx(CS_STRIP, "mt-4")}>
      <ul className="flex w-max gap-2.5 sm:gap-3">
        {Array.from({ length: count }, (_, i) => (
          <li key={i} className={HERO_ITEM}>
            <span className={vx(VS_CARD, "flex w-full flex-col", CARD_BODY)}>
              <span className={vx("block aspect-square w-full rounded-xl", seen ? "vs-film" : CS_SKELETON)} />
              <span className={vx("block h-4 w-3/4 rounded-full", CS_SKELETON)} />
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

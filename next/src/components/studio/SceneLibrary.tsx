"use client";

import { useEffect, useId, useRef } from "react";
import { useTranslation } from "react-i18next";
import { FiChevronDown, FiChevronRight, FiEdit3, FiLoader, FiPlus, FiUser } from "react-icons/fi";
import { EDGE_FADE, useEdgeFade } from "@/components/vstudio/home/strip/useEdgeFade";
import {
  VS_BTN_GHOST,
  VS_BTN_LINK,
  VS_CARD,
  VS_H2,
  VS_INPUT,
  VS_PILL_ON,
  VS_SECTION,
  VS_SUB,
  vx,
} from "@/components/vstudio/ui/skin";
import type { StudioCharacter } from "./CharacterPicker";
import type { Audience, CardPrice, Category, Preset } from "./cartoonTypes";
import SceneCard, { SceneGridSkeleton } from "./library/SceneCard";
import { CS_CHIP, CS_EMPTY, CS_GAP, CS_HEAD, CS_SKELETON } from "./ui/cartoonSkin";

export type SceneLibraryProps = {
  loading: boolean;
  authed: boolean;
  /** Карточки нынешней «горсти», уже отфильтрованные. */
  presets: Preset[];
  /** Сколько карточек ещё за кнопкой «Показать ещё». */
  restCount: number;
  /** Разделы, в которых есть сцены для выбранной аудитории. */
  categories: Category[];
  hasPopular: boolean;
  hasPicks: boolean;
  /** "" — все, "__popular", "__pick" или slug раздела. */
  activeCat: string;
  audience: Audience;
  selected: StudioCharacter | null;
  /** Герои, уже поставленные в сцены открытой ленты. */
  cast: StudioCharacter[];
  /** Кадры выбранного героя в сценах (по id сцены библиотеки). */
  frames: Record<number, string>;
  /** Ролики пар «выбранный герой + сцена» (по id сцены библиотеки). */
  heroVideos: Record<number, string>;
  /** Какая сцена добавляется; -1 — своя сцена. */
  adding: number | null;
  tryingOn: number | null;
  customText: string;
  cardPrice: (p: Preset) => CardPrice;
  onCategory: (slug: string) => void;
  onMore: () => void;
  onAdd: (p: Preset) => void;
  onTryOn: (p: Preset) => void;
  onPickHero: (c: StudioCharacter) => void;
  /** Прокрутить к героям. */
  onHeroes: () => void;
  onCustomText: (text: string) => void;
  onAddCustom: () => void;
};

/** Сколько заглушек показываем, пока грузится витрина: одна «горсть» (PAGE_SIZE). */
const SKELETON_CARDS = 6;
const SKELETON_CHIPS = 6;
/** Сетка витрины: две колонки на телефоне, три с 768 px, четыре с 1280 px. */
const GRID = "mt-4 grid grid-cols-2 gap-2.5 sm:gap-3 md:grid-cols-3 xl:grid-cols-4";

/**
 * Сцены: своя сцена по описанию, разделы и витрина. Ролики карточек заводит
 * LazyClip (бюджет на вкладку, постер сначала, «меньше движения» — без
 * автозапуска); героев мультфильма теперь показывает лента героев выше.
 */
export default function SceneLibrary({
  loading,
  presets,
  restCount,
  categories,
  hasPopular,
  hasPicks,
  activeCat,
  audience,
  selected,
  frames,
  heroVideos,
  adding,
  tryingOn,
  customText,
  cardPrice,
  onCategory,
  onMore,
  onAdd,
  onTryOn,
  onHeroes,
  onCustomText,
  onAddCustom,
}: SceneLibraryProps) {
  const { t } = useTranslation("common");
  const headingId = useId();
  const customTitleId = useId();
  const customNoteId = useId();
  const { attach, fade } = useEdgeFade<HTMLDivElement>();
  const gridRef = useRef<HTMLUListElement | null>(null);
  // С какой карточки начинается порция, открытая «Показать ещё»: туда уйдёт фокус.
  const focusFrom = useRef<number | null>(null);

  useEffect(() => {
    const from = focusFrom.current;
    if (from === null || presets.length <= from) return;
    focusFrom.current = null;
    // Кнопка «Показать ещё» могла исчезнуть вместе с последней порцией, и фокус
    // упал бы на страницу. Страницу не двигаем — новые карточки там, где была кнопка.
    gridRef.current?.children[from]?.querySelector<HTMLElement>("button")?.focus({ preventScroll: true });
  }, [presets.length]);

  const more = () => {
    focusFrom.current = presets.length;
    onMore();
  };

  const heroChip = selected
    ? t("studio_ui.lib_hero_chip", { defaultValue: "Герой: {{name}} — сменить", name: selected.name })
    : "";

  // Разделы: сцен три десятка, и одной простынёй они не читаются — человек
  // ищет не «сцену вообще», а начало, погоню или финал.
  const chips = [
    { slug: "", title: t("studio_ui.cat_all"), emoji: "🎞" },
    ...(hasPopular ? [{ slug: "__popular", title: t("studio_ui.cat_popular"), emoji: "🔥" }] : []),
    ...(hasPicks ? [{ slug: "__pick", title: t("studio_ui.cat_pick"), emoji: "⭐" }] : []),
    ...categories,
  ];

  // Витрина пуста после загрузки: при детской или взрослой аудитории — нет сцен
  // для неё; при «всех» — нет вовсе (сбой загрузки уже сказан плашкой над лентой).
  const empty = !loading && presets.length === 0 && restCount === 0;

  return (
    <section aria-labelledby={headingId} aria-busy={loading || undefined} className={vx(VS_SECTION, CS_GAP)}>
      <div className={CS_HEAD}>
        <div className="min-w-0">
          <h2 id={headingId} className={VS_H2}>
            {t("studio_ui.lib_title", { defaultValue: "Сцены" })}
          </h2>
          <p className={vx(VS_SUB, "mt-1.5 max-w-xl")}>
            {selected
              ? t("studio_ui.lib_sub", {
                  defaultValue: "Готовые куски мультфильма с вашим героем. Добавьте нужные в ленту.",
                })
              : t("studio_ui.lib_pick_hero", { defaultValue: "Сначала выберите героя — сцены покажутся с ним" })}
          </p>
        </div>
        {/* С кем показываются сцены — и короткий путь назад к героям. */}
        {selected ? (
          <button
            type="button"
            onClick={onHeroes}
            aria-label={heroChip}
            title={heroChip}
            className={vx(CS_CHIP, "max-w-full !pl-1.5")}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={selected.image}
              alt=""
              loading="lazy"
              decoding="async"
              className="size-5 shrink-0 rounded-full bg-surface-2 object-cover"
            />
            <span className="min-w-0 truncate">{selected.name}</span>
            <FiChevronRight aria-hidden className="shrink-0 text-muted-2" />
          </button>
        ) : loading ? (
          // Место под «Выбрать героя» занято заранее: на телефоне чип стоит своей строкой.
          <span aria-hidden className={vx("h-10 w-28 shrink-0 rounded-full md:h-9", CS_SKELETON)} />
        ) : (
          <button type="button" onClick={onHeroes} className={CS_CHIP}>
            <FiUser aria-hidden className="shrink-0 text-vs-accent" />
            {t("studio_ui.lib_choose_hero", { defaultValue: "Выбрать героя" })}
          </button>
        )}
      </div>

      {/* Своя сцена: второй путь рядом с библиотекой — описать словами, что
          делает герой. Сцена встаёт в ленту черновиком; студия сама
          превратит описание в сцену при съёмке, с тем же героем. */}
      <div className={vx(VS_CARD, "mt-4 p-3 sm:p-4")}>
        <div className="flex items-start gap-3">
          <span aria-hidden className="grid size-10 shrink-0 place-items-center rounded-xl bg-accent/[0.1] text-lg text-vs-accent">
            <FiEdit3 />
          </span>
          <div className="min-w-0">
            <h3 id={customTitleId} className="text-sm font-semibold text-foreground">
              {t("studio_ui.lib_custom_title", { defaultValue: "Своя сцена" })}
            </h3>
            <p id={customNoteId} className="mt-0.5 text-[13px] leading-snug text-muted">
              {t("studio_ui.custom_note")}
            </p>
          </div>
        </div>
        <div className="mt-3 grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
          <textarea
            value={customText}
            onChange={(e) => onCustomText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && adding === null) {
                e.preventDefault();
                onAddCustom();
              }
            }}
            rows={2}
            placeholder={t("studio_ui.custom_placeholder")}
            aria-labelledby={customTitleId}
            aria-describedby={customNoteId}
            // !min-h: у VS_INPUT с 768 px своя min-h-10, и поле сжималось до двух строк.
            className={vx(VS_INPUT, "!min-h-[76px] resize-none py-2.5 leading-snug max-sm:text-base")}
          />
          <button
            type="button"
            onClick={() => onAddCustom()}
            disabled={adding !== null || customText.trim().length < 3}
            aria-busy={adding === -1 || undefined}
            className={vx(VS_BTN_GHOST, "w-full md:w-auto")}
          >
            {adding === -1 ? (
              <FiLoader aria-hidden className="animate-spin motion-reduce:animate-none" />
            ) : (
              <FiPlus aria-hidden className="text-vs-accent" />
            )}
            {t("studio_ui.custom_btn")}
          </button>
        </div>
        <p className="mt-2 text-xs text-muted-2">
          {selected ? t("studio_ui.custom_hero", { name: selected.name }) : t("studio_ui.custom_pick_hero")}
        </p>
      </div>

      {loading ? (
        <div aria-hidden className="mt-5 flex gap-2 overflow-hidden">
          {Array.from({ length: SKELETON_CHIPS }, (_, i) => (
            <span key={i} className={vx("h-10 w-24 shrink-0 rounded-full md:h-9", CS_SKELETON)} />
          ))}
        </div>
      ) : (
        categories.length > 1 && (
          // На телефоне разделы идут одной лентой, с 640 px переносятся строками — как чипы видеостудии.
          // Поля по вертикали — чтобы лента не срезала кольцо фокуса и зону нажатия.
          <div
            ref={attach}
            role="group"
            aria-label={t("studio_ui.lib_categories", { defaultValue: "Разделы сцен" })}
            className={vx(
              "vs-noscroll -mx-4 -mb-1 mt-5 overflow-x-auto px-4 py-1 sm:mx-0 sm:overflow-visible sm:px-0",
              EDGE_FADE[fade],
            )}
          >
            <ul className="flex w-max gap-2 sm:w-auto sm:flex-wrap">
              {chips.map((c) => (
                <li key={c.slug || "all"} className="flex">
                  <button
                    type="button"
                    onClick={() => onCategory(c.slug)}
                    aria-pressed={activeCat === c.slug}
                    className={vx(CS_CHIP, activeCat === c.slug && VS_PILL_ON)}
                  >
                    {c.emoji && <span aria-hidden>{c.emoji}</span>}
                    {c.title}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )
      )}

      {loading ? (
        <SceneGridSkeleton count={SKELETON_CARDS} className={GRID} />
      ) : empty ? (
        <div className={vx(CS_EMPTY, "mt-4")}>
          {audience === "all" ? (
            <>
              <p>{t("studio_ui.lib_empty", { defaultValue: "Сцен пока нет" })}</p>
              <button type="button" onClick={() => window.location.reload()} className={vx(VS_BTN_LINK, "!text-vs-accent")}>
                {t("studio_ui.lib_reload", { defaultValue: "Обновить страницу" })}
              </button>
            </>
          ) : (
            <p>{t("studio_ui.lib_empty_audience", { defaultValue: "Для этой аудитории сцен пока нет" })}</p>
          )}
        </div>
      ) : (
        <ul ref={gridRef} className={GRID}>
          {presets.map((p) => (
            <li key={p.id} className="flex min-w-0">
              <SceneCard
                preset={p}
                price={cardPrice(p)}
                hero={selected !== null}
                frame={frames[p.id] || ""}
                heroVideo={heroVideos[p.id] || ""}
                adding={adding === p.id}
                addLocked={adding !== null}
                tryingOn={tryingOn === p.id}
                tryLocked={tryingOn !== null}
                onAdd={onAdd}
                onTryOn={onTryOn}
              />
            </li>
          ))}
        </ul>
      )}

      {!loading && restCount > 0 && (
        <div className="mt-5 flex justify-center">
          <button type="button" onClick={more} className={VS_BTN_GHOST}>
            {t("studio_ui.show_more")}
            <span className="tabular-nums text-muted-2">{restCount}</span>
            <FiChevronDown aria-hidden />
          </button>
        </div>
      )}
    </section>
  );
}

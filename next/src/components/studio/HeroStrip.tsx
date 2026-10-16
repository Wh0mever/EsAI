"use client";

import { useEffect, useId } from "react";
import type { RefObject } from "react";
import { useTranslation } from "react-i18next";
import { FiChevronLeft, FiChevronRight } from "react-icons/fi";
import { useEdgeFade } from "@/components/vstudio/home/strip/useEdgeFade";
import { VS_H2, VS_ICON_BTN, VS_PILL_ON, VS_SECTION, VS_SUB, vx } from "@/components/vstudio/ui/skin";
import { prefersReducedMotion } from "@/components/vstudio/ui/useAutoplayAllowed";
import CharacterPicker, { type StudioCharacter } from "./CharacterPicker";
import type { Audience } from "./cartoonTypes";
import { HeroStripSkeleton } from "./library/HeroCard";
import { heroOrder } from "./library/heroOrder";
import { CS_ANCHOR, CS_CHIP, CS_GAP, CS_HEAD, CS_NOTE_GOLD, CS_SKELETON } from "./ui/cartoonSkin";

export type HeroStripProps = {
  loading: boolean;
  authed: boolean;
  /** Герои под выбранную аудиторию; свои — всегда. */
  heroes: StudioCharacter[];
  /** Герои, уже поставленные в сцены открытой ленты. */
  cast: StudioCharacter[];
  selected: StudioCharacter | null;
  /** Нажали «В ленту» без героя — подсказка над героями. */
  needHero: boolean;
  audience: Audience;
  /** Переключатель аудитории — только если есть взрослые сцены. */
  showAudience: boolean;
  balance: number | null;
  sectionRef: RefObject<HTMLDivElement | null>;
  onAudience: (a: Audience) => void;
  onPick: (c: StudioCharacter) => void;
  onCreated: (c: StudioCharacter) => void;
  onDeleted: (id: number) => void;
  onNeedAuth: () => void;
  onNeedCredits: (required: number, balance: number) => void;
};

/** Сколько заглушек в ленте, пока грузится витрина: с запасом на широкий экран. */
const SKELETONS = 7;
/** Стрелка ленты; у края — погашена, но в фокусе. */
const ARROW = vx(VS_ICON_BTN, "aria-disabled:cursor-not-allowed aria-disabled:opacity-50");

/**
 * Кто будет героем: лента карточек героев, как ленты видеостудии, —
 * в начале «Загрузить своего» и «Нарисовать по описанию», затем герои этого
 * мультфильма, свои и библиотечные. Справа в шапке — для кого снимаем и, на
 * широком экране, стрелки ленты.
 */
export default function HeroStrip({
  loading,
  authed,
  heroes,
  cast,
  selected,
  needHero,
  audience,
  showAudience,
  balance,
  sectionRef,
  onAudience,
  onPick,
  onCreated,
  onDeleted,
  onNeedAuth,
  onNeedCredits,
}: HeroStripProps) {
  const { t } = useTranslation("common");
  const headingId = useId();
  const { attach, fade, page } = useEdgeFade<HTMLDivElement>();
  const ordered = heroOrder(heroes, cast, selected);
  const castIds = new Set(cast.map((c) => c.id));
  const prompt = needHero && !selected;

  // Сцену добавляли без героя — студия уже прокрутила страницу сюда; фокус — на
  // первого героя, чтобы с клавиатуры выбрать его сразу. Страницу фокус не
  // двигает (её уже везёт прокрутка студии), ленту — к началу, где он стоит.
  useEffect(() => {
    if (!prompt) return;
    const root = sectionRef.current;
    root?.querySelector<HTMLElement>("[data-hero-strip]")?.scrollTo({
      left: 0,
      behavior: prefersReducedMotion() ? "auto" : "smooth",
    });
    const card =
      root?.querySelector<HTMLElement>("[data-hero-pick]") ?? root?.querySelector<HTMLElement>("[data-hero-card]");
    card?.focus({ preventScroll: true });
  }, [prompt, sectionRef]);

  return (
    <section aria-labelledby={headingId} aria-busy={loading || undefined} className={vx(VS_SECTION, CS_GAP)}>
      <div ref={sectionRef} className={CS_ANCHOR}>
        {/* Высота строки задана заранее: стрелки появляются после замера ленты и не должны её сдвигать. */}
        <div className={vx(CS_HEAD, "md:min-h-10")}>
          <div className="min-w-0">
            {/* tabIndex -1: сюда ставится фокус после «Мои герои» и «Выбрать героя». */}
            <h2 id={headingId} tabIndex={-1} className={vx(VS_H2, "outline-none")}>
              {t("studio_ui.heroes_title", { defaultValue: "Кто будет героем" })}
            </h2>
            <p className={vx(VS_SUB, "mt-1.5 max-w-xl")}>
              {t("studio_ui.heroes_sub", { defaultValue: "Он останется одинаковым во всех сценах" })}
            </p>
          </div>
          {/* Для кого снимаем: сужает и библиотеку героев, и разделы сцен. Пока
              витрина грузится, место под переключатель занято заглушками: на
              телефоне он стоит своей строкой, и шапка не вырастает после загрузки. */}
          {loading ? (
            <div aria-hidden className="flex gap-2 lg:ml-auto">
              {[0, 1, 2].map((i) => (
                <span key={i} className={vx("h-10 w-24 shrink-0 rounded-full md:h-9", CS_SKELETON)} />
              ))}
            </div>
          ) : showAudience && (
            <div
              role="group"
              aria-label={t("studio_ui.heroes_audience", { defaultValue: "Для кого" })}
              className="flex flex-wrap gap-2 lg:ml-auto"
            >
              {([
                ["all", t("studio_ui.aud_all")],
                ["kids", t("studio_ui.aud_kids")],
                ["adults", t("studio_ui.aud_adults")],
              ] as const).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => onAudience(key)}
                  aria-pressed={audience === key}
                  className={vx(CS_CHIP, audience === key && VS_PILL_ON)}
                >
                  {label}
                </button>
              ))}
            </div>
          )}
          {!loading && fade !== "none" && (
            <div className="hidden shrink-0 gap-2 lg:flex">
              {/* Не disabled: у края ленты стрелка гаснет, и фокус с неё упал бы на страницу. */}
              <button
                type="button"
                onClick={() => {
                  if (fade !== "start") page(-1);
                }}
                aria-disabled={fade === "start" || undefined}
                className={ARROW}
                aria-label={t("studio_ui.heroes_prev", { defaultValue: "Прокрутить назад" })}
              >
                <FiChevronLeft aria-hidden />
              </button>
              <button
                type="button"
                onClick={() => {
                  if (fade !== "end") page(1);
                }}
                aria-disabled={fade === "end" || undefined}
                className={ARROW}
                aria-label={t("studio_ui.heroes_next", { defaultValue: "Прокрутить вперёд" })}
              >
                <FiChevronRight aria-hidden />
              </button>
            </div>
          )}
        </div>

        {/* Живая область стоит всегда: появившуюся вместе с текстом читалка может не объявить. */}
        <div role="status" aria-live="polite">
          {prompt && <p className={vx(CS_NOTE_GOLD, "mt-4")}>{t("studio_ui.need_hero")}</p>}
        </div>

        {loading ? (
          <HeroStripSkeleton count={SKELETONS} />
        ) : (
          <CharacterPicker
            authed={authed}
            onNeedAuth={onNeedAuth}
            onNeedCredits={onNeedCredits}
            characters={ordered}
            value={selected}
            castIds={castIds}
            onPick={onPick}
            onCreated={onCreated}
            onDeleted={onDeleted}
            balance={balance}
            stripRef={attach}
            fade={fade}
            labelledBy={headingId}
          />
        )}
      </div>
    </section>
  );
}

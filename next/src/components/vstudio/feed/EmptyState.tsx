"use client";

import { memo, type CSSProperties } from "react";
import { useTranslation } from "react-i18next";
import { FiCoffee, FiFeather, FiFilm, FiSunrise } from "react-icons/fi";
import { IoSparklesOutline } from "react-icons/io5";
import type { IconType } from "react-icons";
import { VS_CARD_BTN, VS_LABEL, VS_SUB, VS_TAG, vx } from "../ui/skin";
import { useReveal } from "../ui/useReveal";
import { VS_EXAMPLES, type VsExample, type VsExampleId } from "./examples";

const ICONS: Record<VsExampleId, IconType> = {
  rooftop_cat: FiFilm,
  morning_coffee: FiCoffee,
  mountain_flight: FiSunrise,
  yurt_poster: FiFeather,
};

/** Карточки примеров появляются одна за другой: шаг задержки и её потолок (§1 — не больше 240 мс). */
const STAGGER_MS = 60;

function delay(step: number): CSSProperties {
  return { "--vs-delay": `${Math.min(240, step * STAGGER_MS)}ms` } as CSSProperties;
}

export type EmptyStateProps = {
  /** Клик по примеру: text — уже переведённый текст примера. */
  onPick: (example: VsExample, text: string) => void;
  disabled?: boolean;
};

/**
 * Проект без кадров (§9.6): «Что снимем?», подсказка про @ и 4 примера.
 * Пример только заполняет композер — ничего не запускает и не тратит.
 * Пока проекта нет вовсе, вместо этого блока лента показывает первый экран.
 */
function EmptyState({ onPick, disabled }: EmptyStateProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const reveal = useReveal<HTMLElement>();

  return (
    <div className="mx-auto flex w-full max-w-[680px] flex-col items-center gap-7 px-1 py-10 text-center sm:gap-8 sm:py-16">
      <div ref={reveal} className="vs-reveal flex flex-col items-center gap-3">
        <span className="relative grid size-14 place-items-center" aria-hidden>
          <span className="absolute -inset-5 rounded-full bg-accent/15 blur-2xl" />
          <span className="vs-card relative grid size-14 place-items-center rounded-full text-2xl text-accent">
            <IoSparklesOutline />
          </span>
        </span>
        <h2 className="vs-display mt-1 text-[26px] text-foreground sm:text-[32px]">
          {t("empty.title", { defaultValue: "Что снимем?" })}
        </h2>
        <p className={vx(VS_SUB, "max-w-md")}>
          {t("empty.hint", { defaultValue: "Опишите сцену внизу. Нажмите @, чтобы добавить своё фото." })}
        </p>
      </div>

      <div className="flex w-full flex-col gap-3">
        <p ref={reveal} style={delay(1)} className={vx(VS_LABEL, "vs-reveal text-left")}>
          {t("empty.examplesTitle", { defaultValue: "Попробуйте для начала" })}
        </p>
        <ul className="grid w-full grid-cols-1 gap-3 sm:grid-cols-2">
          {VS_EXAMPLES.map((ex, k) => {
            const Icon = ICONS[ex.id];
            const title = t(`empty.examples.${ex.id}.title`, { defaultValue: ex.title });
            const prompt = t(`empty.examples.${ex.id}.prompt`, { defaultValue: ex.prompt });
            const kind =
              ex.kind === "image"
                ? t("kind.image", { defaultValue: "Картинка" })
                : t("kind.video", { defaultValue: "Видео" });
            return (
              <li key={ex.id} ref={reveal} style={delay(k + 1)} className="vs-reveal flex">
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => onPick(ex, prompt)}
                  aria-label={t("empty.useExample", { defaultValue: "Взять пример «{{title}}»", title })}
                  className={vx(
                    VS_CARD_BTN,
                    "vs-sheen flex min-h-11 w-full flex-col gap-2.5 p-3.5 active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-60 sm:p-4",
                  )}
                >
                  <span className="flex items-center gap-2.5">
                    <span
                      className="grid size-8 shrink-0 place-items-center rounded-full border border-accent/25 bg-accent/[0.08] text-accent"
                      aria-hidden
                    >
                      <Icon />
                    </span>
                    <span className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">{title}</span>
                    <span className={vx(VS_TAG, "shrink-0")}>{kind}</span>
                  </span>
                  <span className="line-clamp-3 text-[13px] leading-snug text-muted">{prompt}</span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}

export default memo(EmptyState);

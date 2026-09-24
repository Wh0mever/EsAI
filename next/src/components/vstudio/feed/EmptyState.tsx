"use client";

import { memo } from "react";
import { useTranslation } from "react-i18next";
import { FiCoffee, FiFeather, FiFilm, FiSunrise } from "react-icons/fi";
import type { IconType } from "react-icons";
import { VS_EXAMPLES, type VsExample, type VsExampleId } from "./examples";

const ICONS: Record<VsExampleId, IconType> = {
  rooftop_cat: FiFilm,
  morning_coffee: FiCoffee,
  mountain_flight: FiSunrise,
  yurt_poster: FiFeather,
};

export type EmptyStateProps = {
  /** Клик по примеру: text — уже переведённый текст примера. */
  onPick: (example: VsExample, text: string) => void;
  disabled?: boolean;
};

/**
 * Пустая студия (§9.6): «Что снимем?», подсказка про @ и 4 примера.
 * Пример только заполняет композер — ничего не запускает и не тратит.
 */
function EmptyState({ onPick, disabled }: EmptyStateProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });

  return (
    <div className="mx-auto flex w-full max-w-[640px] flex-col items-center gap-5 px-1 py-8 text-center sm:py-14">
      <div className="flex flex-col items-center gap-2">
        <span className="grid size-12 place-items-center rounded-2xl bg-accent-soft text-2xl text-accent-strong" aria-hidden>
          <FiFilm />
        </span>
        <h2 className="text-xl font-semibold text-foreground sm:text-2xl">
          {t("empty.title", { defaultValue: "Что снимем?" })}
        </h2>
        <p className="max-w-md text-sm text-muted">
          {t("empty.hint", { defaultValue: "Опишите сцену внизу. Нажмите @, чтобы добавить своё фото." })}
        </p>
      </div>

      <div className="flex w-full flex-col gap-2">
        <p className="text-left text-xs font-medium uppercase tracking-wide text-muted-2">
          {t("empty.examplesTitle", { defaultValue: "Попробуйте для начала" })}
        </p>
        <ul className="grid w-full grid-cols-1 gap-2 sm:grid-cols-2">
          {VS_EXAMPLES.map((ex) => {
            const Icon = ICONS[ex.id];
            const title = t(`empty.examples.${ex.id}.title`, { defaultValue: ex.title });
            const prompt = t(`empty.examples.${ex.id}.prompt`, { defaultValue: ex.prompt });
            const kind =
              ex.kind === "image"
                ? t("kind.image", { defaultValue: "Картинка" })
                : t("kind.video", { defaultValue: "Видео" });
            return (
              <li key={ex.id} className="flex">
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => onPick(ex, prompt)}
                  aria-label={t("empty.useExample", { defaultValue: "Взять пример «{{title}}»", title })}
                  className="group flex min-h-11 w-full cursor-pointer flex-col gap-1.5 rounded-2xl border border-border bg-surface p-3 text-left transition-colors hover:border-accent/60 hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <span className="flex items-center gap-2 text-sm font-medium text-foreground">
                    <Icon className="shrink-0 text-accent-strong" aria-hidden />
                    <span className="truncate">{title}</span>
                    <span className="ml-auto shrink-0 rounded-full bg-surface-2 px-2 py-0.5 text-[11px] font-normal text-muted group-hover:bg-surface-3">
                      {kind}
                    </span>
                  </span>
                  <span className="line-clamp-3 text-xs leading-snug text-muted">{prompt}</span>
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

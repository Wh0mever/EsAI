"use client";

/**
 * Звук ролика. У моделей без звука переключатель выключен с видимой причиной
 * «Модель снимает без звука» — не прячем, чтобы не гадали, куда он делся.
 * По умолчанию включён: так же решает компилятор, если поле не пришло.
 */
import { useId } from "react";
import { useTranslation } from "react-i18next";
import { FiVolume2, FiVolumeX } from "react-icons/fi";
import type { ModelJSON } from "@/lib/vstudio/types";
import { VS_FOCUS } from "../ui/skin";
import { Reason, Section, cx } from "./SettingsBits";
import { tx } from "./settingsText";

export type AudioToggleProps = {
  model: ModelJSON;
  value: boolean | undefined;
  onChange: (value: boolean) => void;
};

export default function AudioToggle({ model, value, onChange }: AudioToggleProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const labelId = useId();
  const hintId = useId();
  const supported = model.caps.audio;
  const on = supported && value !== false;

  return (
    // Переключатель стоит в строке заголовка: слово «Звук» одно, оно же его подпись.
    <Section
      id={labelId}
      title={tx(t, "settings.audio")}
      icon={on ? <FiVolume2 /> : <FiVolumeX />}
      aside={
        <button
          type="button"
          role="switch"
          aria-checked={on}
          aria-labelledby={labelId}
          aria-describedby={hintId}
          disabled={!supported}
          onClick={() => supported && onChange(!on)}
          className={cx(
            // before: расширяет зону нажатия до 44 px по высоте, не раздвигая строку заголовка.
            "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors before:absolute before:-inset-x-2 before:-inset-y-2.5 before:content-['']",
            VS_FOCUS,
            // Включён: кромка — тёмное золото поверх золотой заливки (в тёмной теме сливается с ней, на белом
            // даёт дорожке чёткий край). Выключен: в светлой теме дорожка плотнее, иначе её не видно на белом.
            on
              ? "border-vs-accent/40 bg-accent"
              : "border-vs-ink/20 bg-vs-ink/[0.12] dark:border-vs-ink/15 dark:bg-vs-ink/[0.08]",
            supported ? "cursor-pointer" : "cursor-not-allowed opacity-50",
          )}
        >
          <span
            className={cx(
              "inline-block size-[18px] rounded-full shadow transition-transform duration-200 motion-reduce:transition-none",
              on ? "translate-x-[22px] bg-on-accent" : "translate-x-[2px] bg-foreground/80",
            )}
          />
        </button>
      }
    >
      <div id={hintId}>
        {!supported ? (
          <Reason>{tx(t, "settings.audioUnsupported", { model: model.name })}</Reason>
        ) : (
          <Reason tone="muted">{tx(t, on ? "settings.audioHint" : "settings.audioOff")}</Reason>
        )}
      </div>
    </Section>
  );
}

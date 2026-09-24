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
    <Section title={tx(t, "settings.audio")} icon={on ? <FiVolume2 /> : <FiVolumeX />}>
      <div className="flex items-center gap-3">
        <button
          type="button"
          role="switch"
          aria-checked={on}
          aria-labelledby={labelId}
          aria-describedby={hintId}
          disabled={!supported}
          onClick={() => supported && onChange(!on)}
          className={cx(
            "relative inline-flex h-7 w-12 shrink-0 items-center rounded-full border transition-colors",
            on ? "border-accent bg-accent" : "border-border bg-surface-3",
            supported ? "cursor-pointer" : "cursor-not-allowed opacity-50",
          )}
        >
          <span
            className={cx(
              "inline-block size-5 rounded-full shadow transition-transform duration-200",
              on ? "translate-x-6 bg-on-accent" : "translate-x-1 bg-surface",
            )}
          />
        </button>
        <span id={labelId} className="text-sm font-medium text-foreground">
          {tx(t, "settings.audio")}
        </span>
      </div>
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

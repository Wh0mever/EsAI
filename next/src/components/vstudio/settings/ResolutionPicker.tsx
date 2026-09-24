"use client";

/**
 * Качество (разрешение) с ценой-подсказкой под каждым значением: 1080p у
 * Seedance в 2,5 раза дороже 720p — это надо видеть до запуска.
 *
 * Одно значение — не кнопка, а строка «Модель снимает только в 720p» (видно,
 * почему выбора нет). Значение, которого модель не умеет, — выключено с причиной.
 */
import { useTranslation } from "react-i18next";
import { FiMonitor } from "react-icons/fi";
import type { ModelJSON } from "@/lib/vstudio/types";
import { OptionButton, Reason, Section } from "./SettingsBits";
import { priceHint } from "./settingsModel";
import { fmtNum, tx } from "./settingsText";

export type ResolutionPickerProps = {
  model: ModelJSON;
  value: string | undefined;
  onChange: (value: string) => void;
  duration?: number;
  aspect?: string;
};

export default function ResolutionPicker({ model, value, onChange, duration, aspect }: ResolutionPickerProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const all = model.caps.resolutions || [];
  if (!all.length) return null;

  const same = (a: string, b: string | undefined) => !!b && a.toLowerCase() === b.toLowerCase();
  const unsupported = value && !all.some((r) => same(r, value)) ? value : null;

  if (all.length === 1 && !unsupported) {
    return (
      <Section title={tx(t, "settings.resolution")} icon={<FiMonitor />}>
        <Reason tone="muted">{tx(t, "settings.resolutionOnly", { model: model.name, res: all[0] })}</Reason>
      </Section>
    );
  }

  return (
    <Section title={tx(t, "settings.resolution")} icon={<FiMonitor />}>
      <div className="grid grid-cols-3 gap-1.5">
        {all.map((r) => {
          const p = priceHint(model, { duration, resolution: r, aspect });
          return (
            <OptionButton
              key={r}
              active={same(r, value)}
              onClick={() => onChange(r)}
              label={r}
              sub={p != null ? tx(t, "settings.credits", { n: fmtNum(p) }) : undefined}
            />
          );
        })}
        {unsupported && <OptionButton active disabled label={unsupported} />}
      </div>
      {unsupported && <Reason>{tx(t, "settings.resolutionUnsupported", { model: model.name, res: unsupported })}</Reason>}
    </Section>
  );
}

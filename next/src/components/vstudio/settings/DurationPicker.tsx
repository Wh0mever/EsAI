"use client";

/**
 * Длительность ролика с ценой-подсказкой под каждым значением
 * (price.table / by_aspect, images=0; итог — только из quote).
 *
 * Выключенные значения всегда с видимой причиной:
 *   - Veo + фото-референсы снимает только 8 с (ref_forces_duration) — остальные
 *     выключены, само значение в композере не трогаем: уберёте фото — вернётся;
 *   - значение из «Изменить», которого модель не умеет, — отдельной кнопкой.
 * Длинный ряд (Seedance 2.5: 4…30) сворачивается до ходовых значений.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { FiClock, FiLock } from "react-icons/fi";
import type { ModelJSON } from "@/lib/vstudio/types";
import { VS_FOCUS } from "../ui/skin";
import { OptionButton, Reason, Section, cx } from "./SettingsBits";
import { priceHint, visibleDurations } from "./settingsModel";
import { fmtNum, tx } from "./settingsText";

export type DurationPickerProps = {
  model: ModelJSON;
  value: number | undefined;
  onChange: (value: number) => void;
  resolution?: string;
  aspect?: string;
  /** Сколько секунд модель снимет на самом деле (Veo + референсы → 8); null — как выбрано. */
  forced?: number | null;
};

export default function DurationPicker({ model, value, onChange, resolution, aspect, forced }: DurationPickerProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const [expanded, setExpanded] = useState(false);
  const all = model.caps.durations || [];
  if (!all.length) return null;

  const shown = visibleDurations(all, forced ?? value, expanded);
  // Кнопка «Все значения» нужна, только если ряд вообще сворачивается.
  const collapsible = visibleDurations(all, forced ?? value, false).length < all.length;
  const unsupported = value != null && !all.includes(value) && forced == null ? value : null;
  const price = (d: number) => priceHint(model, { duration: d, resolution, aspect });

  return (
    <Section
      title={tx(t, "settings.duration")}
      icon={<FiClock />}
      aside={
        collapsible ? (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            // Отрицательные поля: зона нажатия 44 px (32 px с 768 px), а строка заголовка остаётся своей высоты.
            className={cx(
              "-my-3 inline-flex min-h-11 cursor-pointer items-center rounded-full px-2 text-[11px] font-medium text-muted transition-colors hover:text-foreground md:-my-1.5 md:min-h-8",
              VS_FOCUS,
            )}
          >
            {expanded ? tx(t, "settings.showLess") : tx(t, "settings.showAll", { n: all.length })}
          </button>
        ) : undefined
      }
    >
      <div className="grid grid-cols-4 gap-1.5 sm:grid-cols-5">
        {shown.map((d) => {
          const p = price(d);
          const off = forced != null && d !== forced;
          const active = forced != null ? d === forced : d === value;
          return (
            <OptionButton
              key={d}
              active={active}
              disabled={off}
              onClick={() => onChange(d)}
              icon={forced != null && d === forced ? <FiLock className="size-3" aria-hidden /> : undefined}
              label={tx(t, "settings.seconds", { n: d })}
              sub={p != null ? tx(t, "settings.credits", { n: fmtNum(p) }) : undefined}
              ariaLabel={
                off
                  ? tx(t, "settings.disabledWhy", {
                      reason: tx(t, "settings.durationForced", { model: model.name, n: forced as number }),
                    })
                  : undefined
              }
            />
          );
        })}
        {unsupported != null && <OptionButton active disabled label={tx(t, "settings.seconds", { n: unsupported })} />}
      </div>
      {forced != null && <Reason>{tx(t, "settings.durationForced", { model: model.name, n: forced })}</Reason>}
      {unsupported != null && <Reason>{tx(t, "settings.durationUnsupported", { model: model.name, n: unsupported })}</Reason>}
    </Section>
  );
}

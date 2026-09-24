"use client";

/**
 * Пропорции кадра: наглядные прямоугольники «▯ 9:16» плюс «Авто».
 *
 * Набор — ровно то, что умеет выбранная модель (caps.aspect_ratios); «Авто»
 * есть всегда и провайдеру не отправляется (§4.4 п. 4). Скрытого разбора
 * текста нет (§0 п. 11): найденное в тексте предлагает ComposerHints.
 *
 * Если значение пришло из «Изменить» и модель его не умеет, оно показывается
 * выключенным с причиной — молча не подменяем.
 * Цена под пропорцией — только у моделей, где она от пропорции зависит (Seedance 21:9).
 */
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import type { ModelJSON, VsKind } from "@/lib/vstudio/types";
import { AspectShape, IconAspect, aspectHint } from "@/components/ui/AspectIcon";
import { OptionButton, Reason, Section } from "./SettingsBits";
import { AUTO, aspectAffectsPrice, priceHint } from "./settingsModel";
import { fmtNum, tx } from "./settingsText";

export type AspectPickerProps = {
  kind: VsKind;
  model: ModelJSON;
  value: string | undefined;
  onChange: (value: string) => void;
  /** Для цены под пропорцией: текущие длительность и качество. */
  duration?: number;
  resolution?: string;
};

export default function AspectPicker({ kind, model, value, onChange, duration, resolution }: AspectPickerProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const tc = t as unknown as TFunction;
  const options = [...(model.caps.aspect_ratios || []), AUTO];
  const current = value || AUTO;
  const unsupported = !options.includes(current) ? current : null;
  const showPrice = kind === "video" && aspectAffectsPrice(model);

  const label = (r: string) => (r === AUTO ? tx(t, "settings.aspectAuto") : r);
  const hint =
    current === AUTO
      ? tx(t, kind === "image" ? "settings.aspectAutoImage" : "settings.aspectAutoVideo")
      : aspectHint(tc, current);

  return (
    <Section title={tx(t, "settings.aspect")} icon={<IconAspect />}>
      <div className="grid grid-cols-4 gap-1.5">
        {options.map((r) => {
          const price = showPrice ? priceHint(model, { duration, resolution, aspect: r }) : null;
          return (
            <OptionButton
              key={r}
              active={current === r}
              onClick={() => onChange(r)}
              icon={<AspectShape ratio={r} size={20} />}
              label={label(r)}
              sub={price != null ? tx(t, "settings.credits", { n: fmtNum(price) }) : undefined}
              title={r === AUTO ? hint : aspectHint(tc, r)}
            />
          );
        })}
        {unsupported && (
          <OptionButton active disabled icon={<AspectShape ratio={unsupported} size={20} />} label={unsupported} />
        )}
      </div>
      {unsupported ? (
        <Reason>{tx(t, "settings.aspectUnsupported", { model: model.name, value: unsupported })}</Reason>
      ) : (
        <Reason tone="muted">{hint}</Reason>
      )}
    </Section>
  );
}

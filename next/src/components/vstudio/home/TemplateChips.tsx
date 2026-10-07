"use client";

import { useEffect, useId, useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import type { IconType } from "react-icons";
import {
  FiArrowRight,
  FiCheck,
  FiFilm,
  FiHexagon,
  FiImage,
  FiLayout,
  FiMusic,
  FiShoppingBag,
  FiSmartphone,
  FiSmile,
  FiZap,
} from "react-icons/fi";
import { VS_H2, VS_PILL, VS_PILL_ON, VS_SECTION, VS_SECTION_GAP, VS_SUB, vx } from "../ui/skin";
import { useReveal } from "../ui/useReveal";
import { trackHomePick } from "./homePick";
import { EDGE_FADE, useEdgeFade } from "./strip/useEdgeFade";
import { VS_TEMPLATES, type VsTemplate, type VsTemplateId } from "./templates";

export type TemplateChipsProps = {
  /** Выбран сценарий; text — его заготовка запроса, уже переведённая. false — заготовка в запрос не легла. */
  onPick: (template: VsTemplate, text: string) => boolean | void;
  disabled?: boolean;
};

const ICONS: Record<VsTemplateId, IconType> = {
  film: FiFilm,
  product: FiShoppingBag,
  ugc: FiSmartphone,
  clip: FiMusic,
  anime: FiZap,
  photo: FiImage,
  poster: FiLayout,
  logo: FiHexagon,
};

/** Сколько чип остаётся золотым после нажатия. */
const PICKED_MS = 1200;

// Чип на телефоне — 40 px в высоту: невидимое поле сверху и снизу доводит зону нажатия до 44.
const CHIP = vx(
  VS_PILL,
  "relative active:scale-[0.97] before:absolute before:inset-x-0 before:-inset-y-0.5 before:content-[''] md:before:hidden",
);
const CHIP_ICON = "shrink-0 text-sm opacity-80";

/**
 * «С чего начать»: жанры-заготовки. Нажатие ничего не запускает и не тратит —
 * оно кладёт в панель запроса текст с пропусками в квадратных скобках.
 * Заполнение происходит внизу экрана, а палец или курсор — здесь, поэтому
 * нажатый чип на секунду становится золотым с галочкой: «готово, смотрите вниз».
 *
 * На телефоне чипы идут одной лентой (девять штук строками заняли бы
 * пол-экрана) и стоят сразу под заголовком, пояснение — после них: так первый
 * ряд виден над панелью запроса без прокрутки. С 640 px пояснение возвращается
 * под заголовок, а чипы переносятся строками.
 */
export default function TemplateChips({ onPick, disabled }: TemplateChipsProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const reveal = useReveal<HTMLElement>();
  const { attach, fade } = useEdgeFade<HTMLDivElement>();
  const headingId = useId();
  // Объект, а не id: повторное нажатие того же чипа заново отсчитывает время.
  const [picked, setPicked] = useState<{ id: VsTemplateId } | null>(null);

  useEffect(() => {
    if (!picked) return;
    const timer = window.setTimeout(() => setPicked(null), PICKED_MS);
    return () => window.clearTimeout(timer);
  }, [picked]);

  const pick = (template: VsTemplate) => {
    // Галочка «готово» — только если заготовка действительно легла в запрос (свой текст она не заменяет).
    if (onPick(template, t(`home.tpl.${template.id}.prompt`, { defaultValue: template.prompt })) !== false) {
      setPicked({ id: template.id });
    }
  };

  return (
    <section
      ref={reveal}
      aria-labelledby={headingId}
      className={vx(VS_SECTION, VS_SECTION_GAP, "vs-reveal flex flex-col")}
    >
      <h2 id={headingId} className={VS_H2}>
        {t("home.templates.title", { defaultValue: "С чего начать" })}
      </h2>
      <p className={vx(VS_SUB, "order-last mt-3 sm:order-none sm:mt-1.5")}>
        {t("home.templates.sub", { defaultValue: "Сценарий заполнит запрос — останется поправить под себя" })}
      </p>

      {/* Поля по вертикали — чтобы лента не срезала кольцо фокуса и зону нажатия. */}
      <div
        ref={attach}
        className={vx(
          "vs-noscroll -mx-4 -mb-1 mt-3 overflow-x-auto px-4 py-1 sm:mx-0 sm:overflow-visible sm:px-0",
          EDGE_FADE[fade],
        )}
      >
        <ul className="flex w-max gap-2 sm:w-auto sm:flex-wrap">
          {VS_TEMPLATES.map((template) => {
            const on = picked?.id === template.id;
            const Icon = on ? FiCheck : ICONS[template.id];
            return (
              <li key={template.id} className="flex">
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => pick(template)}
                  className={vx(CHIP, on && VS_PILL_ON)}
                >
                  <Icon aria-hidden className={CHIP_ICON} />
                  {t(`home.tpl.${template.id}.label`, { defaultValue: template.label })}
                </button>
              </li>
            );
          })}
          <li className="flex">
            <Link href="/studio" onClick={() => trackHomePick("template", "cartoon")} className={vx(CHIP, "group")}>
              <FiSmile aria-hidden className={CHIP_ICON} />
              {t("home.templates.cartoon", { defaultValue: "Мультфильм" })}
              <FiArrowRight
                aria-hidden
                className="shrink-0 text-sm text-muted-2 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-accent motion-reduce:transition-none"
              />
            </Link>
          </li>
        </ul>
      </div>
    </section>
  );
}

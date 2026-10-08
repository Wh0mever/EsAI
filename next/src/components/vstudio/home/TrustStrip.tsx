"use client";

import { useTranslation } from "react-i18next";
import { FiCheckCircle, FiClock, FiTag } from "react-icons/fi";
import { VS_SECTION, VS_SECTION_GAP, vx } from "../ui/skin";
import { useReveal } from "../ui/useReveal";

/** Пропсов нет: три факта — постоянный текст. */
export type TrustStripProps = Record<string, never>;

/**
 * Три факта, после которых не страшно нажать «Создать»: цена известна заранее,
 * платят только за результат, готовое не пропадает. Тихая строка в конце
 * первого экрана — не баннер. Третий факт — про «Историю», а не про «Мои
 * материалы»: там только картинки, готовые видео лежат в своих проектах.
 * Значок тот же, что у «Истории» в левой колонке: по нему её и находят.
 */
export default function TrustStrip() {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const reveal = useReveal<HTMLElement>();

  const facts = [
    { id: "price", Icon: FiTag, text: t("home.trust.price", { defaultValue: "Цена видна до запуска" }) },
    {
      id: "result",
      Icon: FiCheckCircle,
      text: t("home.trust.result", { defaultValue: "Кредиты списываются только за готовый результат" }),
    },
    {
      id: "files",
      Icon: FiClock,
      text: t("home.trust.files", { defaultValue: "Готовые видео и картинки остаются в истории" }),
    },
  ];

  return (
    <footer ref={reveal} className={vx(VS_SECTION, VS_SECTION_GAP, "vs-reveal")}>
      <ul className="flex flex-col gap-3 border-t border-vs-ink/10 pt-6 text-[13px] leading-snug text-muted sm:flex-row sm:flex-wrap sm:justify-center sm:gap-x-10">
        {facts.map(({ id, Icon, text }) => (
          <li key={id} className="flex items-start gap-2.5">
            <Icon aria-hidden className="mt-0.5 shrink-0 text-sm text-vs-accent/70" />
            {text}
          </li>
        ))}
      </ul>
    </footer>
  );
}

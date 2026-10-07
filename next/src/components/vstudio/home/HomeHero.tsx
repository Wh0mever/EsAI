"use client";

import { Fragment } from "react";
import { useTranslation } from "react-i18next";
import { IoSparklesOutline } from "react-icons/io5";
import { VS_EYEBROW, VS_SECTION, VS_SUB, vx } from "../ui/skin";
import { useReveal } from "../ui/useReveal";

export type HomeHeroProps = {
  /** Сколько моделей в студии (видео + картинки); 0 — список ещё не пришёл или пуст. */
  modelCount: number;
};

// Русский текст по умолчанию для трёх форм числа; переводы — home.hero.sub_one|few|many|other.
const SUB_RU = {
  one: "{{count}} модель видео и картинок в одном окне. Свои фото — через @. Цена видна до запуска.",
  few: "{{count}} модели видео и картинок в одном окне. Свои фото — через @. Цена видна до запуска.",
  many: "{{count}} моделей видео и картинок в одном окне. Свои фото — через @. Цена видна до запуска.",
} as const;

const RU_FORMS = new Intl.PluralRules("ru");

function subRu(count: number): string {
  const form = RU_FORMS.select(count);
  return form === "one" || form === "few" ? SUB_RU[form] : SUB_RU.many;
}

/**
 * Первое, что читает человек: что это и что он получит. Кнопок нет — действие
 * одно, и оно внизу, в панели запроса. Луч и зерно за текстом рисует
 * StudioHome: они общие для заголовка и карусели.
 *
 * Невысокое окно ноутбука (шире 1024 px, ниже 1040 px): заголовок в две строки,
 * карусель и панель запроса вместе в него не помещаются, и кадры — главное на
 * экране — уезжали под панель. Там заголовок идёт одной строкой, а отступы
 * меньше: блок ниже на ~90 px. В высоком окне, на планшете и телефоне строк две.
 */
export default function HomeHero({ modelCount }: HomeHeroProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const reveal = useReveal<HTMLElement>();

  const sub =
    modelCount > 0
      ? t("home.hero.sub", { count: modelCount, defaultValue: subRu(modelCount) })
      : t("home.hero.subPlain", {
          defaultValue: "Видео и картинки по вашему описанию. Свои фото — через @. Цена видна до запуска.",
        });
  // «@» здесь — тот же знак, что на кнопке в панели запроса: цветом, чтобы читался как клавиша, а не как опечатка.
  const [subHead, ...subTail] = sub.split("@");

  return (
    <header
      className={vx(
        VS_SECTION,
        "flex flex-col items-center pt-8 text-center sm:pt-12 lg:[@media(max-height:1040px)]:pt-6",
      )}
    >
      <p ref={reveal} className={vx(VS_EYEBROW, "vs-reveal")}>
        <IoSparklesOutline aria-hidden className="text-[13px]" />
        {t("home.hero.eyebrow", { defaultValue: "Видеостудия EsAI" })}
      </p>
      <h1
        ref={reveal}
        className="vs-display vs-reveal mt-4 text-balance text-[34px] text-foreground [--vs-delay:80ms] sm:mt-5 sm:text-5xl lg:text-[56px] lg:[@media(max-height:1040px)]:mt-3.5"
      >
        {t("home.hero.title", { defaultValue: "Снимайте видео" })}{" "}
        <br className="lg:[@media(max-height:1040px)]:hidden" />
        {/* Курсив выступает за свою рамку справа: без поля градиент срезал бы край последней буквы. */}
        <span className="vs-serif vs-gold-text -mr-[0.08em] pr-[0.08em]">
          {t("home.hero.accent", { defaultValue: "одной фразой" })}
        </span>
      </h1>
      <p
        ref={reveal}
        className={vx(
          VS_SUB,
          "vs-reveal mt-3 max-w-xl text-balance [--vs-delay:160ms] sm:mt-4 lg:[@media(max-height:1040px)]:mt-3 lg:[@media(max-height:1040px)]:max-w-none",
        )}
      >
        {subHead}
        {subTail.map((part, i) => (
          <Fragment key={i}>
            <span className="font-semibold text-accent">@</span>
            {part}
          </Fragment>
        ))}
      </p>
    </header>
  );
}

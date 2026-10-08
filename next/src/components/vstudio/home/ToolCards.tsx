"use client";

import Link from "next/link";
import { useId } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useVStudio } from "../context";
import { openLockedModel } from "../settings/RunSettingsPanel";
import { VS_SECTION, VS_SECTION_GAP, VS_SHEEN_ON_MEDIA, vx } from "../ui/skin";
import { useReveal } from "../ui/useReveal";
import { trackHomePick } from "./homePick";
import { HOME_CARD, HOME_CELLS, HOME_CELL_IN, staggerStyle } from "./tools/cardSkin";
import { callDockOrFocus } from "./tools/dock";
import { framesPlan } from "./tools/framesPlan";
import { chooseModel } from "./tools/modelStrip";
import SectionHead from "./tools/SectionHead";
import { CartoonArt, FramesArt, ImageArt, RefsArt } from "./tools/ToolArt";
import { useFramesFocus } from "./tools/useFramesFocus";

export type ToolCardsProps = {
  /** Постер сцены мультстудии — для карточки «Мультстудия»; null — значок плёнки. */
  cartoonPoster: string | null;
};

/**
 * Карточка-инструмент. Под курсором и в фокусе с клавиатуры она ставит
 * переменную --vs-on — по ней оживает картинка (tools/ToolArt). При «меньше
 * движения» переменная не ставится, и картинка неподвижна.
 */
const CARD = vx(HOME_CARD, "motion-safe:hover:[--vs-on:1] motion-safe:focus-visible:[--vs-on:1]");

function CardText({ title, text }: { title: string; text: string }) {
  return (
    <span className="flex w-full flex-1 flex-col gap-1 p-3 sm:p-3.5">
      <span className="text-sm font-semibold leading-snug text-foreground sm:text-[15px]">{title}</span>
      <span className="text-xs leading-snug text-muted sm:text-[13px]">{text}</span>
    </span>
  );
}

/**
 * «Инструменты режиссёра» (§2.2): четыре возможности студии, о которых по
 * одному полю запроса не догадаться. Карточка ничего не запускает и не тратит:
 * она открывает нужное действие панели запроса (выбор файла, слоты кадров,
 * мини-генератор картинки) или уводит в мультстудию.
 */
export default function ToolCards({ cartoonPoster }: ToolCardsProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { state, dispatch, actions } = useVStudio();
  const reveal = useReveal<HTMLElement>();
  const headId = useId();
  const { composer, models } = state;
  const showFramesSoon = useFramesFocus();

  const onRefs = () => {
    trackHomePick("tool", "refs");
    if (!actions.requireAuth()) return;
    callDockOrFocus("openUpload");
  };

  const onFrames = () => {
    trackHomePick("tool", "frames");
    const plan = framesPlan(models, composer);
    if (plan.kind === "locked") {
      // Кадры умеют только модели платного тарифа — тот же путь, что у замка в списке моделей.
      openLockedModel(dispatch, { requireAuth: actions.requireAuth });
      return;
    }
    if (plan.kind !== "select") {
      callDockOrFocus("focusFrames");
      return;
    }
    chooseModel(dispatch, models, composer, "video", plan.model.id);
    // Модель — это и цена: о том, что она сменилась не рукой человека, говорим вслух.
    actions.toast(
      t("home.tools.frames.switched", {
        defaultValue: "Выбрали {{model}} — эта модель снимает по заданным кадрам",
        model: plan.model.name,
      }),
      "info",
    );
    // Слоты кадров появятся, когда панель запроса перерисуется с новой моделью, — зовём её кадром позже.
    showFramesSoon();
  };

  const onImage = () => {
    trackHomePick("tool", "image");
    if (!actions.requireAuth()) return;
    callDockOrFocus("openImageGen");
  };

  // Пока список моделей не пришёл, карточки не прячем: сетка не должна прыгать.
  const withFrames = !models || framesPlan(models, composer).kind !== "none";
  const withImage = !models || models.image.length > 0;

  const cards: { id: string; node: ReactNode }[] = [
    {
      id: "refs",
      node: (
        <button type="button" onClick={onRefs} className={CARD}>
          <RefsArt />
          <CardText
            title={t("home.tools.refs.title", { defaultValue: "Свои герои через @" })}
            text={t("home.tools.refs.text", {
              defaultValue: "Загрузите фото человека или товара и отметьте его в запросе",
            })}
          />
        </button>
      ),
    },
  ];
  if (withFrames) {
    cards.push({
      id: "frames",
      node: (
        <button type="button" onClick={onFrames} className={CARD}>
          <FramesArt />
          <CardText
            title={t("home.tools.frames.title", { defaultValue: "Первый и последний кадр" })}
            text={t("home.tools.frames.text", { defaultValue: "Задайте, с чего ролик начнётся и чем закончится" })}
          />
        </button>
      ),
    });
  }
  if (withImage) {
    cards.push({
      id: "image",
      node: (
        <button type="button" onClick={onImage} className={CARD}>
          <ImageArt />
          <CardText
            title={t("home.tools.image.title", { defaultValue: "Картинка для кадра" })}
            text={t("home.tools.image.text", {
              defaultValue: "Нет нужного фото — создайте его здесь же и поставьте в ролик",
            })}
          />
        </button>
      ),
    });
  }
  cards.push({
    id: "cartoon",
    node: (
      // Шапка этой карточки — настоящий кадр: блик по нему идёт тихий (VS_SHEEN_ON_MEDIA).
      <Link href="/studio" onClick={() => trackHomePick("tool", "cartoon")} className={vx(CARD, VS_SHEEN_ON_MEDIA)}>
        <CartoonArt poster={cartoonPoster} />
        <CardText
          title={t("home.tools.cartoon.title", { defaultValue: "Мультстудия" })}
          text={t("home.tools.cartoon.text", {
            defaultValue: "150 готовых сцен: выберите героя и соберите мультфильм",
          })}
        />
      </Link>
    ),
  });

  return (
    <section ref={reveal} aria-labelledby={headId} className={vx(VS_SECTION, VS_SECTION_GAP, "vs-reveal", HOME_CELLS)}>
      <SectionHead id={headId} title={t("home.tools.title", { defaultValue: "Инструменты режиссёра" })} />
      <ul className={vx("mt-5 grid grid-cols-2 gap-3 sm:mt-6", cards.length > 3 ? "lg:grid-cols-4" : "lg:grid-cols-3")}>
        {cards.map((card, i) => (
          <li key={card.id} className={vx("min-w-0", HOME_CELL_IN)} style={staggerStyle(i)}>
            {card.node}
          </li>
        ))}
      </ul>
    </section>
  );
}

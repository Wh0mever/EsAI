"use client";

import { memo, useCallback, useLayoutEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useVStudio } from "../context";
import { applyNotice, applyReelItem, reelModelName, wantsPhoto, type ApplyNotice } from "./applyItem";
import ContinueStrip from "./ContinueStrip";
import HomeHero from "./HomeHero";
import { trackHomePick } from "./homePick";
import ModelStrip from "./ModelStrip";
import ReelCoverflow from "./ReelCoverflow";
import { homeStarters } from "./starters";
import TemplateChips from "./TemplateChips";
import type { VsStarter, VsTemplate } from "./templates";
import ToolCards from "./ToolCards";
import { focusComposer } from "./tools/dock";
import { useFramesFocus } from "./tools/useFramesFocus";
import Trends from "./Trends";
import TrustStrip from "./TrustStrip";
import { useShowreel, type ReelItem } from "./useShowreel";

export type StudioHomeProps = {
  /** Сценарий выбран: вид, текст и пропорция уходят в композер (RunThread). false — запрос не тронут. */
  onStarter: (starter: VsStarter) => boolean | void;
  disabled?: boolean;
};

/**
 * Первый экран студии (§2.2): пока проекта нет, лента показывает его вместо
 * пустого состояния. Секции независимы и каждая рисует себя сама; здесь —
 * только их порядок, кадры карусели и «Трендов» и то, что происходит по
 * нажатию на пример в них и по выбору сценария. Ничего не запускается и не
 * тратится: любое нажатие лишь готовит панель запроса.
 */
function StudioHome({ onStarter, disabled }: StudioHomeProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { state, dispatch, actions } = useVStudio();
  const show = useShowreel();
  const showFramesSoon = useFramesFocus();

  const say = (notice: NonNullable<ApplyNotice>, model: string): string => {
    switch (notice) {
      case "kept":
        return t("home.use.kept", { defaultValue: "Модель и параметры выбраны. Текст запроса не тронули." });
      case "gone":
        return t("home.use.gone", { defaultValue: "Модели этой работы сейчас нет в студии — осталась выбранная." });
      case "locked_filled":
        return t("home.use.lockedFilled", {
          defaultValue:
            "Пример снят на {{model}} — она доступна на платном тарифе. Запрос подставили, модель осталась ваша.",
          model,
        });
      case "locked_kept":
        return t("home.use.lockedKept", {
          defaultValue:
            "Пример снят на {{model}} — она доступна на платном тарифе. Модель и текст запроса остались ваши.",
          model,
        });
      case "locked":
        return t("home.use.locked", {
          defaultValue: "Пример снят на {{model}} — она доступна на платном тарифе. Модель осталась ваша.",
          model,
        });
      // В карусели и «Трендах» только ролики, поэтому вид меняется всегда на видео.
      case "locked_switched":
        return t("home.use.lockedSwitched", {
          defaultValue:
            "Пример снят на {{model}} — она доступна на платном тарифе. Переключили на видео с доступной вам моделью.",
          model,
        });
      case "locked_switched_kept":
        return t("home.use.lockedSwitchedKept", {
          defaultValue:
            "Пример снят на {{model}} — она доступна на платном тарифе. Переключили на видео с доступной вам моделью. Текст запроса не тронули.",
          model,
        });
    }
  };
  const photoTip = t("home.use.photo", { defaultValue: "Добавьте своё фото — пример снят по картинке." });

  // Обработчики отдаём секциям неизменными (карусель тяжёлая, перерисовывать
  // её на каждую букву в запросе незачем), а свежее состояние читаем отсюда.
  const live = useRef({ state, dispatch, actions, onStarter, disabled, say, photoTip, t, show });
  useLayoutEffect(() => {
    live.current = { state, dispatch, actions, onStarter, disabled, say, photoTip, t, show };
  });

  // Пример из карусели и из «Трендов» применяется одинаково; различается только шаг воронки.
  const takeExample = useCallback(
    (item: ReelItem) => {
      // Сцена мультстудии — ссылка в /studio: переход делает сама карточка.
      if (item.source !== "vstudio") return;
      const cur = live.current;
      if (cur.disabled) return;
      // Текст прошлого примера или сценария новый пример заменяет, свой текст человека — нет.
      // Прошлый пример мог быть и из карусели, и из «Трендов».
      const starters = homeStarters(cur.t, [...cur.show.reel, ...cur.show.trends]);
      const outcome = applyReelItem(item, cur.state, cur.dispatch, starters);
      const notice = applyNotice(item, cur.state.models, outcome, cur.state.composer.kind, cur.state.composer.model);
      if (notice) cur.actions.toast(cur.say(notice, reelModelName(item, cur.state.models)), "info");
      if (!wantsPhoto(item, cur.state.composer)) {
        focusComposer();
        return;
      }
      // Пример снят по фото, а оно чужое — в запрос его не подставить. Просим своё и
      // ведём к слотам кадров, как карточка «Первый и последний кадр».
      cur.actions.toast(cur.photoTip, "info");
      showFramesSoon();
    },
    [showFramesSoon],
  );

  const onReelUse = useCallback(
    (item: ReelItem) => {
      trackHomePick("reel", item.id);
      takeExample(item);
    },
    [takeExample],
  );

  const onTrendUse = useCallback(
    (item: ReelItem) => {
      trackHomePick("trend", item.id);
      takeExample(item);
    },
    [takeExample],
  );

  const onTemplate = useCallback((template: VsTemplate, text: string) => {
    trackHomePick("template", template.id);
    return live.current.onStarter({ kind: template.kind, text, aspect: template.aspect });
  }, []);

  const modelCount = state.models ? state.models.video.length + state.models.image.length : 0;

  return (
    <div className="flex w-full flex-col pb-6">
      {/* Блок обрезает луч по своим краям. В тёмной теме — целиком: тень карусели на чёрной сцене
          всё равно не видна. На светлой сцене та же тень, срезанная по низу блока, легла бы под
          кадрами ровной полосой, как «пол», — там низ открыт (clip-path пускает тень ещё на 5rem,
          бока и верх режутся как раньше). */}
      <div className="vs-grain relative overflow-x-clip [clip-path:inset(0_0_-5rem_0)] dark:overflow-hidden dark:[clip-path:none]">
        <div className="vs-beam" aria-hidden />
        {/* Свой слой: иначе луч (он absolute) лёг бы поверх текста и кадров. */}
        <div className="relative">
          <HomeHero modelCount={modelCount} />
          <ReelCoverflow items={show.reel} loading={show.loading} onUse={onReelUse} />
        </div>
      </div>
      <ContinueStrip />
      <TemplateChips onPick={onTemplate} disabled={disabled} />
      <ModelStrip />
      <ToolCards cartoonPoster={show.cartoonPoster} />
      <Trends items={show.trends} onUse={onTrendUse} />
      <TrustStrip />
    </div>
  );
}

export default memo(StudioHome);

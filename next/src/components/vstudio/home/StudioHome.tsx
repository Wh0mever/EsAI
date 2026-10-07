"use client";

import { memo, useCallback, useLayoutEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useVStudio } from "../context";
import { COMPOSER_FILLED_EVENT } from "../feed/feedLogic";
import { openLockedModel } from "../settings/RunSettingsPanel";
import { applyNotice, applyReelItem } from "./applyItem";
import ContinueStrip from "./ContinueStrip";
import HomeHero from "./HomeHero";
import { trackHomePick } from "./homePick";
import ModelStrip from "./ModelStrip";
import ReelCoverflow from "./ReelCoverflow";
import ShowcaseGallery from "./ShowcaseGallery";
import TemplateChips from "./TemplateChips";
import type { VsStarter, VsTemplate } from "./templates";
import ToolCards from "./ToolCards";
import TrustStrip from "./TrustStrip";
import { useShowreel, type ReelItem } from "./useShowreel";

export type StudioHomeProps = {
  /** Сценарий выбран: вид, текст и пропорция уходят в композер (RunThread). false — запрос не тронут. */
  onStarter: (starter: VsStarter) => boolean | void;
  disabled?: boolean;
};

/** Композер слушает это событие сам: фокус в редактор, на телефоне — показать панель запроса. */
function focusComposer() {
  try {
    window.dispatchEvent(new CustomEvent(COMPOSER_FILLED_EVENT, { detail: { reason: "example" } }));
  } catch {
    /* старый браузер без CustomEvent — композер просто не возьмёт фокус */
  }
}

/**
 * Первый экран студии (§2.2): пока проекта нет, лента показывает его вместо
 * пустого состояния. Секции независимы и каждая рисует себя сама; здесь —
 * только их порядок, общие данные витрины и то, что происходит по нажатию
 * «Снять похожее» и по выбору сценария. Ничего не запускается и не тратится:
 * любое нажатие лишь готовит панель запроса.
 */
function StudioHome({ onStarter, disabled }: StudioHomeProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { state, dispatch, actions } = useVStudio();
  const show = useShowreel();

  const notices = {
    kept: t("home.use.kept", { defaultValue: "Модель и параметры выбраны. Текст запроса не тронули." }),
    gone: t("home.use.gone", { defaultValue: "Модели этой работы сейчас нет в студии — осталась выбранная." }),
  };

  // Обработчики отдаём секциям неизменными (карусель тяжёлая, перерисовывать
  // её на каждую букву в запросе незачем), а свежее состояние читаем отсюда.
  const live = useRef({ state, dispatch, actions, onStarter, disabled, notices });
  useLayoutEffect(() => {
    live.current = { state, dispatch, actions, onStarter, disabled, notices };
  });

  const applyItem = useCallback((item: ReelItem, what: "reel" | "showcase") => {
    trackHomePick(what, item.id);
    // Сцена мультстудии — ссылка в /studio: переход делает сама карточка.
    if (item.source !== "vstudio") return;
    const cur = live.current;
    if (cur.disabled) return;
    const outcome = applyReelItem(item, cur.state, cur.dispatch);
    if (outcome === "locked") {
      // Тот же путь, что у замка в панели параметров: вход или пэйволл, модель не меняется.
      openLockedModel(cur.dispatch, { requireAuth: cur.actions.requireAuth });
      return;
    }
    const notice = applyNotice(item, cur.state.models, outcome);
    if (notice) cur.actions.toast(cur.notices[notice], "info");
    focusComposer();
  }, []);

  const onReelUse = useCallback((item: ReelItem) => applyItem(item, "reel"), [applyItem]);
  const onShowcaseUse = useCallback((item: ReelItem) => applyItem(item, "showcase"), [applyItem]);

  const onTemplate = useCallback((template: VsTemplate, text: string) => {
    trackHomePick("template", template.id);
    return live.current.onStarter({ kind: template.kind, text, aspect: template.aspect });
  }, []);

  const modelCount = state.models ? state.models.video.length + state.models.image.length : 0;
  const cartoonPoster = useMemo(() => {
    const withPoster = (item: ReelItem) => item.source === "cartoon" && item.poster !== null;
    return (show.reel.find(withPoster) ?? show.all.find(withPoster))?.poster ?? null;
  }, [show.reel, show.all]);

  return (
    <div className="flex w-full flex-col pb-6">
      <div className="vs-grain relative overflow-hidden">
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
      <ToolCards cartoonPoster={cartoonPoster} />
      <ShowcaseGallery
        items={show.all}
        categories={show.categories}
        hasStudio={show.hasStudio}
        loading={show.loading}
        onUse={onShowcaseUse}
      />
      <TrustStrip />
    </div>
  );
}

export default memo(StudioHome);

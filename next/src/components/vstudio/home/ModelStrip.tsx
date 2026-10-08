"use client";

import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FiImage, FiVideo } from "react-icons/fi";
import type { ModelJSON, VsKind } from "@/lib/vstudio/types";
import { useVStudio } from "../context";
import { useVStudioModels } from "../hooks/useVStudioModels";
import { openLockedModel } from "../settings/RunSettingsPanel";
import { modelsFor } from "../settings/settingsModel";
import { tx } from "../settings/settingsText";
import { VS_FOCUS, VS_SECTION, VS_SECTION_GAP, VS_SEG_THUMB, VS_SEG_TRACK, vx } from "../ui/skin";
import { useReveal } from "../ui/useReveal";
import { trackHomePick } from "./homePick";
import { HOME_CELLS, HOME_CELL_IN, staggerStyle } from "./tools/cardSkin";
import { focusComposer } from "./tools/dock";
import ModelCard from "./tools/ModelCard";
import { chooseModel } from "./tools/modelStrip";
import SectionHead from "./tools/SectionHead";
import { useOnScreen } from "./tools/useOnScreen";

/** Пропсов нет: модели и выбор берутся из useVStudio(). */
export type ModelStripProps = Record<string, never>;

const KINDS: readonly VsKind[] = ["video", "image"];
const SKELETON = [0, 1, 2, 3];

/**
 * Телефон — лента с прилипанием, от края до края экрана; с 768 px — сетка.
 * Вертикальные поля с обратным отступом — чтобы прокрутка ленты не обрезала
 * тень и золотую кромку выбранной карточки.
 */
const STRIP =
  "vs-noscroll -mx-4 -my-3 flex snap-x snap-mandatory scroll-px-4 gap-3 overflow-x-auto px-4 py-3 sm:-mx-6 sm:scroll-px-6 sm:px-6 md:m-0 md:grid md:grid-cols-2 md:overflow-visible md:p-0 lg:grid-cols-3 xl:grid-cols-4";
const CELL = "w-[240px] shrink-0 snap-start md:w-auto";

/** Переключатель «Видео / Картинки»: дорожка и плашка — общие с панелью запроса и параметрами (ui/skin). */
const TABS = vx("inline-flex shrink-0 rounded-full p-1", VS_SEG_TRACK);
const TAB_ON = vx(VS_SEG_THUMB, "text-vs-accent");

/**
 * «Модели студии» (§2.2): карточки моделей из state.models. Нажатие выбирает
 * модель в панели запроса — теми же функциями, что и панель параметров, —
 * и ставит курсор в поле запроса. Ничего не запускается и не тратится.
 */
export default function ModelStrip() {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const { state, dispatch, actions } = useVStudio();
  const { loading, error } = useVStudioModels();
  const reveal = useReveal<HTMLElement>();
  const [watchSkeleton, skeletonSeen] = useOnScreen<HTMLUListElement>();
  const headId = useId();
  const { composer, models } = state;

  // Вкладка — своя, но за видом в панели запроса она следует: сменили его там
  // («Видео / Картинка») — лента показывает модели того же вида.
  const [tab, setTab] = useState<VsKind>(composer.kind);
  const [seenKind, setSeenKind] = useState<VsKind>(composer.kind);
  if (seenKind !== composer.kind) {
    setSeenKind(composer.kind);
    setTab(composer.kind);
  }

  const counts = { video: modelsFor(models, "video").length, image: modelsFor(models, "image").length };
  // У вида нет моделей — его вкладка выключена, показываем другой.
  const shown: VsKind = counts[tab] > 0 ? tab : tab === "video" ? "image" : "video";
  const list = modelsFor(models, shown);
  const current = shown === composer.kind ? composer.model : null;

  // Обработчик отдаём карточкам неизменным (они не перерисовываются на каждую
  // букву в запросе), а свежее состояние читаем отсюда.
  const live = useRef({ composer, models, dispatch, actions, shown });
  useLayoutEffect(() => {
    live.current = { composer, models, dispatch, actions, shown };
  });

  const strip = useRef<HTMLUListElement | null>(null);
  /** Модель выбрали нажатием в самой ленте: карточка и так на виду, ленту не двигаем. */
  const pickedHere = useRef(false);

  // На телефоне выбранная модель может стоять за краем ленты — подвозим её к
  // началу. Двигаем только саму ленту: страница остаётся на месте.
  useEffect(() => {
    if (pickedHere.current) {
      pickedHere.current = false;
      return;
    }
    const box = strip.current;
    if (!box || box.scrollWidth <= box.clientWidth) return;
    const card = box.querySelector<HTMLElement>('[aria-pressed="true"]');
    if (!card) {
      box.scrollLeft = 0;
      return;
    }
    const gutter = parseFloat(getComputedStyle(box).paddingLeft) || 0;
    box.scrollLeft += card.getBoundingClientRect().left - box.getBoundingClientRect().left - gutter;
  }, [shown, current, list.length]);

  const pick = useCallback((model: ModelJSON) => {
    const cur = live.current;
    trackHomePick("model", model.id);
    if (model.locked) {
      // Тот же путь, что у замка в панели параметров: гостю — вход, остальным — пэйволл.
      openLockedModel(cur.dispatch, { requireAuth: cur.actions.requireAuth });
      return;
    }
    pickedHere.current = cur.shown !== cur.composer.kind || model.id !== cur.composer.model;
    chooseModel(cur.dispatch, cur.models, cur.composer, cur.shown, model.id);
    focusComposer();
  }, []);

  // Список не пришёл и не придёт (ошибка сети) — секции нет; пришёл пустой — тоже.
  if (!models && error && !loading) return null;
  if (models && list.length === 0) return null;

  return (
    <section ref={reveal} aria-labelledby={headId} className={vx(VS_SECTION, VS_SECTION_GAP, "vs-reveal", HOME_CELLS)}>
      <SectionHead
        id={headId}
        title={t("home.models.title", { defaultValue: "Модели студии" })}
        sub={t("home.models.sub", { defaultValue: "Выберите модель — параметры и цена подстроятся под неё" })}
      >
        {models && (
          <div
            role="group"
            aria-label={t("home.models.tabs", { defaultValue: "Какие модели показать" })}
            className={TABS}
          >
            {KINDS.map((kind) => {
              const Icon = kind === "video" ? FiVideo : FiImage;
              const on = kind === shown;
              return (
                <button
                  key={kind}
                  type="button"
                  aria-pressed={on}
                  disabled={counts[kind] === 0}
                  onClick={() => setTab(kind)}
                  className={vx(
                    "inline-flex min-h-11 cursor-pointer items-center gap-1.5 rounded-full px-4 text-[13px] font-medium tabular-nums transition-colors disabled:cursor-not-allowed disabled:opacity-45 md:min-h-9",
                    on ? TAB_ON : "text-muted enabled:hover:text-foreground",
                    VS_FOCUS,
                  )}
                >
                  <Icon className="size-4 shrink-0" aria-hidden />
                  {kind === "video"
                    ? t("home.models.tabVideo", { defaultValue: "Видео · {{n}}", n: counts.video })
                    : t("home.models.tabImage", { defaultValue: "Картинки · {{n}}", n: counts.image })}
                </button>
              );
            })}
          </div>
        )}
      </SectionHead>

      <div className="mt-5 sm:mt-6">
        {models ? (
          <ul ref={strip} className={STRIP}>
            {list.map((model, i) => (
              <li key={model.id} className={vx(CELL, HOME_CELL_IN)} style={staggerStyle(i)}>
                <ModelCard model={model} kind={shown} selected={model.id === current} onPick={pick} />
              </li>
            ))}
          </ul>
        ) : (
          <ul ref={watchSkeleton} className={STRIP} aria-busy="true">
            <li className="sr-only">{tx(t, "settings.modelsLoading")}</li>
            {SKELETON.map((k) => (
              <li
                key={k}
                aria-hidden
                className={vx(CELL, "h-[218px] rounded-2xl", skeletonSeen ? "vs-film" : "bg-surface-2")}
              />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

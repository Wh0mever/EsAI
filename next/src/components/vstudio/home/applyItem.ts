/**
 * «Снять похожее»: что работа из витрины меняет в панели запроса (§3.3).
 *
 * Берём у работы всё, что у нас можно повторить: модель (если она есть в
 * списке и не под замком), параметры — только те, что модель умеет, и текст
 * запроса — только в пустую панель. Ничего не запускается и не тратится.
 *
 * Выбор модели идёт теми же функциями, что и в панели параметров
 * (selectKind / selectModel): память «последняя модель вида» и недонабранный
 * seed ведут себя одинаково, откуда бы человек ни выбрал модель.
 *
 * Модуль без React и разметки — его проверяет node-тест home.test.mjs на
 * настоящем редьюсере.
 */
import type { Dispatch } from "react";
import { isEmptyDoc } from "@/lib/vstudio/promptDoc";
import type { ModelJSON, ShotParams, VsAction, VsKind, VsState } from "@/lib/vstudio/types";
import { exampleDoc } from "../feed/examples";
import { exampleAspect } from "../feed/feedLogic";
import { AUTO, findModel, modelsFor } from "../settings/settingsModel";
import { selectKind, selectModel } from "../settings/useRunSettingsSync";
import type { ReelItem } from "./showreelData";

export type ApplyOutcome =
  /** Модель работы под замком: ничего не меняли, дальше — вход или пэйволл. */
  | "locked"
  /** Текст работы лёг в пустой запрос (вместе с моделью и параметрами, если подошли). */
  | "filled"
  /** Модель или параметры выбраны, а свой текст человека не тронут — об этом стоит сказать. */
  | "kept"
  /** Выбраны модель или параметры; текста у работы нет. */
  | "set"
  /** Применить было нечего. */
  | "none";

/**
 * Из параметров чужой работы берём только то, что умеет модель: неподходящее
 * значение вернулось бы от сервера ошибкой invalid_param вместо цены.
 */
export function supportedParams(model: ModelJSON, kind: VsKind, params: ReelItem["params"]): Partial<ShotParams> {
  const patch: Partial<ShotParams> = {};
  if (!params) return patch;
  const caps = model.caps;
  const aspect = params.aspect_ratio;
  if (aspect && (aspect === AUTO || (caps.aspect_ratios || []).includes(aspect))) patch.aspect_ratio = aspect;
  if (kind !== "video") return patch;
  if (typeof params.duration === "number" && (caps.durations || []).includes(params.duration)) {
    patch.duration = params.duration;
  }
  const wanted = params.resolution?.toLowerCase();
  const resolution = wanted ? (caps.resolutions || []).find((r) => r.toLowerCase() === wanted) : undefined;
  if (resolution) patch.resolution = resolution;
  return patch;
}

export function applyReelItem(
  item: ReelItem,
  state: Pick<VsState, "composer" | "models">,
  dispatch: Dispatch<VsAction>,
): ApplyOutcome {
  const { composer, models } = state;
  const current = { kind: composer.kind, model: composer.model, params: composer.params };

  const wanted = findModel(models, item.modelId, item.kind);
  if (wanted?.locked) return "locked";

  let patch: Partial<ShotParams> = {};
  let changed = false;
  if (wanted) {
    if (item.kind !== current.kind) selectKind(dispatch, models, current, item.kind);
    // После смены вида модель в сторе уже другая — нужную выбираем как с чистого листа.
    const base =
      item.kind === current.kind
        ? current
        : { kind: item.kind, model: null, params: { aspect_ratio: current.params.aspect_ratio } };
    selectModel(dispatch, models, base, wanted.id);
    patch = supportedParams(wanted, item.kind, item.params);
    changed = true;
  } else if (item.kind === current.kind) {
    // Модели этой работы у нас уже нет — остаёмся на выбранной.
    const mine = findModel(models, current.model, current.kind);
    if (mine) patch = supportedParams(mine, item.kind, item.params);
  } else if (modelsFor(models, item.kind).length > 0) {
    // Другой вид без известной модели: её выберет стор, поэтому пропорцию
    // берём, только если её умеют все модели вида (как у примеров).
    selectKind(dispatch, models, current, item.kind);
    const aspect = exampleAspect(item.params?.aspect_ratio, models, item.kind, null);
    if (aspect) patch = { aspect_ratio: aspect };
    changed = true;
  }
  if (Object.keys(patch).length > 0) {
    dispatch({ type: "composer/params", params: patch });
    changed = true;
  }

  if (!item.prompt) return changed ? "set" : "none";
  // Свой текст человека дороже чужого примера: не затираем.
  if (!isEmptyDoc(composer.doc)) return changed ? "kept" : "none";
  dispatch({ type: "composer/doc", doc: exampleDoc(item.prompt) });
  return "filled";
}

/** Что сказать человеку после нажатия; null — панель запроса говорит сама за себя. */
export type ApplyNotice =
  /** Модели работы в студии нет: кнопка обещала её, а осталась выбранная. */
  | "gone"
  /** Модель и параметры выбраны, свой текст не тронут. */
  | "kept"
  | null;

/**
 * Работа висит в витрине и после того, как её модель убрали из студии. Тогда
 * нажатие модель не меняет — иногда не меняет вообще ничего, — и промолчать
 * значило бы оставить человека гадать, сработала ли кнопка. А «модель
 * выбрана» было бы неправдой: цена на кнопке «Создать» осталась прежней.
 * Если текст работы лёг в запрос, нажатие и так видно. Пока список моделей
 * не пришёл, судить о пропаже рано.
 */
export function applyNotice(item: ReelItem, models: VsState["models"], outcome: ApplyOutcome): ApplyNotice {
  if (outcome === "locked" || outcome === "filled") return null;
  if (models && !findModel(models, item.modelId, item.kind)) return "gone";
  return outcome === "kept" ? "kept" : null;
}

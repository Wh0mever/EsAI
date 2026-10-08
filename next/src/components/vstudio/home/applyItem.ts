/**
 * «Снять похожее»: что работа из карусели меняет в панели запроса (§3.3).
 *
 * Берём у работы всё, что у нас можно повторить: модель (если она есть в
 * списке и не под замком), параметры — только те, что модель умеет, и текст
 * запроса — в пустую панель или поверх нетронутой заготовки (текст прошлого
 * примера своим текстом человека не считается). Ничего не запускается и не
 * тратится.
 *
 * Замок на модели пример не останавливает: человек остаётся на своей модели и
 * всё равно получает текст и параметры работы, а о платной модели узнаёт из
 * подсказки. Пэйволл по нажатию на пример не открывается.
 *
 * Выбор модели идёт теми же функциями, что и в панели параметров
 * (selectKind / selectModel): память «последняя модель вида» и недонабранный
 * seed ведут себя одинаково, откуда бы человек ни выбрал модель.
 *
 * Модуль без React и разметки — его проверяет node-тест home.test.mjs на
 * настоящем редьюсере.
 */
import type { Dispatch } from "react";
import type { ComposerState, ModelJSON, ShotParams, VsAction, VsKind, VsState } from "@/lib/vstudio/types";
import { exampleDoc, starterReplaceable } from "../feed/examples";
import { exampleAspect } from "../feed/feedLogic";
import { AUTO, countInputs, findModel, modelsFor } from "../settings/settingsModel";
import { selectKind, selectModel } from "../settings/useRunSettingsSync";
import type { ReelItem } from "./showreelData";

export type ApplyOutcome =
  /** Текст работы лёг в пустой запрос (вместе с моделью и параметрами, если подошли). */
  | "filled"
  /** Модель или параметры выбраны, а свой текст человека не тронут — об этом стоит сказать. */
  | "kept"
  /** Выбраны модель или параметры; текста у работы нет. */
  | "set"
  /** Применить было нечего. */
  | "none"
  /**
   * Модель работы под замком, её не выбрали; текст работы лёг в запрос. Модель в
   * панели — прежняя, а если в ней стоял другой вид — та, что подобрал стор.
   */
  | "filled_locked"
  /** Модель работы под замком, её не выбрали; текст не подставляли: его нет или в панели свой. */
  | "locked";

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

/**
 * replaceable — заготовки первого экрана (starters.homeStarters): запрос, в
 * котором одна из них стоит нетронутой, пример заменяет. Без списка заменяется
 * только пустой запрос.
 */
export function applyReelItem(
  item: ReelItem,
  state: Pick<VsState, "composer" | "models">,
  dispatch: Dispatch<VsAction>,
  replaceable: readonly string[] = [],
): ApplyOutcome {
  const { composer, models } = state;
  const current = { kind: composer.kind, model: composer.model, params: composer.params };

  const found = findModel(models, item.modelId, item.kind);
  const locked = found?.locked === true;
  // Модель под замком выбрать нельзя — дальше с ней как с моделью, которой в студии нет.
  const wanted = locked ? null : found;

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
    // Модели этой работы у нас нет или она под замком — остаёмся на выбранной.
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

  if (!item.prompt) return locked ? "locked" : changed ? "set" : "none";
  // Свой текст человека дороже чужого примера: не затираем. Текст прошлого примера или
  // сценария — не свой: иначе в запросе остался бы один ролик, а модель и цена — другого.
  if (!starterReplaceable(composer.doc, replaceable)) return locked ? "locked" : changed ? "kept" : "none";
  dispatch({ type: "composer/doc", doc: exampleDoc(item.prompt) });
  return locked ? "filled_locked" : "filled";
}

/** Что сказать человеку после нажатия; null — панель запроса говорит сама за себя. */
export type ApplyNotice =
  /** Модели работы в студии нет: кнопка обещала её, а осталась выбранная. */
  | "gone"
  /** Модель и параметры выбраны, свой текст не тронут. */
  | "kept"
  /** Модель работы на платном тарифе — осталась своя; текст работы подставлен. */
  | "locked_filled"
  /** Модель работы на платном тарифе — остались и своя модель, и свой текст. */
  | "locked_kept"
  /** Модель работы на платном тарифе — осталась своя; текста у работы нет. */
  | "locked"
  /** Модель работы на платном тарифе, а в панели стоял другой вид: он сменился, модель подобрал стор. */
  | "locked_switched"
  /** То же, и свой текст человека остался. */
  | "locked_switched_kept"
  | null;

/**
 * Работа висит в карусели и после того, как её модель убрали из студии или
 * закрыли тарифом. Тогда нажатие модель не меняет — иногда не меняет вообще
 * ничего, — и промолчать значило бы оставить человека гадать, сработала ли
 * кнопка. А «модель выбрана» было бы неправдой: цена на кнопке «Создать»
 * осталась прежней. О платной модели говорим всегда: её название стоит на
 * кадре, а в панели запроса осталась другая. О пропавшей — только если текст
 * работы не лёг в запрос: иначе нажатие и так видно. Пока список моделей не
 * пришёл, судить о пропаже рано.
 *
 * kindBefore — вид в панели до нажатия. Если он был другим (картинка, а пример
 * — ролик), вид переключился и модель с ценой подобрал стор: «модель осталась
 * ваша» там неправда, говорим о переключении. Модель под замком в списке есть,
 * значит, и переключиться было на что.
 */
export function applyNotice(
  item: ReelItem,
  models: VsState["models"],
  outcome: ApplyOutcome,
  kindBefore: VsKind = item.kind,
): ApplyNotice {
  if (outcome === "filled_locked" || outcome === "locked") {
    // Запрос у работы был, но не лёг — значит, в панели свой текст.
    const ownText = outcome === "locked" && item.prompt !== null;
    if (item.kind !== kindBefore) return ownText ? "locked_switched_kept" : "locked_switched";
    if (outcome === "filled_locked") return "locked_filled";
    return ownText ? "locked_kept" : "locked";
  }
  if (outcome === "filled") return null;
  if (models && !findModel(models, item.modelId, item.kind)) return "gone";
  return outcome === "kept" ? "kept" : null;
}

/** Название модели работы для подсказки: как в списке моделей студии, иначе — как подписана работа. */
export function reelModelName(item: ReelItem, models: VsState["models"]): string {
  return findModel(models, item.modelId, item.kind)?.name || item.subtitle;
}

/**
 * Работа снята по фото, а в запросе человека фото нет: стоит попросить добавить
 * своё и показать, куда. Без фото «похожее» не выйдет, как ни повторяй текст;
 * а если фото в запросе уже есть — просить нечего.
 */
export function wantsPhoto(item: ReelItem, composer: Pick<ComposerState, "tray" | "frames">): boolean {
  if (!item.needsPhoto) return false;
  const inputs = countInputs(composer.tray, composer.frames);
  return inputs.refs === 0 && !inputs.first && !inputs.last;
}

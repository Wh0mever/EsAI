/**
 * Мультстудия, нижний док «Модель / Качество / Длительность / Формат»: чистая
 * логика без React и сети.
 *
 * Здесь всё, что студия решает сама: что показать в доке, как «примагнитить»
 * качество и длительность к новой модели (то же правило, что на сервере,
 * core/cartoon/pricing.clamp_*), какую цену написать у строки ленты гостя и у
 * карточки библиотеки, пока сервер не пересчитал витрину, и сколько выходит
 * «Итого». Цену съёмки у вошедшего считает только сервер (render_credits);
 * отсюда — лишь подсказки из таблиц GET cartoon/models/ (price.by_aspect).
 * Контракт: vstudio2-notes/pricing/CONTRACT_C.md.
 *
 * Модуль чистый: его проверяет node-тест dockLogic.test.mjs.
 */
import type { ModelJSON } from "@/lib/vstudio/types";
import { priceHint } from "@/components/vstudio/settings/settingsModel";

/** Форматы мультстудии (STUDIO_ASPECTS на сервере). */
export const STUDIO_ASPECTS = ["16:9", "9:16", "1:1"] as const;
export const DEFAULT_ASPECT = "16:9";
/** Предел длительности на сервере (pricing.MAX_DURATION). */
export const MAX_DURATION = 60;
/** Длительность по умолчанию в коде сервера (CODE_DEFAULT_DURATION). */
const CODE_DEFAULT_DURATION = 5;

/** Модель дока: ModelJSON видеостудии + короткое имя, цена кадра и «цены нет». */
export type CartoonModel = ModelJSON & {
  /** «Seedance Mini» — подпись кнопки дока. */
  short?: string;
  /** Цена кадра «типичной сцены»: с готовым кадром из запаса платится только видео. */
  frame_credits?: number | null;
  /** markup без себестоимости: цены нет, «Снять» выключено. */
  price_unavailable?: boolean;
};

export type DockDefaults = {
  video_model: string | null;
  resolution: string | null;
  duration: number | null;
  /** settings — настройки админки; preset — откат на «типичную сцену». */
  source: string;
};

/** GET cartoon/models/. */
export type CartoonModels = {
  aspect_ratio: string;
  aspects: string[];
  models: CartoonModel[];
  defaults: DockDefaults;
  frame_credits: number | null;
  pricing_mode?: string;
};

/** Настройки дока целиком: так их и шлём серверу (все три разом). */
export type DockSettings = { video_model: string; resolution: string; duration: number };

/** Чем снимется сцена (scene.config) или снята (scene.shot). */
export type SceneConfig = {
  video_model: string;
  model_name: string;
  resolution: string;
  duration: number;
  aspect_ratio: string;
};
export type SceneShot = SceneConfig & { credits_planned?: number | null };

/** project.effective: что показывает док мультфильма. */
export type DockEffective = SceneConfig & { model_available: boolean };

/** Что сервер подогнал сам ({field, from, to, message}, у длительности сцены — ещё scene). */
export type AdjustedNote = {
  field: string;
  from: string | number;
  to: string | number;
  message?: string;
  scene?: number;
};

/* ------------------------------------------------------------------ */
/* Тексты                                                              */
/* ------------------------------------------------------------------ */

/**
 * Русские тексты дока — defaultValue ключей common:studio_ui.dock_* и
 * studio_ui.scene_*. Один источник для компонентов и тестов; переводы — во
 * фрагментах vstudio2-notes/i18n/C_F1.json и C_FIX.json (ru там байт в байт как здесь).
 */
export const DOCK_RU = {
  "studio_ui.dock_label": "Настройки съёмки",
  "studio_ui.dock_model": "Модель",
  "studio_ui.dock_quality": "Качество",
  "studio_ui.dock_duration": "Длительность",
  "studio_ui.dock_seconds": "{{n}} с",
  "studio_ui.dock_total": "Итого",
  "studio_ui.dock_total_title": "Сцен к съёмке: {{count}}",
  "studio_ui.dock_total_line": "Итого к съёмке: {{credits}} кр · сцен: {{count}}",
  "studio_ui.dock_total_line_unavailable": "Сцен к съёмке: {{count}} · цена сейчас недоступна",
  "studio_ui.dock_duration_hint": "Для сцен без своей длительности. Свою длительность сцены можно выбрать в её карточке.",
  "studio_ui.dock_format_hint": "Один формат на весь мультфильм — так сцены склеятся ровно.",
  "studio_ui.dock_clamp_resolution": "{{model}} не снимает в {{from}} — выбрано {{to}}",
  "studio_ui.dock_clamp_duration": "{{model}} не снимает {{from}} с — выбрано {{to}} с",
  "studio_ui.dock_clamp_scene": "Сцена {{n}}: {{from}} с не снять — выбрано {{to}} с",
  "studio_ui.dock_model_off": "Модель этого мультфильма сейчас выключена — сцены снимутся моделью из библиотеки. Выберите другую.",
  "studio_ui.dock_models_error": "Модели не загрузились",
  "studio_ui.dock_retry": "Повторить",
  "studio_ui.dock_hide_notice": "Скрыть сообщение",
  "studio_ui.dock_save_failed": "Не удалось сохранить настройки — попробуйте ещё раз",
  "studio_ui.scene_duration": "Длительность сцены",
  "studio_ui.scene_duration_default": "{{n}} с · по умолчанию",
  "studio_ui.scene_duration_default_plain": "По умолчанию",
  "studio_ui.scene_shot_working": "Снимается: {{config}}",
  "studio_ui.scene_shot_ready": "Снято: {{config}}",
  "studio_ui.scene_reshoot_duration":
    "Сцена уже снята на {{from}} с. Чтобы она стала {{to}} с, её нужно переснять — это новая съёмка за {{credits}} кр, нынешний ролик заменится. Переснять?",
  "studio_ui.scene_reshoot_duration_cfg":
    "Сцена снята на {{from}} с ({{was}}). Чтобы она стала {{to}} с, её нужно переснять — новая съёмка: {{config}} за {{credits}} кр, нынешний ролик заменится. Переснять?",
  "studio_ui.scene_reshoot_duration_fmt":
    "Сцена снята на {{from}} с ({{was}}, формат {{was_aspect}}). Чтобы она стала {{to}} с, её нужно переснять — новая съёмка: {{config}} в формате {{aspect}} за {{credits}} кр, нынешний ролик заменится. Переснять?",
  "studio_ui.reshoot_confirm_cfg":
    "Переснять сцену заново ({{config}})? Спишется {{credits}} кр., нынешний ролик заменится новым.",
  "studio_ui.scene_price_changed": "Цена изменилась: теперь {{credits}} кр. Проверьте и нажмите «Снять» ещё раз.",
  "studio_ui.scene_price_changed_retry": "Цена изменилась: теперь {{credits}} кр. Проверьте и нажмите ещё раз.",
  "studio_ui.scene_already_shot": "Сцена уже снята — переснять можно кнопкой «Переснять»",
  "studio_ui.reshoot_btn": "Переснять · {{credits}} кр",
  "studio_ui.reshoot_btn_plain": "Переснять",
  "studio_ui.dock_saving": "Сохраняем настройки…",
  "studio_ui.dock_err_model": "Эта модель недоступна в мультстудии — выберите другую",
  "studio_ui.dock_err_value": "Эта модель так не снимает — выберите другое значение",
  "studio_ui.dock_err_caps": "Не удалось проверить возможности модели — попробуйте через минуту",
  "studio_ui.scene_err_busy": "Сцена уже снимается — подождите, пока съёмка закончится",
  "studio_ui.scene_err_price": "Цена модели сейчас недоступна — попробуйте позже",
  "studio_ui.scene_err_quote": "Не удалось проверить цену — обновите страницу и попробуйте снова",
  "studio_ui.scene_err_stale": "Сцена на странице устарела — обновите страницу и попробуйте снова",
  "studio_ui.scene_err_changed": "Сцену уже переснимали — проверьте её и нажмите ещё раз",
  "studio_ui.scene_save_failed": "Не удалось сохранить — попробуйте ещё раз",
  "studio_ui.err_tryon": "Не удалось примерить героя",
  "studio_ui.retry_failed_short": "Повторить",
} as const;

export type DockTextKey = keyof typeof DOCK_RU;

/** Сообщение дока: ключ перевода и подстановки (текст собирает компонент). */
export type DockNotice = { key: DockTextKey; params: Record<string, string | number> };

/** Подставить {{x}} в русский шаблон — для тестов и мест без i18next. */
export function fillDock(key: DockTextKey, params?: Record<string, string | number>): string {
  return DOCK_RU[key].replace(/\{\{\s*(\w+)\s*\}\}/g, (_, name: string) =>
    params && name in params ? String(params[name]) : "",
  );
}

/* ------------------------------------------------------------------ */
/* «Примагничивание» — то же правило, что на сервере                   */
/* ------------------------------------------------------------------ */

const RES_HEIGHT: Record<string, number> = { "1k": 1080, "2k": 1440, "4k": 2160 };

/** Высота кадра качества: «720p» → 720, «4K» → 2160; непонятное — 0. */
export function resHeight(resolution: string | null | undefined): number {
  const value = String(resolution ?? "").trim().toLowerCase();
  if (value in RES_HEIGHT) return RES_HEIGHT[value];
  const digits = value.endsWith("p") ? value.slice(0, -1) : value;
  return /^\d+$/.test(digits) ? Number(digits) : 0;
}

/** Ближайшая длительность, которую модель снимает; при равенстве — короче (дешевле). */
export function clampDuration(durations: readonly number[], want: number | null | undefined): number {
  const target = Math.max(1, Math.trunc(Number(want) || CODE_DEFAULT_DURATION));
  if (!durations.length) return target;
  let best = durations[0];
  for (const d of durations) {
    const gap = Math.abs(d - target);
    const bestGap = Math.abs(best - target);
    if (gap < bestGap || (gap === bestGap && d < best)) best = d;
  }
  return best;
}

/** То же качество без учёта регистра или ближайшее по высоте кадра; при равенстве — ниже. */
export function clampResolution(resolutions: readonly string[], want: string | null | undefined): string {
  const value = String(want || "720p");
  if (!resolutions.length) return value;
  const exact = resolutions.find((r) => r.toLowerCase() === value.toLowerCase());
  if (exact) return exact;
  const target = resHeight(value) || 720;
  let best = resolutions[0];
  for (const r of resolutions) {
    const gap = Math.abs(resHeight(r) - target);
    const bestGap = Math.abs(resHeight(best) - target);
    if (gap < bestGap || (gap === bestGap && resHeight(r) < resHeight(best))) best = r;
  }
  return best;
}

/** Качество из списка модели без учёта регистра («4k» → «4K») или null. */
export function findResolution(resolutions: readonly string[], want: string | null | undefined): string | null {
  const value = String(want ?? "").trim().toLowerCase();
  if (!value) return null;
  return resolutions.find((r) => r.toLowerCase() === value) ?? null;
}

/* ------------------------------------------------------------------ */
/* Модели                                                              */
/* ------------------------------------------------------------------ */

export function findModel(models: readonly CartoonModel[] | null | undefined, id: string | null | undefined): CartoonModel | null {
  if (!models || !id) return null;
  return models.find((m) => m.id === id) ?? null;
}

/** Подпись кнопки модели: «Seedance Mini». */
export function modelLabel(model: Pick<CartoonModel, "short" | "name"> | null | undefined): string {
  return (model?.short || model?.name || "").trim();
}

/** На телефоне в кнопке — без имени семейства: в доке только Seedance («Mini», «2.0»). */
export function compactModelLabel(label: string): string {
  const short = label.replace(/^seedance\s+/i, "").trim();
  return short || label;
}

/**
 * Модели для пикеров видеостудии в формате мультфильма: price.table — цены
 * этого формата, «от N кр» — самая дешёвая сцена в нём (квадрат дешевле 16:9).
 */
export function modelsForAspect(models: readonly CartoonModel[], aspect: string): CartoonModel[] {
  return models.map((m) => {
    const table = m.price?.by_aspect?.[aspect];
    if (!m.price || !table) return m;
    const cells = Object.values(table).flatMap((row) => Object.values(row)).filter((v) => Number.isFinite(v));
    return {
      ...m,
      price: { ...m.price, table },
      price_from: cells.length ? Math.min(...cells) : m.price_from,
    };
  });
}

/** Цена кадра модели (или общая из ответа): её не платят, когда кадр уже есть. */
export function frameCreditsOf(model: CartoonModel | null | undefined, fallback?: number | null): number {
  const v = model?.frame_credits ?? fallback;
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

/**
 * Цена сцены из таблицы модели: кадр + видео; с готовым кадром — только видео.
 * null — модель не умеет такое качество/длительность или цены нет.
 */
export function tablePrice(
  model: CartoonModel | null | undefined,
  at: { resolution: string | null | undefined; duration: number | null | undefined; aspect: string; keyframeReady?: boolean },
  frameFallback?: number | null,
): number | null {
  if (!model || model.price_unavailable) return null;
  const cell = priceHint(model, { duration: at.duration ?? null, resolution: at.resolution ?? null, aspect: at.aspect });
  if (cell == null) return null;
  return at.keyframeReady ? Math.max(0, cell - frameCreditsOf(model, frameFallback)) : cell;
}

/* ------------------------------------------------------------------ */
/* Значения дока                                                       */
/* ------------------------------------------------------------------ */

/** Полная тройка настроек или null (чего-то нет). */
export function completeDock(raw: {
  video_model?: string | null;
  resolution?: string | null;
  duration?: number | null;
} | null | undefined): DockSettings | null {
  if (!raw) return null;
  const { video_model, resolution, duration } = raw;
  if (!video_model || !resolution || !duration) return null;
  return { video_model, resolution, duration };
}

/**
 * Настройки, которые получит новый мультфильм, если человек док не трогал.
 * source=preset — сцены снимутся как в библиотеке: явных настроек нет (null).
 */
export function explicitDefaults(models: CartoonModels | null | undefined): DockSettings | null {
  if (!models || models.defaults?.source !== "settings") return null;
  return completeDock(models.defaults);
}

/** Что показать в доке, когда своих настроек нет: значения по умолчанию или первая модель. */
export function displayDefaults(models: CartoonModels | null | undefined): DockSettings | null {
  if (!models) return null;
  const own = completeDock(models.defaults);
  if (own) return own;
  const first = models.models[0];
  if (!first) return null;
  return {
    video_model: first.id,
    resolution: clampResolution(first.caps.resolutions || [], first.defaults?.resolution),
    duration: clampDuration(first.caps.durations || [], first.defaults?.duration),
  };
}

export type DockChange = { settings: DockSettings; notices: DockNotice[] };

/**
 * Сменить модель: качество и длительность остаются, если новая модель их
 * умеет; иначе — ближайшие, и об этом короткое сообщение (решение 4).
 */
export function switchModel(
  models: readonly CartoonModel[],
  current: DockSettings | null,
  nextId: string,
): DockChange | null {
  const model = findModel(models, nextId);
  if (!model) return null;
  const resolutions = model.caps.resolutions || [];
  const durations = model.caps.durations || [];
  const name = modelLabel(model);
  const notices: DockNotice[] = [];

  let resolution: string;
  const wantRes = current?.resolution;
  const keptRes = wantRes ? findResolution(resolutions, wantRes) : null;
  if (keptRes) resolution = keptRes;
  else if (wantRes) {
    resolution = clampResolution(resolutions, wantRes);
    if (resolution !== wantRes) {
      notices.push({ key: "studio_ui.dock_clamp_resolution", params: { model: name, from: wantRes, to: resolution } });
    }
  } else resolution = clampResolution(resolutions, model.defaults?.resolution);

  let duration: number;
  const wantDur = current?.duration;
  if (wantDur && durations.includes(wantDur)) duration = wantDur;
  else if (wantDur) {
    duration = clampDuration(durations, wantDur);
    if (duration !== wantDur) {
      notices.push({ key: "studio_ui.dock_clamp_duration", params: { model: name, from: wantDur, to: duration } });
    }
  } else duration = clampDuration(durations, model.defaults?.duration);

  return { settings: { video_model: model.id, resolution, duration }, notices };
}

/** Новое качество: только то, что модель умеет (иначе null — ничего не меняем). */
export function withResolution(
  models: readonly CartoonModel[],
  current: DockSettings,
  resolution: string,
): DockSettings | null {
  const model = findModel(models, current.video_model);
  const found = model ? findResolution(model.caps.resolutions || [], resolution) : null;
  return found ? { ...current, resolution: found } : null;
}

/** Новая длительность: только то, что модель умеет (иначе null). */
export function withDuration(models: readonly CartoonModel[], current: DockSettings, duration: number): DockSettings | null {
  const model = findModel(models, current.video_model);
  return model && (model.caps.durations || []).includes(duration) ? { ...current, duration } : null;
}

/**
 * Настройки из черновика под нынешний список моделей: модель выключили — null
 * (будут значения по умолчанию), качество и длительность — ближайшие. Список
 * ещё не пришёл — как есть: сервер перенос проверит сам (мягко).
 */
export function sanitizeDock(
  dock: DockSettings | null | undefined,
  models: readonly CartoonModel[] | null | undefined,
): DockSettings | null {
  if (!dock) return null;
  if (!models) return dock;
  const model = findModel(models, dock.video_model);
  if (!model) return null;
  return {
    video_model: model.id,
    resolution: clampResolution(model.caps.resolutions || [], dock.resolution),
    duration: clampDuration(model.caps.durations || [], dock.duration),
  };
}

/** Тело POST projects/ (новый мультфильм): все три разом (CONTRACT_C §5). */
export function dockBody(settings: DockSettings): DockSettings {
  return { video_model: settings.video_model, resolution: settings.resolution, duration: settings.duration };
}

/** Что человек тронул в доке. */
export type DockField = "video_model" | "resolution" | "duration";

/**
 * Тело PATCH projects/<id>/ после касания дока: только то, что человек менял.
 *
 * У мультфильма без своих настроек (старый, или снятый «как в библиотеке») док
 * показывает настройки «типичной сцены». Раньше любое касание слало все три — и
 * длительность «типичной сцены» молча становилась длительностью каждой сцены без
 * своей (4 с и 15 с превращались в 5 с). Теперь:
 *  - поле, которое тронули, — всегда;
 *  - модель — ещё и когда своей у мультфильма нет: качество и длительность без
 *    модели не имеют смысла (сервер взял бы ту же модель «типичной сцены» сам);
 *  - остальные — только если они у мультфильма уже свои: тогда это подогнанные к
 *    новой модели значения (сообщение об этом показал switchModel). Пустые остаются
 *    пустыми: сцены по-прежнему снимутся со своими длительностями из библиотеки.
 */
export function dockPatch(
  saved: { video_model?: string | null; resolution?: string | null; duration?: number | null } | null | undefined,
  next: DockSettings,
  field: DockField,
): Partial<DockSettings> {
  const body: Partial<DockSettings> = {};
  if (field === "video_model" || !saved?.video_model) body.video_model = next.video_model;
  if (field === "resolution" || saved?.resolution) body.resolution = next.resolution;
  if (field === "duration" || saved?.duration) body.duration = next.duration;
  return body;
}

export function sameDock(a: DockSettings | null | undefined, b: DockSettings | null | undefined): boolean {
  if (!a || !b) return !a && !b;
  return a.video_model === b.video_model && a.resolution === b.resolution && a.duration === b.duration;
}

/**
 * Свои длительности сцен черновика гостя под новую модель — как сервер делает
 * это у мультфильма (_apply_dock): чего модель не умеет — ближайшее, с сообщением.
 */
export function clampSceneDurations<T extends { duration?: number }>(
  scenes: readonly T[],
  durations: readonly number[],
): { scenes: T[]; notices: DockNotice[] } {
  const notices: DockNotice[] = [];
  if (!durations.length) return { scenes: [...scenes], notices };
  const out = scenes.map((s, i) => {
    if (!s.duration || durations.includes(s.duration)) return s;
    const fixed = clampDuration(durations, s.duration);
    notices.push({ key: "studio_ui.dock_clamp_scene", params: { n: i + 1, from: s.duration, to: fixed } });
    return { ...s, duration: fixed };
  });
  return { scenes: out, notices };
}

/**
 * Что сервер подогнал сам (adjusted) — сообщениями дока на языке человека.
 * Номер сцены — её место в ленте (sceneIndex), как в тексте сервера.
 */
export function adjustedNotices(
  adjusted: readonly AdjustedNote[] | null | undefined,
  modelName: string,
  sceneIndex: (sceneId: number) => number | null,
): DockNotice[] {
  const out: DockNotice[] = [];
  for (const a of adjusted || []) {
    if (!a || typeof a !== "object") continue;
    if (a.field === "duration" && typeof a.scene === "number") {
      const at = sceneIndex(a.scene);
      out.push({ key: "studio_ui.dock_clamp_scene", params: { n: at == null ? "?" : at + 1, from: a.from, to: a.to } });
    } else if (a.field === "resolution") {
      out.push({ key: "studio_ui.dock_clamp_resolution", params: { model: modelName, from: a.from, to: a.to } });
    } else if (a.field === "duration") {
      out.push({ key: "studio_ui.dock_clamp_duration", params: { model: modelName, from: a.from, to: a.to } });
    }
  }
  return out;
}

/* ------------------------------------------------------------------ */
/* Витрина: запрос и цена карточки                                     */
/* ------------------------------------------------------------------ */

/**
 * Как спросить цены витрины: мультфильм (?project=, настройки сервер возьмёт
 * сам), явные настройки (гость, новый мультфильм) или по пресетам, как раньше.
 * key — что посчитано: сменился — витрину пора перезапросить.
 */
export function presetsQuery(args: {
  lang: string;
  aspect: string;
  projectId?: number | null;
  /** Сохранённые настройки мультфильма — только для ключа (сервер их знает сам). */
  saved?: { video_model: string | null; resolution: string | null; duration: number | null } | null;
  /** Явные настройки без мультфильма. */
  explicit?: DockSettings | null;
}): { key: string; query: string } {
  const params = new URLSearchParams({ lang: args.lang, aspect_ratio: args.aspect });
  let key: string;
  if (args.projectId) {
    params.set("project", String(args.projectId));
    const s = args.saved;
    key = `p:${args.projectId}|${s?.video_model ?? ""}|${s?.resolution ?? ""}|${s?.duration ?? ""}`;
  } else if (args.explicit) {
    const e = args.explicit;
    params.set("video_model", e.video_model);
    params.set("resolution", e.resolution);
    params.set("duration", String(e.duration));
    key = `e:${e.video_model}|${e.resolution}|${e.duration}`;
  } else key = "n:";
  return { key: `${key}|${args.aspect}|${args.lang}`, query: params.toString() };
}

/**
 * Цена карточки библиотеки, пока витрина пересчитывается под новые настройки:
 * видео из таблицы модели, кадр — этой сцены (tryon_credits). В режиме наценки
 * это ровно то, что посчитает сервер; потом его число всё равно заменит подсказку.
 * null — подсказки нет (настроек нет или модель их не умеет): остаётся прежнее число.
 */
export function cardEstimate(
  model: CartoonModel | null | undefined,
  dock: DockSettings | null | undefined,
  aspect: string,
  tryonCredits: number | null | undefined,
  frameFallback?: number | null,
): { credits: number; duration: number } | null {
  if (!dock || !model || model.id !== dock.video_model) return null;
  const video = tablePrice(model, { resolution: dock.resolution, duration: dock.duration, aspect, keyframeReady: true }, frameFallback);
  if (video == null) return null;
  const frame = typeof tryonCredits === "number" ? tryonCredits : frameCreditsOf(model, frameFallback);
  return { credits: video + frame, duration: dock.duration };
}

/* ------------------------------------------------------------------ */
/* Лента                                                               */
/* ------------------------------------------------------------------ */

/**
 * Строка ленты гостя: длительность и цена так, как их посчитает сервер после
 * входа. full — кадр + видео, render — что спишет «Снять» (с готовым кадром —
 * только видео). Карточка библиотеки (cardCredits) точнее таблицы, но только
 * если сцена снимается с настройками витрины: без своей длительности и не своя.
 */
export function guestRowPrice(args: {
  model: CartoonModel | null | undefined;
  /** Настройки, которыми снимется сцена (явные или «как показано в доке»). */
  resolution: string | null | undefined;
  duration: number | null | undefined;
  aspect: string;
  custom: boolean;
  ownDuration: boolean;
  keyframe: boolean;
  /** Цена карточки, посчитанная сервером под нынешние настройки (иначе undefined). */
  cardCredits?: number | null;
  /** Цена кадра этой сцены (tryon_credits карточки). */
  frameCredits?: number | null;
  frameFallback?: number | null;
}): { full: number | null; render: number | null } {
  const frame =
    typeof args.frameCredits === "number" ? args.frameCredits : frameCreditsOf(args.model, args.frameFallback);
  let full: number | null;
  if (!args.custom && !args.ownDuration && args.cardCredits !== undefined) full = args.cardCredits;
  else {
    const video = tablePrice(
      args.model,
      { resolution: args.resolution, duration: args.duration, aspect: args.aspect, keyframeReady: true },
      args.frameFallback,
    );
    full = video == null ? (args.custom || args.ownDuration ? null : (args.cardCredits ?? null)) : video + frame;
  }
  if (full == null) return { full: null, render: null };
  return { full, render: args.keyframe ? Math.max(0, full - frame) : full };
}

type TotalScene = { status: string; render_credits?: number | null; price_unavailable?: boolean };

/** Сцены, которые ещё предстоит снять: черновики и несостоявшиеся. */
export function toShoot<T extends TotalScene>(scenes: readonly T[]): T[] {
  return scenes.filter((s) => s.status === "draft" || s.status === "failed");
}

/**
 * «Итого»: сумма цен строк, которые ещё снимать. Хоть у одной цены нет —
 * итога тоже нет (credits null): «примерно» за деньги не пишем.
 */
export function timelineTotal(scenes: readonly TotalScene[]): { credits: number | null; count: number } {
  const rows = toShoot(scenes);
  let sum = 0;
  for (const s of rows) {
    if (s.price_unavailable || typeof s.render_credits !== "number" || !Number.isFinite(s.render_credits)) {
      return { credits: null, count: rows.length };
    }
    sum += s.render_credits;
  }
  return { credits: rows.length ? sum : 0, count: rows.length };
}

/* ------------------------------------------------------------------ */
/* «Снять»: цена с кнопки                                              */
/* ------------------------------------------------------------------ */

/**
 * Тело «Снять» / «Переснять»: цена, которую человек видел на кнопке. Сервер
 * снимает, только если она не выросла (иначе 409 price_changed): док могли
 * сменить в другой вкладке или в боте, модель — выключить в админке. Цены нет —
 * тело без неё, как раньше (такую сцену сервер всё равно не снимет).
 */
export function quoteBody(credits: number | null | undefined): { quoted_credits?: number } {
  return typeof credits === "number" && Number.isInteger(credits) && credits >= 0 ? { quoted_credits: credits } : {};
}

/** Отказ «цена изменилась» (409 price_changed): новая цена, если сервер её назвал; не он — null. */
export function priceChanged(status: number, body: unknown): { credits: number | null } | null {
  if (status !== 409 || !body || typeof body !== "object") return null;
  const b = body as { error_code?: unknown; credits?: unknown };
  if (b.error_code !== "price_changed") return null;
  return { credits: typeof b.credits === "number" && Number.isFinite(b.credits) ? b.credits : null };
}

/**
 * Отказ «сцена уже снята» (409 already_shot): строка на странице устарела — сцену
 * сняли в другой вкладке или в боте. Ничего не снято и не списано.
 */
export function alreadyShot(status: number, body: unknown): boolean {
  if (status !== 409 || !body || typeof body !== "object") return false;
  return (body as { error_code?: unknown }).error_code === "already_shot";
}

/**
 * Отказ сервера на правку дока или сцены — текстом на языке человека.
 *
 * Русский текст сервера точнее всего («Seedance Mini снимает от 4 до 15 секунд»),
 * поэтому по-русски — он. Для en/kg — свой текст по error_code; незнакомый код —
 * fallback (общий «не удалось сохранить»). Ключ, а не готовый текст: перевод — у компонента.
 * keepDetail — у незнакомого кода лучше текст сервера, чем общий: отказы съёмки и кадра
 * без кода («опишите сцену по-другому») объясняют, что делать.
 */
export function refusalText(
  lang: string,
  body: unknown,
  fallback: DockTextKey,
  keepDetail = false,
): { key: DockTextKey; detail?: string } {
  const b = body && typeof body === "object" ? (body as { detail?: unknown; error_code?: unknown }) : {};
  const detail = typeof b.detail === "string" && b.detail.trim() ? b.detail.trim() : "";
  if (detail && String(lang || "").toLowerCase().startsWith("ru")) return { key: fallback, detail };
  const key = refusalKey(b.error_code);
  if (key) return { key };
  return keepDetail && detail ? { key: fallback, detail } : { key: fallback };
}

/** Свой текст для известного кода отказа мультстудии (core/cartoon/views.py, serializers.py). */
function refusalKey(code: unknown): DockTextKey | null {
  switch (code) {
    case "model_unavailable":
    case "model_required":
      return "studio_ui.dock_err_model";
    case "unsupported_resolution":
    case "unsupported_duration":
    case "invalid_resolution":
    case "invalid_duration":
      return "studio_ui.dock_err_value";
    case "caps_unavailable":
      return "studio_ui.dock_err_caps";
    case "scene_busy":
      return "studio_ui.scene_err_busy";
    case "price_unavailable":
      return "studio_ui.scene_err_price";
    case "invalid_quote":
      return "studio_ui.scene_err_quote";
    case "invalid_expect_status":
      return "studio_ui.scene_err_stale";
    case "scene_changed":
      return "studio_ui.scene_err_changed";
    case "already_shot":
      return "studio_ui.scene_already_shot";
    default:
      return null;
  }
}

/**
 * Сообщения «Цена изменилась: теперь N кр» у строк ленты после того, как цены строк
 * перечитали (опрос, правка дока или формата). price — число из сообщения: у строки
 * уже другая цена (или строки нет) — сообщение устарело и уходит, иначе «теперь 54 кр»
 * висело бы рядом с ценой 35. Без числа (price null) его снимает только сохранённая
 * правка дока или формата (saved). Сообщения без price не трогаем. Ничего не ушло —
 * тот же объект: React не перерисует ленту зря.
 */
export function settlePriceNotes<T extends { price?: number | null }>(
  notes: Record<number, T>,
  scenes: readonly { id: number; render_credits?: number | null; preset?: { credits?: number | null } }[],
  saved: boolean,
): Record<number, T> {
  let out = notes;
  for (const [key, note] of Object.entries(notes)) {
    if (note.price === undefined) continue;
    const row = scenes.find((s) => s.id === Number(key));
    const stale = !row || (note.price === null ? saved : (row.render_credits ?? row.preset?.credits ?? null) !== note.price);
    if (!stale) continue;
    if (out === notes) out = { ...notes };
    delete out[Number(key)];
  }
  return out;
}

/** Состояния строки, из которых есть ↻ «Переснять» (и которые понимает сервер). */
const RETRY_STATUSES: readonly string[] = ["draft", "failed", "ready"];

/**
 * Тело ↻ «Переснять»: цена с кнопки и состояние строки, которое видел человек.
 * Спрашиваем перед пересъёмкой только у готовой строки — поэтому строка «ошибка»
 * из устаревшей вкладки не должна заменить уже снятый ролик: сервер откажет 409
 * already_shot.
 */
export function retryBody(
  credits: number | null | undefined,
  status: string,
): { retry: true; quoted_credits?: number; expect_status?: string } {
  return { retry: true, ...quoteBody(credits), ...(RETRY_STATUSES.includes(status) ? { expect_status: status } : {}) };
}

/**
 * Выбор длительности в строке ленты: что умеет модель сцены. Своё значение,
 * которого в списке нет (каталог поменялся), не теряем — показываем как есть.
 */
export function durationChoices(durations: readonly number[] | null | undefined, own: number | null | undefined): number[] {
  const list = [...(durations || [])];
  if (own && !list.includes(own)) list.push(own);
  return list.sort((a, b) => a - b);
}

/** «Seedance Mini · 480p» — чем снимется или снята сцена (без длительности). */
export function configLabel(cfg: Pick<SceneConfig, "model_name" | "resolution"> | null | undefined): string {
  if (!cfg) return "";
  return [cfg.model_name, cfg.resolution].filter(Boolean).join(" · ");
}

type QuestionConfig = Pick<SceneConfig, "video_model" | "model_name" | "resolution"> & { aspect_ratio?: string };

/**
 * Вопрос «переснять ради другой длительности»: пересъёмка идёт с НЫНЕШНИМИ моделью
 * и качеством дока (решение 2) и в нынешнем формате мультфильма. Отличаются от прошлой
 * съёмки — называем их, иначе ролик 2.0 · 720p в 16:9 молча сменился бы на Mini · 480p
 * в 9:16. Совпадают — короткий вопрос. Что ролик заменится, говорит каждый вариант.
 * shot — чем сцена снята; next — чем переснимется (scene.config после PATCH длительности).
 */
export function reshootDurationQuestion(args: {
  shot: QuestionConfig | null | undefined;
  next: QuestionConfig | null | undefined;
  from: number | string;
  to: number | string;
  credits: number;
}): DockNotice {
  const { shot, next, from, to, credits } = args;
  if (!shot || !next) return { key: "studio_ui.scene_reshoot_duration", params: { from, to, credits } };
  const params = { from, to, credits, was: configLabel(shot), config: configLabel(next) };
  if (shot.aspect_ratio && next.aspect_ratio && shot.aspect_ratio !== next.aspect_ratio) {
    return {
      key: "studio_ui.scene_reshoot_duration_fmt",
      params: { ...params, was_aspect: shot.aspect_ratio, aspect: next.aspect_ratio },
    };
  }
  if (shot.video_model !== next.video_model || String(shot.resolution) !== String(next.resolution)) {
    return { key: "studio_ui.scene_reshoot_duration_cfg", params };
  }
  return { key: "studio_ui.scene_reshoot_duration", params: { from, to, credits } };
}

/** Больше 300 знаков реплики сервер не хранит. */
export const DIALOGUE_MAX = 300;
/** Живая речь — около 13 знаков в секунду (та же норма, что director.LINE_CHARS_PER_SEC на сервере). */
export const LINE_CHARS_PER_SEC = 13;

/** Предел поля реплики: по длине снимка (clipSeconds), но не больше, чем сохранит сервер. */
export function dialogueMaxLength(seconds: number | null | undefined): number {
  const s = typeof seconds === "number" && Number.isFinite(seconds) && seconds > 0 ? seconds : 5;
  return Math.min(DIALOGUE_MAX, Math.max(40, Math.round(s * LINE_CHARS_PER_SEC)));
}

/**
 * Длина ролика сцены, секунды: снятой или снимающейся — по съёмке (scene.shot), иначе
 * та, с которой снимется (config, затем длительность в карточке). Для звука: «трек
 * длиннее сцены» считается от настоящего ролика, а не от нынешнего дока.
 */
export function clipSeconds(scene: {
  status: string;
  shot?: { duration?: number | null } | null;
  config?: { duration?: number | null } | null;
  preset?: { duration?: number | null };
} | null | undefined): number {
  if (!scene) return 5;
  const shotOrWorking = scene.status === "ready" || scene.status === "new" || scene.status === "keyframe" || scene.status === "video";
  const value = (shotOrWorking ? scene.shot?.duration : null) ?? scene.config?.duration ?? scene.preset?.duration;
  return typeof value === "number" && value > 0 ? value : 5;
}

/**
 * Очередь запросов «по одному»: следующий уходит, только когда вернулся предыдущий.
 * Правки мультфильма (док, формат) так приходят на сервер в том порядке, в каком
 * их сделал человек, и последний ответ — это и есть итог на сервере.
 */
export function serialQueue(): <T>(task: () => Promise<T>) => Promise<T> {
  let tail: Promise<unknown> = Promise.resolve();
  return <T>(task: () => Promise<T>): Promise<T> => {
    const run = tail.then(task, task);
    tail = run.catch(() => undefined);
    return run;
  };
}

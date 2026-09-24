"use client";

/**
 * Видеостудия: жизненный цикл параметров запуска.
 *
 * Один хук на всё, что должно работать, даже когда панель параметров не видна
 * (на телефоне она живёт в закрытой шторке):
 *   1. модели попадают в стор (models/loaded) — из общего 10-минутного кэша;
 *   2. если модели в композере нет или она не того вида — выбирается модель
 *      из настроек проекта, из последнего выбора в этой вкладке или первая
 *      доступная;
 *   3. при открытии проекта композер получает его Project.settings;
 *   4. изменения вида, модели и параметров уходят в Project.settings через
 *      PATCH projects/<uid>/ с паузой в 1 с.
 *
 * Хук можно звать из нескольких компонентов сразу (панель, чип, контейнер):
 * состояние, от которого зависят повторы (что уже сохранено, что ждёт отправки,
 * какой проект уже восстановлен), лежит в модуле, поэтому PATCH уходит один.
 */
import { useEffect, type Dispatch } from "react";
import { updateProject } from "@/lib/vstudio/api";
import type { ModelsResponse, ProjectJSON, ProjectSettings, ShotParams, Uid, VsAction, VsKind, VsState } from "@/lib/vstudio/types";
import { useVStudioModels } from "../hooks/useVStudioModels";
import {
  PARAM_KEYS,
  PERSIST_DEBOUNCE_MS,
  applyParamsPatch,
  choiceFromSettings,
  diffParams,
  findModel,
  initialChoice,
  memoryFromSettings,
  settingsKey,
  settingsPayload,
  switchKindChoice,
  switchModelChoice,
  type KindMemory,
  type SettingsChoice,
} from "./settingsModel";

type Current = { kind: VsKind; model: string | null; params: ShotParams };

/* ------------------------------------------------------------------ */
/* Состояние модуля (общее для всех экземпляров хука)                  */
/* ------------------------------------------------------------------ */

/** Последний выбор по видам в этой вкладке: «Картинка» и обратно не теряет модель видео. */
const kindMemory: KindMemory = {};
/** Для какого проекта настройки уже применены к композеру. */
let restoredFor: Uid | null = null;
/** Ключ settingsKey того, что лежит в Project.settings на сервере (по нашим данным). */
const savedKeys = new Map<Uid, string>();
/** Какие настройки проекта мы последний раз видели в сторе (чтобы заметить свежие с сервера). */
const seenKeys = new Map<Uid, string>();
const pending = new Map<Uid, { key: string; timer: ReturnType<typeof setTimeout> }>();
/** Что сейчас летит на сервер: тот же ключ второй раз не отправляем. */
const sending = new Map<Uid, string>();
/** Какой ответ models/ уже отдан в какой стор — чтобы не диспатчить одно и то же N раз. */
const dispatchedModels = new WeakMap<object, ModelsResponse>();
/**
 * Последний прогон синхронизации по каждому стору (ключ — dispatch). Хук зовут
 * контейнер, панель и чип: в одном коммите у всех одинаковое состояние, и
 * работать должен один — иначе вторые экземпляры повторяли бы действия по
 * устаревшему снимку стора.
 */
let lastRun = new WeakMap<object, string>();
/** Номер объекта моделей: новый ответ models/ — новый прогон, даже если ключи те же. */
const modelIds = new WeakMap<object, number>();
let modelSeq = 0;

function modelsId(models: object | null | undefined): number {
  if (!models) return 0;
  let id = modelIds.get(models);
  if (!id) {
    id = ++modelSeq;
    modelIds.set(models, id);
  }
  return id;
}

/**
 * true — этот прогон первый для такого состояния этого стора; false — его уже
 * сделал другой экземпляр хука (или StrictMode повторил эффект).
 */
export function claimSyncRun(dispatch: object, signature: string): boolean {
  if (lastRun.get(dispatch) === signature) return false;
  lastRun.set(dispatch, signature);
  return true;
}

export function getKindMemory(): KindMemory {
  return kindMemory;
}

/** Для тестов и «Новой генерации» без памяти. */
export function resetRunSettingsSync(): void {
  for (const p of pending.values()) clearTimeout(p.timer);
  pending.clear();
  sending.clear();
  savedKeys.clear();
  seenKeys.clear();
  lastRun = new WeakMap();
  restoredFor = null;
  delete kindMemory.video;
  delete kindMemory.image;
}

/* ------------------------------------------------------------------ */
/* Недонабранный ввод «Дополнительно»                                  */
/* ------------------------------------------------------------------ */

/** Черновики seed и негатива (AdvancedSection отправляет их в стор с паузой). */
const paramsDrafts = new Set<() => Partial<ShotParams> | null>();

/** Зарегистрировать источник черновика; вернёт отписку. */
export function registerParamsDraft(take: () => Partial<ShotParams> | null): () => void {
  paramsDrafts.add(take);
  return () => {
    paramsDrafts.delete(take);
  };
}

/** Забрать ещё не отправленный ввод (без dispatch); null — черновика нет. */
export function takeParamsDraft(): Partial<ShotParams> | null {
  let out: Partial<ShotParams> | null = null;
  for (const take of paramsDrafts) {
    const d = take();
    if (d) out = { ...(out || {}), ...d };
  }
  return out;
}

/**
 * Перед сменой модели или вида: недонабранный seed или негатив сначала уходит
 * в стор и в снимок, от которого считается выбор, — иначе отложенный патч
 * догнал бы уже новую модель (вкладки вида стоят и вне панели).
 */
function withDraft(dispatch: Dispatch<VsAction>, current: Current): Current {
  const draft = takeParamsDraft();
  if (!draft) return current;
  dispatch({ type: "composer/params", params: draft });
  return { ...current, params: applyParamsPatch(current.params, draft) };
}

/* ------------------------------------------------------------------ */
/* Действия                                                            */
/* ------------------------------------------------------------------ */

/**
 * Применить выбор к композеру тремя действиями стора. Если сменились вид или
 * модель, параметры уходят целиком (удалённые — явным undefined): редьюсер мог
 * сбросить их на composer/kind или composer/model.
 */
export function applyChoice(dispatch: Dispatch<VsAction>, current: Current, choice: SettingsChoice): void {
  const kindChanged = current.kind !== choice.kind;
  const modelChanged = kindChanged || current.model !== choice.model;
  if (kindChanged) dispatch({ type: "composer/kind", kind: choice.kind });
  if (modelChanged) dispatch({ type: "composer/model", model: choice.model });
  let patch: Partial<ShotParams>;
  if (modelChanged) {
    patch = {};
    for (const k of PARAM_KEYS) (patch as Record<string, unknown>)[k] = (choice.params as Record<string, unknown>)[k];
  } else {
    patch = diffParams(current.params, choice.params);
  }
  if (Object.keys(patch).length) dispatch({ type: "composer/params", params: patch });
  kindMemory[choice.kind] = { model: choice.model, params: choice.params };
}

/** Клик по карточке модели. */
export function selectModel(
  dispatch: Dispatch<VsAction>,
  models: Pick<ModelsResponse, "video" | "image"> | null,
  current: Current,
  modelId: string,
): void {
  const cur = withDraft(dispatch, current);
  const choice = switchModelChoice(models, cur.kind, modelId, cur.params);
  if (choice) applyChoice(dispatch, cur, choice);
}

/** Вкладки «Видео / Картинка». */
export function selectKind(
  dispatch: Dispatch<VsAction>,
  models: Pick<ModelsResponse, "video" | "image"> | null,
  current: Current,
  kind: VsKind,
): void {
  if (kind === current.kind && current.model) return;
  const cur = withDraft(dispatch, current);
  // Запомнить уходящий вид, чтобы вернуться к той же модели.
  if (cur.model && findModel(models, cur.model, cur.kind)) {
    kindMemory[cur.kind] = { model: cur.model, params: cur.params };
  }
  const choice = switchKindChoice(models, kind, cur.params, kindMemory);
  if (choice) applyChoice(dispatch, cur, choice);
}

/* ------------------------------------------------------------------ */
/* Сохранение в Project.settings                                       */
/* ------------------------------------------------------------------ */

/**
 * Запомнить, что лежит в настройках проекта. Новые данные с сервера (проект
 * перечитали — например, его меняли в другой вкладке) главнее нашей памяти,
 * но пока наш PATCH ждёт отправки или летит, память не трогаем: в сторе ещё
 * старые настройки.
 */
export function noteProjectSettings(uid: Uid, settings: ProjectSettings | null | undefined): void {
  const key = settingsKey(settings);
  if (seenKeys.get(uid) === key && savedKeys.has(uid)) return;
  seenKeys.set(uid, key);
  if (!savedKeys.has(uid) || (!pending.has(uid) && !sending.has(uid))) savedKeys.set(uid, key);
}

/**
 * Отложенный PATCH: повторный вызов с тем же содержимым ничего не делает,
 * возврат к сохранённому — отменяет отправку.
 */
export function scheduleSettingsSave(
  uid: Uid,
  payload: ProjectSettings,
  onSaved?: (project: ProjectJSON) => void,
  delayMs: number = PERSIST_DEBOUNCE_MS,
): void {
  const key = settingsKey(payload);
  const waiting = pending.get(uid);
  if (savedKeys.get(uid) === key) {
    if (waiting) {
      clearTimeout(waiting.timer);
      pending.delete(uid);
    }
    return;
  }
  if (waiting?.key === key) return;
  if (waiting) {
    clearTimeout(waiting.timer);
    pending.delete(uid);
  }
  if (sending.get(uid) === key) return;
  const timer = setTimeout(async () => {
    pending.delete(uid);
    sending.set(uid, key);
    const res = await updateProject(uid, { settings: payload });
    if (sending.get(uid) === key) sending.delete(uid);
    if (!res.ok) return; // не страшно: уйдёт со следующим изменением
    // Ключ — от отправленного: если сервер что-то нормализовал, не гоняем PATCH по кругу.
    savedKeys.set(uid, key);
    onSaved?.(res.data);
  }, delayMs);
  pending.set(uid, { key, timer });
}

/* ------------------------------------------------------------------ */
/* Хук                                                                 */
/* ------------------------------------------------------------------ */

export type SyncState = Pick<VsState, "models" | "project" | "composer" | "mode" | "available">;

export type SyncOutcome = "idle" | "restored" | "selected" | "synced";

/**
 * Один шаг синхронизации (тело эффекта хука, вынесено для тестов):
 * restored — применили настройки открытого проекта; selected — выбрали модель,
 * которой не было; synced — выбор в порядке, сохранение в проект запланировано
 * (или не нужно); idle — модели ещё не пришли.
 */
export function syncRunSettings(
  state: SyncState,
  dispatch: Dispatch<VsAction>,
  opts: { delayMs?: number } = {},
): SyncOutcome {
  const { models, project, composer } = state;
  if (!models) return "idle";
  const cur: Current = { kind: composer.kind, model: composer.model, params: composer.params };

  // 3. Открыли проект — его настройки главнее того, что было в композере.
  if (project && restoredFor !== project.uid) {
    restoredFor = project.uid;
    noteProjectSettings(project.uid, project.settings);
    const mem = memoryFromSettings(project.settings);
    for (const k of ["video", "image"] as const) if (mem[k] && !kindMemory[k]) kindMemory[k] = mem[k];
    const choice = choiceFromSettings(models, project.settings);
    if (choice && settingsKey(choice) !== settingsKey({ ...cur, model: cur.model ?? undefined })) {
      applyChoice(dispatch, cur, choice);
      return "restored";
    }
  }
  if (!project) restoredFor = null;

  // 2. Модели нет или она не того вида — выбрать.
  if (!findModel(models, cur.model, cur.kind)) {
    const choice = initialChoice(models, cur.kind, {
      settings: project?.settings,
      memory: kindMemory,
      params: cur.params,
    });
    if (choice) applyChoice(dispatch, cur, choice);
    return "selected";
  }

  kindMemory[cur.kind] = { model: cur.model as string, params: cur.params };

  // 4. Сохранить в проект (гостю проекта нет; при закрытой студии PATCH всё равно получит 403).
  const canSave = !!project && state.available !== false && state.mode !== "off";
  if (canSave && project) {
    noteProjectSettings(project.uid, project.settings);
    const payload = settingsPayload(project.settings, { kind: cur.kind, model: cur.model as string, params: cur.params }, kindMemory);
    scheduleSettingsSave(project.uid, payload, (saved) => dispatch({ type: "projects/upsert", project: saved }), opts.delayMs);
  }
  return "synced";
}

/**
 * Хук жизненного цикла параметров. Его можно звать из нескольких мест сразу
 * (контейнер VideoStudio, панель, чип): прогон по одному и тому же состоянию
 * делает только первый экземпляр (claimSyncRun), PATCH уходит один.
 */
export function useRunSettingsSync(state: SyncState, dispatch: Dispatch<VsAction>): void {
  const { models, project, composer } = state;

  useVStudioModels({
    onLoaded: (data) => {
      if (dispatchedModels.get(dispatch) === data) return;
      dispatchedModels.set(dispatch, data);
      // Контейнер мог уже положить этот же ответ в стор сам — второй раз не нужно.
      if (models && models.video === data.video && models.image === data.image) return;
      dispatch({ type: "models/loaded", payload: data });
    },
  });

  // Ключи вместо объектов в зависимостях: новый объект с теми же значениями — не повод.
  const currentKey = settingsKey({ kind: composer.kind, model: composer.model ?? undefined, params: composer.params });
  const projectUid = project?.uid ?? null;
  const projectKey = settingsKey(project?.settings);
  const canSave = !!project && state.available !== false && state.mode !== "off";

  useEffect(() => {
    const signature = [modelsId(models), projectUid ?? "", projectKey, currentKey, canSave ? 1 : 0].join("\u0001");
    if (!claimSyncRun(dispatch, signature)) return;
    syncRunSettings(state, dispatch);
    // Состояние читается из замыкания этого рендера, а перезапуск — только по ключам.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [models, projectUid, projectKey, currentKey, canSave, dispatch]);
}

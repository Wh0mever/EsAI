/**
 * Ссылка с выбором: /video-studio?model=<id>&kind=video|image&prompt=<текст> (§3.5).
 *
 * Так студию открывают страницы моделей и карточки на сайте: человек нажал
 * «Открыть в видеостудии» у Veo — и видит в панели запроса Veo, а не модель
 * по умолчанию. Ссылка только готовит панель: ничего не запускается и не
 * тратится.
 *
 *  — Модель главнее вида: «?model=<видео-модель>&kind=image» открывает модель.
 *  — Модель под замком тоже выбирается: человек видит то, за чем пришёл, а про
 *    тариф скажет кнопка запуска. Окно входа или оплаты с порога не открываем.
 *  — Текст кладём только в пустой запрос: своё и черновик гостя не затираем.
 *  — Всё непонятное молча пропускаем: модель, которой нет в списке, вид без
 *    моделей, текст длиннее предела (резать чужой текст на полуслове нельзя).
 *
 * Модуль без React и без окна — его проверяет node-тест deepLink.test.mjs на
 * настоящем редьюсере.
 */
import type { Dispatch } from "react";
import { cpLength, isEmptyDoc, normalizeText, sanitizeDoc } from "@/lib/vstudio/promptDoc";
import type { VsAction, VsKind, VsState } from "@/lib/vstudio/types";
import { safeReturnPath } from "@/tools/returnPath";
import { exampleDoc } from "./feed/examples";
import { selectKind, selectModel } from "./settings/useRunSettingsSync";
import { findModel } from "./store";

const KEYS = ["model", "kind", "prompt"] as const;
/** Тот же белый список, что у черновика гостя (lib/vstudio/draft.ts). */
const MODEL_RE = /^[\w.\-/:]{1,128}$/;
export const DEEP_LINK_PROMPT_MAX = 2000;

export type DeepLink = { model: string | null; kind: VsKind | null; prompt: string | null };

/**
 * Разобрать строку запроса адреса. null — наших параметров нет, и адрес
 * трогать незачем; поле null — параметра нет или значение не годится.
 */
export function parseDeepLink(search: string | null | undefined): DeepLink | null {
  const q = new URLSearchParams(search || "");
  if (!KEYS.some((k) => q.has(k))) return null;
  const model = (q.get("model") || "").trim();
  const kind = (q.get("kind") || "").trim().toLowerCase();
  const prompt = normalizeText(q.get("prompt")).trim();
  return {
    model: MODEL_RE.test(model) ? model : null,
    kind: kind === "video" || kind === "image" ? kind : null,
    prompt: prompt && cpLength(prompt) <= DEEP_LINK_PROMPT_MAX ? prompt : null,
  };
}

/** Строка запроса без наших параметров: чужие (utm_*, payment) остаются как были. */
export function stripDeepLink(search: string | null | undefined): string {
  const q = new URLSearchParams(search || "");
  for (const k of KEYS) q.delete(k);
  const rest = q.toString();
  return rest ? `?${rest}` : "";
}

/**
 * Куда вернуть человека после входа. Из проекта — в тот же проект: его
 * параметры хранит сервер. С первого экрана — по ссылке с его выбором вида и
 * модели: черновик без текста не сохраняется (lib/vstudio/draft.ts), и без
 * этого гость, пришедший со страницы Veo и нажавший «Войти» раньше, чем начал
 * писать, после входа видел модель по умолчанию. Текст в адрес не кладём — он
 * едет черновиком.
 */
export function signInReturnPath(
  base: string,
  projectUid: string | null,
  composer: { kind: VsKind; model: string | null },
): string {
  if (projectUid) return `${base}/${projectUid}`;
  const q = new URLSearchParams({ kind: composer.kind });
  if (composer.model && MODEL_RE.test(composer.model)) q.set("model", composer.model);
  // Путь, который страница входа не примет (tools/returnPath), увёл бы в чат — тогда без выбора.
  return safeReturnPath(`${base}?${q.toString()}`) ?? base;
}

/**
 * Применить ссылку к панели запроса. read отдаёт свежий стор после каждого
 * dispatch (контейнер ведёт его зеркало): смена вида сама выбирает модель и
 * параметры, и следующий шаг должен считать уже от них.
 *
 * Вид и модель идут теми же функциями, что и в панели параметров, — память
 * «последняя модель вида» ведёт себя одинаково, откуда бы ни пришёл выбор.
 */
export function applyDeepLink(
  link: DeepLink,
  read: () => Pick<VsState, "composer" | "models">,
  dispatch: Dispatch<VsAction>,
): void {
  const models = read().models;
  const current = () => {
    const c = read().composer;
    return { kind: c.kind, model: c.model, params: c.params };
  };
  if (models) {
    const found = findModel(models, link.model);
    const kind = found?.kind ?? link.kind;
    if (kind && kind !== current().kind) selectKind(dispatch, models, current(), kind);
    if (found && found.model.id !== current().model) selectModel(dispatch, models, current(), found.model.id);
  }
  if (link.prompt && isEmptyDoc(read().composer.doc)) {
    // sanitizeDoc: текст из сотен строк иначе вышел бы за предел абзацев документа.
    dispatch({ type: "composer/doc", doc: sanitizeDoc(exampleDoc(link.prompt)) });
  }
}

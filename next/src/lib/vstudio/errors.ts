/**
 * Видеостудия: ошибки API → что показать человеку.
 *
 * Бэкенд всегда отвечает {"error": "<рус. текст>", "error_code": "…", …доп. поля},
 * а fetchData поднимает в res.error только detail/message — поэтому код ошибки
 * читаем здесь, из тела. Правило перевода (§4.7): ключ `vstudio:errors.<code>`
 * (или `warnings.<code>`), русский текст бэкенда — defaultValue; если бэкенд
 * текста не дал (сеть, 429, HTML от nginx), берём свой из ERROR_RU.
 *
 * Модуль без импорта значений: его проверяют node-тесты (errors.test.mjs).
 */
import type { TFunction } from "i18next";
import type { PaywallContext, PaywallReason } from "@/components/chat/PaywallModal";
import type {
  BlockingCode,
  CompilerIssue,
  HttpErrorCode,
  IssueFix,
  PriceLine,
  TakeLite,
  VsError,
  VsKind,
  VsResult,
  WarningCode,
} from "./types";

/* ------------------------------------------------------------------ */
/* Русские тексты по умолчанию (подстановки в формате i18next: {{x}})   */
/* ------------------------------------------------------------------ */

/** Блокирующие ошибки компилятора (§4.7). */
export const BLOCKING_RU: Record<BlockingCode, string> = {
  prompt_empty: "Опишите, что должно происходить в кадре.",
  prompt_too_long:
    "Текст длиннее, чем принимает {{model}}: {{chars}} из {{hard}} символов. Сократите его или нажмите «Сжать с ИИ».",
  prompt_doc_invalid: "Не удалось прочитать текст запроса. Обновите страницу и попробуйте снова.",
  mention_not_attached:
    "В тексте есть тег фото, которого нет в запросе. Уберите красный тег или добавьте фото заново.",
  asset_not_found: "Фото не найдено — возможно, оно удалено.",
  asset_not_ready: "{{subject}} ещё создаётся — подождите несколько секунд.",
  asset_failed: "{{subject}} не получилось — удалите его или создайте заново.",
  refs_not_supported:
    "{{model}} не умеет работать с фото-референсами. Сделайте фото первым кадром или выберите другую модель.",
  too_many_refs: "{{model}} принимает не больше {{max}} фото-референсов, а у вас {{n}}.",
  frames_not_supported: "{{model}} не умеет начинать видео с вашего кадра.",
  last_frame_not_supported: "{{model}} не умеет заканчивать видео заданным кадром.",
  last_frame_with_refs:
    "С фото-референсами {{model}} не может закончить видео заданным кадром. Уберите последний кадр или референсы.",
  frames_refs_conflict:
    "{{model}} не может одновременно использовать кадры и фото-референсы. Выберите что-то одно.",
  ref_too_small: "{{subject}} слишком маленькое для {{model}}: нужно от {{min}} px по короткой стороне.",
  ref_bad_aspect:
    "{{subject}} слишком вытянутое для {{model}}: подойдёт соотношение сторон от {{lo_text}} до {{hi_text}}.",
  video_refs_unsupported: "Видео и звук как референсы появятся позже. Сейчас можно добавить только фото.",
  invalid_param: "{{model}} не поддерживает {{field_text}} = {{value_text}}. Доступно: {{allowed_text}}.",
  model_unavailable: "Эта модель сейчас недоступна. Выберите другую.",
  too_many_inputs: "Слишком много материалов в одном запросе (максимум {{max}}).",
  service_misconfigured: "Студия временно недоступна. Мы уже чиним.",
};

/** Предупреждения компилятора (§4.7): запуск разрешён. */
export const WARNING_RU: Record<WarningCode, string> = {
  prompt_long:
    "{{model}} лучше всего понимает до ~{{soft}} слов, а у вас {{words}}. Детали в конце могут потеряться — попробуйте «Сжать с ИИ».",
  looks_like_script:
    "Похоже на сценарий из нескольких сцен. Один ролик покажет только одну сцену — лучше снять сцены по отдельности.",
  ref_unmentioned:
    "{{subject}} прикреплено, но не упомянуто в тексте — модель решит сама, как его использовать. Лучше написать, кто или что это.",
  tag_unknown: "«{{text}}» похоже на тег, но такого фото в запросе нет.",
  frame_soft_pin: "Первый кадр отправим как Image {{k}}: начало видео будет похожим, но не точь-в-точь.",
  duration_forced: "С фото-референсами {{model}} снимает только {{value}} с — цена пересчитана.",
  faces_risk:
    "{{model}} не принимает фото реальных людей. Если на фото человек, генерация может не пройти — кредиты тогда не спишутся.",
  aspect_in_text: "В тексте указано {{value}}, а в настройках — {{current_text}}. Применить {{value}}?",
  lang_hint: "{{model}} лучше понимает английский. Русский текст тоже сработает, но точность ниже.",
  input_excluded: "{{subject}} не учитывается и не оплачивается.",
};

/**
 * У кадров свой род («@Первый кадр слишком маленький»). Ключи —
 * `errors.<code>_frame`: issueText передаёт i18next context "frame", и без
 * такого ключа он откатится к обычному.
 */
export const FRAME_RU: Record<string, string> = {
  asset_failed: "{{subject}} не получился — удалите его или создайте заново.",
  ref_too_small: "{{subject}} слишком маленький для {{model}}: нужно от {{min}} px по короткой стороне.",
  ref_bad_aspect:
    "{{subject}} слишком вытянутый для {{model}}: подойдёт соотношение сторон от {{lo_text}} до {{hi_text}}.",
};

/** Имена параметров для invalid_param ({{field_text}}): ключи `fields.<field>`. */
export const FIELD_RU: Record<string, string> = {
  duration: "длительность",
  resolution: "качество",
  aspect_ratio: "пропорции",
  seed: "seed",
  negative_prompt: "негатив",
  role: "роль",
  slot: "слот",
  generate_audio: "звук",
};

/** Кто виноват ({{subject}}): кадры переводятся, «@Image N» — нет (§4.2). Ключи `subject.<k>`. */
export const SUBJECT_RU: Record<"first_frame" | "last_frame" | "excluded", string> = {
  first_frame: "@Первый кадр",
  last_frame: "@Последний кадр",
  excluded: "Выключенное фото",
};

/** Коды ответов API (§8.4), которых нет среди ошибок компилятора. */
export const HTTP_RU: Record<Exclude<HttpErrorCode, BlockingCode>, string> = {
  bad_request: "Некорректный запрос. Обновите страницу и попробуйте снова.",
  unauthorized: "Войдите, чтобы продолжить.",
  insufficient_balance: "Недостаточно кредитов для генерации.",
  premium_locked: "Эта модель доступна на платном тарифе.",
  vstudio_disabled: "Видеостудия скоро откроется.",
  project_not_found: "Проект не найден.",
  take_not_found: "Генерация не найдена.",
  shot_not_found: "Запрос не найден.",
  price_changed: "Цена изменилась: теперь {{credits}} кр. Проверьте и нажмите «Создать» ещё раз.",
  too_many_open: "Одновременно можно запустить не больше {{limit}} — дождитесь, пока одна генерация закончится.",
  already_submitted: "Генерация уже отправлена модели — отменить её нельзя.",
  file_too_large: "Файл слишком большой: максимум 15 МБ.",
  unsupported_type: "Этот формат не подходит. Загрузите фото: JPG, PNG, WebP или HEIC.",
  bad_image: "Не удалось открыть фото — файл повреждён или это не картинка.",
  too_many_pixels: "Фото слишком большое по разрешению. Уменьшите его и загрузите снова.",
  blocked: "Запрос нельзя запустить — исправьте отмеченное.",
  condense_failed: "Не получилось сжать текст. Попробуйте ещё раз или сократите вручную.",
  throttled: "Слишком много запросов. Подождите немного и попробуйте снова.",
  provider_unavailable: "Сервис генерации временно недоступен. Кредиты не списаны — попробуйте чуть позже.",
  take_not_ready: "Видео ещё не готово — кадр можно взять, когда ролик появится.",
  frame_failed: "Не удалось взять последний кадр из видео. Попробуйте ещё раз.",
  forbidden: "Нет доступа.",
  method_not_allowed: "Такой запрос здесь не поддерживается.",
};

/**
 * Причины неудачного дубля (TakeLite.error.code): конвейер (§6, ERRORS в
 * core/vstudio/pipeline.py) и разбор ответа провайдера
 * (core/ai/provider_errors.py — тексты оттуда). Код конвейера без текста здесь
 * роняет errors.test.mjs: иначе человек увидел бы чужую причину.
 */
export const TAKE_ERROR_RU: Record<string, string> = {
  journal_unavailable: "Не удалось запустить генерацию. Кредиты не списаны — попробуйте ещё раз.",
  queue_timeout: "Генерация слишком долго ждала очереди. Кредиты не списаны — попробуйте ещё раз.",
  submit_unknown: "Не удалось подтвердить запуск — кредиты не списаны, мы проверим вручную.",
  provider_timeout: "Модель так и не вернула результат. Кредиты не списаны, мы проверим вручную.",
  provider_unreachable: "Не удалось забрать результат у модели. Кредиты не списаны, мы проверим вручную.",
  // Точнее текста бэкенда («не удалось сохранить результат»): ролик уже снят, и его довезут.
  save_failed: "Ролик снят, но сохранить его не удалось. Кредиты не списаны — мы довезём его вручную.",
  image_real_person:
    "Модель не принимает фото реальных людей. Используйте рисунок, аватар, мультяшного героя или картинку без лица — и попробуйте снова.",
  image_sensitive:
    "Модель отказалась от этой картинки: на ней что-то из запрещённого (обнажённость, насилие, кровь). Возьмите другую картинку.",
  prompt_rejected:
    "Модель отказалась от этого запроса: в описании есть то, что она считает запрещённым. Перефразируйте — без насилия, взрослых тем и реальных известных людей.",
  no_image_to_video:
    "Эта модель не умеет делать видео из картинки. Уберите картинку или выберите другую модель видео.",
  image_invalid:
    "Картинка не подошла: слишком большая, необычного формата или не загрузилась. Попробуйте JPG или PNG до 10 МБ.",
  provider_out_of_credits:
    "Сервис генерации временно недоступен — мы уже знаем и чиним. Кредиты не списаны, попробуйте чуть позже.",
  provider_busy: "Модель сейчас перегружена. Подождите минуту и попробуйте снова — кредиты не списаны.",
  bad_params:
    "Модель не приняла параметры видео (длительность, качество или пропорции). Выберите другие значения и попробуйте снова.",
  provider_error: "Не удалось запустить генерацию видео. Попробуйте ещё раз.",
  bad_result: "Модель вернула файл, который не удалось открыть. Кредиты не списаны — попробуйте ещё раз.",
  internal_error: "Не удалось запустить генерацию. Кредиты не списаны — попробуйте ещё раз.",
  no_image_input: "Эта модель не умеет работать с приложенной картинкой. Уберите её или выберите другую модель.",
};

/** Ошибки, которые фронт придумывает сам. */
export const CLIENT_RU: Record<string, string> = {
  network: "Нет сети — результаты не пропадут.",
  server_error: "Сервер не ответил. Попробуйте ещё раз.",
  not_found: "Не найдено.",
  bad_response: "Сервер ответил непонятно. Обновите страницу и попробуйте снова.",
  aborted: "",
  unknown: "Что-то пошло не так. Попробуйте ещё раз.",
  // Потерянный дубль с кодом, которого фронт не знает: только то, что верно при любой причине.
  take_lost: "Результат не выдан. Кредиты не списаны, мы проверим вручную.",
};

/** Все тексты группы errors.<code> в одном словаре — источник для FE-6. */
export const ERROR_RU: Record<string, string> = {
  ...CLIENT_RU,
  ...TAKE_ERROR_RU,
  ...HTTP_RU,
  ...BLOCKING_RU,
};

export const BLOCKING_CODES = Object.keys(BLOCKING_RU) as BlockingCode[];
export const WARNING_CODES = Object.keys(WARNING_RU) as WarningCode[];

/* ------------------------------------------------------------------ */
/* Ответ → VsError / VsResult                                          */
/* ------------------------------------------------------------------ */

/** То, что нужно от ApiResponse fetchData (и от ответа XHR-загрузки). */
export type RawResponse = {
  ok: boolean;
  status: number;
  data: unknown;
  error?: string;
};

const isObj = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

const str = (v: unknown): string => (typeof v === "string" ? v : "");

/** Код по HTTP-статусу, если тело без error_code (DRF, nginx, сеть). */
function codeForStatus(status: number): string {
  if (status === 0) return "network";
  if (status === 400) return "bad_request";
  if (status === 401) return "unauthorized";
  if (status === 404) return "not_found";
  if (status === 413) return "file_too_large";
  if (status === 429) return "throttled";
  if (status >= 500) return "server_error";
  return "unknown";
}

export function errorFromResponse(res: RawResponse): VsError {
  const data = isObj(res.data) ? res.data : {};
  const code = str(data.error_code) || codeForStatus(res.status);
  // error — формат студии, detail — DRF (401/429), res.error — то, что поднял fetchData.
  let message = str(data.error) || str(data.detail) || str(data.message);
  if (!message && res.error && !/^HTTP \d+$/.test(res.error) && res.status !== 0) message = res.error;
  return { status: res.status, code, message, data };
}

/** ApiResponse → VsResult: ok, но пустое тело у ответа с данными — это bad_response. */
export function toResult<T>(res: RawResponse, opts?: { allowEmpty?: boolean }): VsResult<T> {
  if (!res.ok) return { ok: false, status: res.status, error: errorFromResponse(res) };
  if (res.data == null && !opts?.allowEmpty) {
    return {
      ok: false,
      status: res.status,
      error: { status: res.status, code: "bad_response", message: "", data: {} },
    };
  }
  return { ok: true, status: res.status, data: res.data as T };
}

export function abortedError(): VsError {
  return { status: 0, code: "aborted", message: "", data: {} };
}

export function isAborted(err: VsError | null | undefined): boolean {
  return err?.code === "aborted";
}

/* ------------------------------------------------------------------ */
/* Что делать с ошибкой                                                */
/* ------------------------------------------------------------------ */

const PAYWALL_CODES: readonly PaywallReason[] = [
  "premium_locked",
  "insufficient_balance",
  "insufficient_tokens",
  "daily_limit_reached",
];

export function isPaywallCode(code: string): code is PaywallReason {
  return (PAYWALL_CODES as readonly string[]).includes(code);
}

const num = (v: unknown): number | undefined =>
  typeof v === "number" && Number.isFinite(v) ? v : undefined;

/** Контекст существующего PaywallModal (402 у студии той же формы, что в чате). */
export function paywallContext(err: VsError | null | undefined): PaywallContext | null {
  if (!err || !isPaywallCode(err.code)) return null;
  return {
    reason: err.code,
    minPackageKgs: num(err.data.min_package_kgs),
    balanceTokens: num(err.data.balance_tokens),
    requiredEstimate: num(err.data.required_estimate),
    limit: num(err.data.limit),
  };
}

/** Сколько кредитов не хватает для «Пополнить · не хватает N кр» (0 — хватает или неизвестно). */
export function missingCredits(err: VsError | null | undefined): number {
  if (!err || err.code !== "insufficient_balance") return 0;
  const need = num(err.data.required_estimate);
  const have = num(err.data.balance_tokens);
  if (need == null || have == null) return 0;
  return Math.max(0, Math.ceil(need - have));
}

const ISSUE_LIST = (v: unknown): CompilerIssue[] =>
  Array.isArray(v)
    ? v.filter(isObj).map((x) => ({
        code: str(x.code) || "unknown",
        params: isObj(x.params) ? x.params : {},
        message: str(x.message),
        fix: isObj(x.fix) ? (x.fix as IssueFix) : null,
        ...(Array.isArray(x.fixes) ? { fixes: x.fixes.filter(isObj) as IssueFix[] } : {}),
      }))
    : [];

const NOT_FOUND_CODES = new Set([
  "not_found",
  "project_not_found",
  "take_not_found",
  "asset_not_found",
  "shot_not_found",
]);

const UPLOAD_CODES = new Set([
  "file_too_large",
  "unsupported_type",
  "bad_image",
  "too_many_pixels",
  "video_refs_unsupported",
]);

/**
 * Реакция интерфейса на ошибку. Тексты не здесь: для каждой ветки, кроме
 * paywall/auth/disabled, показывайте errorText(t, err).
 */
export type ErrorReaction =
  /** PaywallModal: premium_locked (403) или insufficient_balance (402). */
  | { kind: "paywall"; paywall: PaywallContext; missing: number }
  /** Окно входа (StudioAuthDialog с returnTo). */
  | { kind: "auth" }
  /** Страница «Видеостудия скоро откроется». */
  | { kind: "disabled" }
  /** 409 price_changed: обновить кнопку новой ценой и ждать второго клика. */
  | { kind: "requote"; credits: number | null; breakdown: PriceLine[] }
  /** 422 blocked: причины под кнопкой и кнопки исправления. */
  | { kind: "blocked"; errors: CompilerIssue[]; warnings: CompilerIssue[] }
  /** 409 too_many_open: «Сейчас снимается 2 — дождитесь одного». */
  | { kind: "limit"; limit: number | null; of: VsKind | null }
  /** Проект, дубль, ассет или кадр не найден (чужой uid неотличим). */
  | { kind: "not_found" }
  /** Загрузка файла отклонена: чип в failed с причиной. */
  | { kind: "upload" }
  /** Нет сети: плашка офлайна, результаты не пропадут. */
  | { kind: "offline" }
  /** 429, 503, 5xx: попробовать позже. */
  | { kind: "retry_later" }
  /** Отменённый запрос (AbortController): ничего не показывать. */
  | { kind: "ignore" }
  /** Всё остальное: всплывающее сообщение с errorText. */
  | { kind: "message" };

export function reactionFor(err: VsError): ErrorReaction {
  const { code, status, data } = err;
  if (code === "aborted") return { kind: "ignore" };
  const paywall = paywallContext(err);
  if (paywall) return { kind: "paywall", paywall, missing: missingCredits(err) };
  if (code === "unauthorized" || status === 401) return { kind: "auth" };
  if (code === "vstudio_disabled") return { kind: "disabled" };
  if (code === "price_changed") {
    const breakdown = Array.isArray(data.breakdown) ? (data.breakdown.filter(isObj) as PriceLine[]) : [];
    return { kind: "requote", credits: num(data.credits) ?? null, breakdown };
  }
  if (code === "blocked") {
    return { kind: "blocked", errors: ISSUE_LIST(data.errors), warnings: ISSUE_LIST(data.warnings) };
  }
  if (code === "too_many_open") {
    const of = data.kind === "video" || data.kind === "image" ? data.kind : null;
    return { kind: "limit", limit: num(data.limit) ?? null, of };
  }
  if (NOT_FOUND_CODES.has(code)) return { kind: "not_found" };
  if (UPLOAD_CODES.has(code)) return { kind: "upload" };
  if (code === "network") return { kind: "offline" };
  if (
    code === "throttled" ||
    code === "provider_unavailable" ||
    code === "service_misconfigured" ||
    code === "server_error" ||
    status >= 500
  ) {
    return { kind: "retry_later" };
  }
  return { kind: "message" };
}

/* ------------------------------------------------------------------ */
/* Тексты                                                              */
/* ------------------------------------------------------------------ */

/** Подстановки для i18next: списки через запятую, null/undefined — пустая строка. */
export function interpolationParams(params: Record<string, unknown> | null | undefined): Record<string, string | number> {
  const out: Record<string, string | number> = {};
  for (const [k, v] of Object.entries(params || {})) {
    if (typeof v === "number") out[k] = v;
    else if (Array.isArray(v)) out[k] = v.map((x) => String(x)).join(", ");
    else if (v == null) out[k] = "";
    else if (typeof v === "boolean") out[k] = v ? "true" : "false";
    else out[k] = String(v);
  }
  return out;
}

/** Ключ перевода ошибки в ns vstudio. */
export function errorKey(code: string): string {
  return `errors.${code}`;
}

export function warningKey(code: string): string {
  return `warnings.${code}`;
}

/** Русский по умолчанию, подставленный вручную (без i18next — для тостов вне React и тестов). */
export function fillRu(template: string, params: Record<string, unknown> | null | undefined): string {
  const p = interpolationParams(params);
  return template.replace(/\{\{\s*(\w+)\s*\}\}/g, (_, name: string) => (name in p ? String(p[name]) : ""));
}

type Translate = TFunction | ((key: string, options?: Record<string, unknown>) => string);

function translate(t: Translate, key: string, options: Record<string, unknown>): string {
  const fn = t as (key: string, options?: Record<string, unknown>) => unknown;
  const out = fn(key, options);
  return typeof out === "string" ? out : String(out ?? "");
}

/** 0.4 → «2:5», 2.5 → «5:2»: соотношение сторон словами, как в тексте бэкенда. */
export function ratioText(x: unknown): string {
  if (x === null || x === undefined || x === "") return "";
  const v = Number(x);
  if (!Number.isFinite(v) || v <= 0) return "";
  for (let q = 1; q <= 10; q++) {
    const p = Math.round(v * q);
    if (p > 0 && Math.abs(p / q - v) < 0.005) return `${p}:${q}`;
  }
  return String(v);
}

/**
 * Подстановки, которые бэкенд пишет только в русский текст (fmt в
 * vstudio/compiler.py), а в params не кладёт: subject, field_text,
 * value_text, allowed_text, current_text, lo_text, hi_text. Считаем их тут
 * теми же правилами, чтобы переводы могли повторять шаблоны бэкенда.
 * Без t — русские значения по умолчанию.
 */
export function derivedParams(params: Record<string, unknown> | null | undefined, t?: Translate): Record<string, string> {
  const p = params || {};
  const tr = (key: string, ru: string) => (t ? translate(t, key, { ns: "vstudio", defaultValue: ru }) : ru);
  const out: Record<string, string> = {};
  if ("slot" in p || "n" in p) {
    if (p.slot === "first_frame" || p.slot === "last_frame") out.subject = tr(`subject.${p.slot}`, SUBJECT_RU[p.slot]);
    else if (typeof p.n === "number" && p.n > 0) out.subject = `@Image ${p.n}`;
    else out.subject = tr("subject.excluded", SUBJECT_RU.excluded);
  }
  if (typeof p.field === "string") out.field_text = tr(`fields.${p.field}`, FIELD_RU[p.field] || p.field);
  if ("value" in p) out.value_text = p.value == null ? "" : String(p.value);
  if ("allowed" in p) out.allowed_text = Array.isArray(p.allowed) ? p.allowed.map(String).join(", ") : String(p.allowed ?? "");
  if ("current" in p) out.current_text = p.current === "auto" ? tr("settings.aspectAuto", "Авто") : String(p.current ?? "");
  if ("lo" in p || "hi" in p) {
    // Единственный диапазон в Фазе 1 — Seedance 0.4…2.5.
    out.lo_text = ratioText(p.lo) || "2:5";
    out.hi_text = ratioText(p.hi) || "5:2";
  }
  return out;
}

/**
 * Текст ошибки: перевод `vstudio:errors.<code>`; defaultValue — русский
 * текст бэкенда, иначе свой из ERROR_RU, иначе «что-то пошло не так».
 *
 * context — i18next context: `errors.<code>_<context>`, если такой ключ есть
 * (картинка: context "image" → «Не удалось сгенерировать изображение»),
 * иначе обычный ключ. У condense_failed context — причина из тела (reason):
 * «Сжимать нечего…» вместо общего «Не получилось сжать».
 *
 * unknownText — готовый (уже переведённый) текст для кода, которого фронт не
 * знает, вместо общего «что-то пошло не так».
 */
export function errorText(
  t: Translate,
  err: Pick<VsError, "code" | "message"> & {
    params?: Record<string, unknown>;
    data?: Record<string, unknown>;
    context?: string;
    unknownText?: string;
  },
): string {
  if (err.code === "aborted") return "";
  // У 409/429 параметры лежат прямо в теле (limit, credits) — берём и их.
  const params = { ...(err.data || {}), ...(err.params || {}) };
  const fallback = ERROR_RU[err.code]
    ? fillRu(ERROR_RU[err.code], params)
    : err.unknownText || fillRu(CLIENT_RU.unknown, null);
  const reason = err.code === "condense_failed" && typeof err.data?.reason === "string" ? err.data.reason : "";
  const context = err.context || reason || undefined;
  return translate(t, errorKey(err.code), {
    ns: "vstudio",
    defaultValue: err.message || fallback,
    ...(context ? { context } : {}),
    ...interpolationParams(params),
  });
}

/**
 * Причина закрытого дубля (failed | lost) — по его error.code, а не по статусу.
 * lost закрывают разные коды: «не подтвердили запуск» и «ролик снят, но не
 * сохранён» — не одно и то же, и одна фраза на весь статус называла бы чужую
 * причину.
 *
 * Код, которого фронт не знает, — текст бэкенда; нет и его — общая фраза
 * статуса, которая причину не называет. Дубль без ошибки (идёт, готов,
 * отменён) — пустая строка.
 */
export function takeErrorText(t: Translate, take: Pick<TakeLite, "status" | "kind" | "error">): string {
  if (take.status !== "failed" && take.status !== "lost") return "";
  const unknownText = errorText(t, { code: take.status === "lost" ? "take_lost" : "unknown", message: "" });
  const code = take.error?.code || "";
  const message = take.error?.message || "";
  if (!code) return message || unknownText;
  return errorText(t, {
    code,
    message,
    unknownText,
    // У картинки свои тексты (errors.<code>_image): «…картинку», а не «…ролик».
    context: take.kind === "image" ? "image" : undefined,
  });
}

const isFrameSlot = (slot: unknown) => slot === "first_frame" || slot === "last_frame";

/** Русский текст записи без i18next (мок-сервер, тосты вне React). */
export function issueRu(code: string, params: Record<string, unknown>, which: "errors" | "warnings"): string {
  const frame = which === "errors" && isFrameSlot(params.slot) ? FRAME_RU[code] : undefined;
  const table: Record<string, string> = which === "warnings" ? WARNING_RU : ERROR_RU;
  return fillRu(frame || table[code] || CLIENT_RU.unknown, { ...params, ...derivedParams(params) });
}

/**
 * Текст записи компилятора; which — группа ключей: errors или warnings.
 * У кадров — i18next context "frame" (ключ `errors.<code>_frame`).
 */
export function issueText(t: Translate, issue: CompilerIssue, which: "errors" | "warnings"): string {
  const params = issue.params || {};
  const code = String(issue.code);
  const frame = which === "errors" && isFrameSlot(params.slot) && Boolean(FRAME_RU[code]);
  return translate(t, which === "warnings" ? warningKey(code) : errorKey(code), {
    ns: "vstudio",
    defaultValue: issue.message || issueRu(code, params, which),
    ...(frame ? { context: "frame" } : {}),
    ...interpolationParams(params),
    ...derivedParams(params, t),
  });
}

/** Все исправления записи одним списком (fix и fixes). */
export function issueFixes(issue: CompilerIssue): IssueFix[] {
  const out: IssueFix[] = [];
  if (issue.fix) out.push(issue.fix);
  for (const f of issue.fixes || []) {
    if (!out.some((x) => x.action === f.action)) out.push(f);
  }
  return out;
}

/** Код для воронки vstudio_blocked: первая блокирующая причина. */
export function firstBlockingCode(errors: CompilerIssue[] | null | undefined): string | null {
  return errors && errors.length ? String(errors[0].code) : null;
}

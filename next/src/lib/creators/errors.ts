/**
 * EsAI Creators: ошибки API → что показать человеку.
 *
 * Сервер отвечает {code, message, detail, …доп. поля} (core/creators/errors.py),
 * а fetchData поднимает в res.error только текст — поэтому код читаем здесь,
 * из тела. Интерфейс на трёх языках переводит по коду: ключ `creators:errors.<code>`,
 * русский текст — из ERROR_RU. Текст сервера (он только русский) на
 * пользовательских страницах не печатаем; исключение — fieldErrorText.
 */
import type { TFunction } from "i18next";
import type { ApiResponse } from "@/tools/fetchData";
import type { CrError, CrResult } from "./types";

/** i18next t (любого namespace) или совместимая функция. */
export type CrT = TFunction | ((key: string, options?: Record<string, unknown>) => string);

function translate(t: CrT, key: string, options: Record<string, unknown>): string {
  const fn = t as (key: string, options?: Record<string, unknown>) => unknown;
  const out = fn(key, options);
  return typeof out === "string" ? out : String(out ?? "");
}

/** Русские тексты по коду (ключи `errors.<code>`): всё, что может вернуть API, плюс свои. */
export const ERROR_RU: Record<string, string> = {
  // 404
  disabled: "Программа EsAI Creators сейчас недоступна",
  not_found: "Не найдено",
  // 403
  not_creator: "Вы не участник программы EsAI Creators",
  creator_blocked: "Аккаунт креатора заблокирован",
  superuser_required: "Это действие доступно только главному администратору",
  apply_blocked: "Подача заявки для этого аккаунта закрыта",
  payouts_disabled: "Заявки на вывод временно не принимаются",
  // 409
  already_creator: "Вы уже участник программы EsAI Creators",
  application_open: "Ваша заявка уже на рассмотрении",
  code_taken: "Этот промокод уже занят",
  code_already_set: "Промокод уже создан. Изменить его может только администратор",
  code_unchanged: "Этот промокод уже установлен",
  already_bound: "Пользователь уже закреплён за другим креатором",
  has_referrer: "Пользователь уже зарегистрирован по приглашению",
  publication_duplicate: "Эта публикация уже добавлена",
  withdrawal_open: "У вас уже есть заявка на вывод в работе",
  txid_duplicate: "Этот TXID уже указан в другой выплате",
  bad_state: "Действие недоступно в текущем статусе",
  already_marked: "Платёж уже отмечен как возвращённый",
  payment_refunded: "Платёж возвращён — комиссию по нему начислить нельзя",
  duplicate_request: "Такой запрос только что выполнен. Подождите несколько секунд",
  creator_conflict: "Оба аккаунта участвуют в программе Creators — обратитесь в поддержку",
  // 400
  validation: "Проверьте заполнение полей",
  links_required: "Укажите хотя бы одну ссылку на соцсеть",
  code_format: "Промокод: от 4 до 16 символов, латинские буквы и цифры, первой идёт буква",
  code_reserved: "Этот промокод использовать нельзя",
  self: "Нельзя использовать собственный промокод",
  staff: "Сотрудника нельзя закрепить за креатором",
  creator_unusable: "Этот креатор сейчас не может принимать рефералов",
  too_late: "Промокод креатора можно ввести только в первые 72 часа после регистрации",
  already_paid: "Промокод креатора можно ввести только до первой оплаты",
  link_window: "Ссылка креатора действует только при регистрации",
  race: "Не удалось выполнить действие, попробуйте ещё раз",
  no_user: "Пользователь не найден или отключён",
  already_bound_same: "Пользователь уже закреплён за этим креатором",
  network_invalid: "Выберите социальную сеть из списка",
  url_invalid: "Укажите корректную ссылку (http:// или https://)",
  address_required: "Укажите адрес кошелька USDT TRC20",
  address_invalid: "Некорректный адрес USDT TRC20",
  amount_invalid: "Некорректная сумма",
  amount_below_min: "Минимальная сумма вывода — {{min}} USDT",
  insufficient_available: "Недостаточно средств, доступных к выводу",
  txid_invalid: "Некорректный TXID: нужны 64 шестнадцатеричных символа",
  reason_required: "Укажите причину",
  kind_invalid: "Укажите вид отметки: refund или fraud",
  category_invalid: "Выберите причину начисления из списка",
  level_unknown: "Такого уровня нет",
  percent_invalid: "Процент комиссии должен быть больше 0 и не больше 25",
  // DRF и свои (клиент)
  unauthorized: "Войдите, чтобы продолжить",
  forbidden: "Нет доступа",
  throttled: "Слишком много запросов. Подождите немного и попробуйте снова",
  network: "Нет соединения. Проверьте интернет и попробуйте ещё раз",
  server_error: "Сервер не ответил. Попробуйте ещё раз",
  unknown: "Что-то пошло не так. Попробуйте ещё раз",
  field_invalid: "Проверьте это поле",
};

/**
 * Отказы при вводе кода креатора в поле промокода (ключи `promo.errors.<code>`).
 * Тексты — как в CREATOR_PROMO_MESSAGES сервера (core/users/services.py).
 */
export const PROMO_ERROR_RU: Record<string, string> = {
  self: "Нельзя использовать собственный промокод",
  staff: "Промокод недоступен для этого аккаунта",
  already_bound: "Вы уже закреплены за другим креатором",
  has_referrer: "Вы уже зарегистрированы по приглашению — промокод креатора применить нельзя",
  too_late: "Промокод креатора можно ввести только в первые 72 часа после регистрации",
  already_paid: "Промокод креатора можно ввести только до первой оплаты",
};

/* ------------------------------------------------------------------ */
/* Ответ fetchData → CrResult                                          */
/* ------------------------------------------------------------------ */

const isObj = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

const str = (v: unknown): string => (typeof v === "string" ? v : "");

/** Коды самого DRF: сессии нет или она умерла. */
const UNAUTHORIZED_CODES = new Set(["not_authenticated", "authentication_failed", "token_not_valid"]);

/** Код по HTTP-статусу, когда тело без code (nginx, сеть, чужой обработчик). */
function codeByStatus(status: number): string {
  if (status === 0) return "network";
  if (status === 401) return "unauthorized";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 429) return "throttled";
  if (status >= 500) return "server_error";
  return "unknown";
}

function errorFromResponse(res: Pick<ApiResponse, "status" | "data">): CrError {
  const data = isObj(res.data) ? res.data : {};
  let code = str(data.code);
  if (UNAUTHORIZED_CODES.has(code)) code = "unauthorized";
  else if (code === "permission_denied") code = "forbidden";
  // "error" — заглушка обработчика, когда у отказа DRF своего кода нет.
  else if (!code || code === "error") code = codeByStatus(res.status);

  const error: CrError = {
    status: res.status,
    code,
    message: str(data.message) || str(data.detail),
    data,
  };
  if (isObj(data.fields)) {
    const fields: Record<string, string> = {};
    for (const [name, text] of Object.entries(data.fields)) fields[name] = String(text ?? "");
    error.fields = fields;
  }
  return error;
}

/** Ответ fetchData → результат с кодом ошибки. Никогда не бросает. */
export function toResult<T>(res: ApiResponse): CrResult<T> {
  if (!res.ok) return { ok: false, status: res.status, error: errorFromResponse(res) };
  // 2xx без JSON-объекта — вместо API ответил кто-то другой (HTML от nginx).
  if (!isObj(res.data)) {
    return {
      ok: false,
      status: res.status,
      error: { status: res.status, code: "unknown", message: "", data: {} },
    };
  }
  return { ok: true, status: res.status, data: res.data as T };
}

/* ------------------------------------------------------------------ */
/* Тексты                                                              */
/* ------------------------------------------------------------------ */

/** Служебные имена: значение из тела ответа не должно стать опцией i18next. */
const RESERVED_PARAMS = new Set(["ns", "defaultValue", "count", "context", "code", "message", "detail", "fields"]);

/**
 * Текст ошибки на языке интерфейса — по коду, не по тексту сервера.
 * Подстановки берутся из тела ответа (available) и из params; коду
 * amount_below_min нужен params.min.
 */
export function errorText(
  t: CrT,
  err: Pick<CrError, "code"> & { data?: Record<string, unknown> },
  params?: Record<string, string | number>,
): string {
  const code = err.code;
  const fromBody: Record<string, string | number> = {};
  for (const [name, value] of Object.entries(err.data || {})) {
    if (RESERVED_PARAMS.has(name)) continue;
    if (typeof value === "string" || typeof value === "number") fromBody[name] = value;
  }
  return translate(t, `errors.${code}`, {
    ns: "creators",
    defaultValue: ERROR_RU[code] ?? ERROR_RU.unknown,
    ...fromBody,
    ...(params || {}),
  });
}

/**
 * Ошибка поля формы от сервера. Текст сервера только русский: его показываем
 * как есть в русском интерфейсе, в остальных — общее «Проверьте это поле».
 */
export function fieldErrorText(t: CrT, lang: string, serverMessage: string | null | undefined): string {
  const text = (serverMessage || "").trim();
  if (text && (lang || "").toLowerCase().startsWith("ru")) return text;
  return translate(t, "errors.field_invalid", { ns: "creators", defaultValue: ERROR_RU.field_invalid });
}

/* ------------------------------------------------------------------ */
/* Поле промокода: код креатора                                        */
/* ------------------------------------------------------------------ */

/** Код креатора принят: ничего не начислено, человек закреплён за креатором. */
export function promoCreatorAccepted(t: CrT, name: string): string {
  return translate(t, "promo.creator_accepted", {
    ns: "creators",
    name,
    defaultValue: "Промокод принят — вы пришли по приглашению {{name}}",
  });
}

/** Отказ по коду креатора; незнакомый код — текст сервера (fallback). */
export function promoCreatorError(t: CrT, code: string | null | undefined, fallback: string): string {
  const ru = code ? PROMO_ERROR_RU[code] : undefined;
  if (!code || !ru) return fallback;
  return translate(t, `promo.errors.${code}`, { ns: "creators", defaultValue: ru });
}

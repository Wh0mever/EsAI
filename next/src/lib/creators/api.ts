/**
 * EsAI Creators: типизированный слой над /api/creators/ — публичная страница
 * и кабинет креатора.
 *
 * Все функции ходят через fetchData и никогда не бросают: ответ — CrResult с
 * кодом ошибки, прочитанным из тела (errors.ts). Страницы программы зовут
 * только эти функции, сами fetchData не трогают.
 *
 * Права на сервере: GET me/* — любой креатор (заблокированный читает);
 * всё, что пишет, и code/check/ — только активный, иначе 403 creator_blocked;
 * не креатор — 403 not_creator; программа выключена — 404 disabled.
 */
import { ensureAccess, fetchData } from "@/tools/fetchData";
import { deviceKeyHeader } from "@/tools/deviceKey";
import { toResult } from "./errors";
import type {
  Application,
  ApplicationBody,
  CodeCheck,
  CodeCreated,
  Commission,
  CommissionStatus,
  Credits,
  CrLang,
  CrResult,
  Invite,
  Iso,
  Me,
  Network,
  Paged,
  Program,
  Publication,
  PublicationStatus,
  Referral,
  Withdrawal,
} from "./types";

export const CREATORS = "creators/";

type Method = "GET" | "POST" | "PUT" | "PATCH";
type Query = Record<string, string | number | boolean | null | undefined>;

/** `?a=1&b=2` из непустых значений; true уходит как 1 (так читает сервер). */
export function queryString(params?: Query): string {
  const parts: string[] = [];
  for (const [name, value] of Object.entries(params || {})) {
    if (value === null || value === undefined || value === "" || value === false) continue;
    parts.push(`${encodeURIComponent(name)}=${encodeURIComponent(value === true ? "1" : String(value))}`);
  }
  return parts.length ? `?${parts.join("&")}` : "";
}

async function call<T>(
  path: string,
  method: Method = "GET",
  body?: Record<string, unknown> | null,
  auth: boolean = true,
  headers?: Record<string, string>,
): Promise<CrResult<T>> {
  try {
    // Сначала оживляем access (он живёт 12 ч): в режиме «только сотрудники»
    // сервер проверяет рубильник раньше входа и запросу без токена отвечает
    // 404 disabled, а не 401 — fetchData такой ответ обновлением не лечит.
    if (auth) await ensureAccess();
    return toResult<T>(await fetchData(`${CREATORS}${path}`, method, body ?? null, auth, headers));
  } catch {
    // fetchData не бросает; это страховка обещания «никогда не бросает».
    return { ok: false, status: 0, error: { status: 0, code: "network", message: "", data: {} } };
  }
}

/* ------------------------------------------------------------------ */
/* Публичное                                                           */
/* ------------------------------------------------------------------ */

/** Условия программы и состояние посетителя. Гостю отвечает так же (me.is_authenticated=false). */
export async function getProgram(): Promise<CrResult<Program>> {
  // Токен шлём, только если сессия жива: гостя с мёртвым токеном не редиректим.
  const authed = await ensureAccess();
  return call<Program>("program/", "GET", null, authed);
}

/** Переход по ссылке ?ref=CODE. Ответ всегда {ok: true}: существует ли код, по нему не узнать. */
export async function postClick(code: string): Promise<CrResult<{ ok: true }>> {
  const authed = await ensureAccess();
  return call<{ ok: true }>("click/", "POST", { code }, authed, deviceKeyHeader());
}

/** По чьему приглашению пришёл сам пользователь. */
export function getInvite(): Promise<CrResult<Invite>> {
  return call<Invite>("invite/");
}

/* ------------------------------------------------------------------ */
/* Заявка                                                              */
/* ------------------------------------------------------------------ */

export function getApplication(): Promise<CrResult<{ application: Application | null }>> {
  return call<{ application: Application | null }>("application/");
}

export function submitApplication(body: ApplicationBody): Promise<CrResult<{ application: Application }>> {
  return call<{ application: Application }>("application/", "POST", body);
}

/* ------------------------------------------------------------------ */
/* Кабинет                                                             */
/* ------------------------------------------------------------------ */

export function getMe(): Promise<CrResult<Me>> {
  return call<Me>("me/");
}

/** Язык уведомлений креатора. */
export function setLang(lang: CrLang): Promise<CrResult<{ lang: CrLang }>> {
  return call<{ lang: CrLang }>("me/", "PATCH", { lang });
}

/** Свободен ли код. 200 и тогда, когда занят: смотрите available и reason. */
export function checkCode(code: string): Promise<CrResult<CodeCheck>> {
  return call<CodeCheck>(`code/check/${queryString({ code })}`);
}

/** Создать свой промокод — один раз; дальше меняет только администратор. */
export function createCode(code: string): Promise<CrResult<CodeCreated>> {
  return call<CodeCreated>("me/code/", "POST", { code });
}

export function listPublications(
  params: { status?: PublicationStatus; page?: number } = {},
): Promise<CrResult<Paged<Publication>>> {
  return call<Paged<Publication>>(`me/publications/${queryString(params)}`);
}

export function addPublication(body: {
  network: Network;
  url: string;
  description: string;
}): Promise<CrResult<Publication>> {
  return call<Publication>("me/publications/", "POST", body);
}

/** Creator Credits: без страниц, последние 100 строк. full — вместе с расходами. */
export function getCredits(full?: boolean): Promise<CrResult<Credits>> {
  return call<Credits>(`me/credits/${queryString({ full })}`);
}

export function listCommissions(
  params: { status?: CommissionStatus; page?: number } = {},
): Promise<CrResult<Paged<Commission>>> {
  return call<Paged<Commission>>(`me/commissions/${queryString(params)}`);
}

export function listReferrals(params: { page?: number } = {}): Promise<CrResult<Paged<Referral>>> {
  return call<Paged<Referral>>(`me/referrals/${queryString(params)}`);
}

export function listWithdrawals(params: { page?: number } = {}): Promise<CrResult<Paged<Withdrawal>>> {
  return call<Paged<Withdrawal>>(`me/withdrawals/${queryString(params)}`);
}

/**
 * Заявка на вывод. amount — СТРОКА, как её ввёл человек: в число не
 * переводим, сумму разбирает сервер. address — если адрес ещё не сохранён.
 */
export function requestWithdrawal(body: { amount: string; address?: string }): Promise<CrResult<Withdrawal>> {
  const payload: Record<string, unknown> = { amount: body.amount };
  if (body.address) payload.address = body.address;
  return call<Withdrawal>("me/withdrawals/", "POST", payload);
}

export function setPayoutAddress(
  address: string,
): Promise<CrResult<{ payout_address: string; payout_address_changed_at: Iso | null }>> {
  return call<{ payout_address: string; payout_address_changed_at: Iso | null }>("me/payout-address/", "PUT", {
    address,
  });
}

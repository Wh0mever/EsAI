/**
 * EsAI Creators: типизированный слой над /api/manage/ — раздел «Creators»
 * панели /admin-new.
 *
 * Все функции ходят через fetchData с токеном и никогда не бросают: ответ —
 * CrResult с кодом ошибки. Кто что может, решает сервер: «любой сотрудник»
 * или «только главный администратор» (403 superuser_required) — отмечено у
 * каждой функции. Денег страница никуда не отправляет: USDT администратор
 * переводит сам и вводит TXID.
 */
import { fetchData } from "@/tools/fetchData";
import { queryString } from "./api";
import { toResult } from "./errors";
import type {
  AdminApplication,
  AdminCommission,
  AdminCreatorProfile,
  AdminCreatorRow,
  AdminCreditRow,
  AdminLevel,
  AdminLogRow,
  AdminPublication,
  AdminReferral,
  AdminSettings,
  AdminWithdrawal,
} from "./adminTypes";
import type {
  ApplicationStatus,
  CommissionStatus,
  CreatorStatus,
  CrMode,
  CrResult,
  Paged,
  PublicationStatus,
  WithdrawalStatus,
} from "./types";

export const MANAGE = "manage/";

type Method = "GET" | "POST" | "PATCH";
type Id = number | string;

async function call<T>(path: string, method: Method = "GET", body?: Record<string, unknown> | null): Promise<CrResult<T>> {
  try {
    return toResult<T>(await fetchData(`${MANAGE}${path}`, method, body ?? null, true));
  } catch {
    return { ok: false, status: 0, error: { status: 0, code: "network", message: "", data: {} } };
  }
}

/* ------------------------------------------------------------------ */
/* Заявки                                                              */
/* ------------------------------------------------------------------ */

/** Любой сотрудник. */
export function adminApplications(
  params: { status?: ApplicationStatus; q?: string; page?: number } = {},
): Promise<CrResult<Paged<AdminApplication>>> {
  return call<Paged<AdminApplication>>(`creators/applications/${queryString(params)}`);
}

/** Любой сотрудник — с уровнем creator; уровень выше — только главный администратор. */
export function adminApproveApplication(
  id: Id,
  level: string,
): Promise<CrResult<{ application: AdminApplication; creator: AdminCreatorRow }>> {
  return call<{ application: AdminApplication; creator: AdminCreatorRow }>(
    `creators/applications/${id}/approve/`,
    "POST",
    { level },
  );
}

/** Любой сотрудник; block: true (запрет подавать снова) — только главный администратор. */
export function adminRejectApplication(
  id: Id,
  body: { reason: string; block: boolean },
): Promise<CrResult<AdminApplication>> {
  return call<AdminApplication>(`creators/applications/${id}/reject/`, "POST", body);
}

/** Главный администратор. Причина обязательна. */
export function adminUnblockApplication(id: Id, reason: string): Promise<CrResult<AdminApplication>> {
  return call<AdminApplication>(`creators/applications/${id}/unblock/`, "POST", { reason });
}

/* ------------------------------------------------------------------ */
/* Креаторы                                                            */
/* ------------------------------------------------------------------ */

/** Любой сотрудник. ready — у кого выполнены условия следующего уровня. */
export function adminCreators(
  params: { status?: CreatorStatus; level?: string; q?: string; ready?: boolean; page?: number } = {},
): Promise<CrResult<Paged<AdminCreatorRow>>> {
  return call<Paged<AdminCreatorRow>>(`creators/${queryString(params)}`);
}

/** Любой сотрудник. */
export function adminCreator(id: Id): Promise<CrResult<AdminCreatorProfile>> {
  return call<AdminCreatorProfile>(`creators/${id}/`);
}

/** Главный администратор. Процент меняется только для будущих комиссий. */
export function adminSetLevel(id: Id, body: { level: string; reason: string }): Promise<CrResult<AdminCreatorRow>> {
  return call<AdminCreatorRow>(`creators/${id}/level/`, "POST", body);
}

/** Главный администратор. Причина обязательна; открытая заявка на вывод будет отклонена. */
export function adminBlock(id: Id, reason: string): Promise<CrResult<AdminCreatorRow>> {
  return call<AdminCreatorRow>(`creators/${id}/block/`, "POST", { reason });
}

/** Главный администратор. */
export function adminUnblock(id: Id, reason: string): Promise<CrResult<AdminCreatorRow>> {
  return call<AdminCreatorRow>(`creators/${id}/unblock/`, "POST", { reason });
}

/** Главный администратор. Код и причина обязательны; старый код остаётся рабочим псевдонимом. */
export function adminChangeCode(
  id: Id,
  body: { code: string; reason: string },
): Promise<CrResult<{ code: string; link: string; aliases: string[] }>> {
  return call<{ code: string; link: string; aliases: string[] }>(`creators/${id}/code/`, "POST", body);
}

/** Главный администратор. Только вручную: количество, причина из списка, примечание. */
export function adminGrantCredits(
  id: Id,
  body: { amount: number; category: string; note: string },
): Promise<CrResult<{ granted: number; remaining: number; balance: number; transaction: AdminCreditRow | null }>> {
  return call<{ granted: number; remaining: number; balance: number; transaction: AdminCreditRow | null }>(
    `creators/${id}/credits/`,
    "POST",
    body,
  );
}

/* ------------------------------------------------------------------ */
/* Публикации                                                          */
/* ------------------------------------------------------------------ */

/** Любой сотрудник. */
export function adminPublications(
  params: { status?: PublicationStatus; creator?: Id; page?: number } = {},
): Promise<CrResult<Paged<AdminPublication>>> {
  return call<Paged<AdminPublication>>(`creators/publications/${queryString(params)}`);
}

/** Любой сотрудник. */
export function adminApprovePublication(id: Id): Promise<CrResult<AdminPublication>> {
  return call<AdminPublication>(`creators/publications/${id}/approve/`, "POST", {});
}

/** Любой сотрудник. */
export function adminRejectPublication(id: Id, reason: string): Promise<CrResult<AdminPublication>> {
  return call<AdminPublication>(`creators/publications/${id}/reject/`, "POST", { reason });
}

/* ------------------------------------------------------------------ */
/* Рефералы                                                            */
/* ------------------------------------------------------------------ */

/** Любой сотрудник. suspect — только подозрительные, active — только действующие. */
export function adminReferrals(
  params: { creator?: Id; q?: string; suspect?: boolean; active?: boolean; page?: number } = {},
): Promise<CrResult<Paged<AdminReferral>>> {
  return call<Paged<AdminReferral>>(`creators/referrals/${queryString(params)}`);
}

/** Главный администратор. creator_id: null — снять привязку. Меняет только будущие оплаты. */
export function adminRebind(body: {
  user_id: number;
  creator_id: number | null;
  reason: string;
}): Promise<CrResult<{ referral: AdminReferral | null }>> {
  return call<{ referral: AdminReferral | null }>("creators/referrals/rebind/", "POST", body);
}

/** Главный администратор. */
export function adminClearSuspect(
  id: Id,
  body: { reason: string; release_held: boolean },
): Promise<CrResult<AdminReferral>> {
  return call<AdminReferral>(`creators/referrals/${id}/clear-suspect/`, "POST", body);
}

/* ------------------------------------------------------------------ */
/* Комиссии                                                            */
/* ------------------------------------------------------------------ */

/** Любой сотрудник. */
export function adminCommissions(
  params: { creator?: Id; status?: CommissionStatus; provider?: string; page?: number } = {},
): Promise<CrResult<Paged<AdminCommission>>> {
  return call<Paged<AdminCommission>>(`creators/commissions/${queryString(params)}`);
}

/** Главный администратор. Причина обязательна. */
export function adminVoidCommission(id: Id, reason: string): Promise<CrResult<AdminCommission>> {
  return call<AdminCommission>(`creators/commissions/${id}/void/`, "POST", { reason });
}

/** Главный администратор. held → accrued. */
export function adminReleaseCommission(id: Id, reason: string): Promise<CrResult<AdminCommission>> {
  return call<AdminCommission>(`creators/commissions/${id}/release/`, "POST", { reason });
}

/** Главный администратор. Причина обязательна. */
export function adminRestoreCommission(
  id: Id,
  body: { reason: string; clear_admin_refund: boolean },
): Promise<CrResult<AdminCommission>> {
  return call<AdminCommission>(`creators/commissions/${id}/restore/`, "POST", body);
}

/* ------------------------------------------------------------------ */
/* Выплаты                                                             */
/* ------------------------------------------------------------------ */

/** Любой сотрудник. */
export function adminWithdrawals(
  params: { status?: WithdrawalStatus; creator?: Id; page?: number } = {},
): Promise<CrResult<Paged<AdminWithdrawal>>> {
  return call<Paged<AdminWithdrawal>>(`creators/withdrawals/${queryString(params)}`);
}

/** Главный администратор. */
export function adminApproveWithdrawal(id: Id): Promise<CrResult<AdminWithdrawal>> {
  return call<AdminWithdrawal>(`creators/withdrawals/${id}/approve/`, "POST", {});
}

/** Главный администратор. Причина обязательна. */
export function adminRejectWithdrawal(id: Id, reason: string): Promise<CrResult<AdminWithdrawal>> {
  return call<AdminWithdrawal>(`creators/withdrawals/${id}/reject/`, "POST", { reason });
}

/**
 * Главный администратор. USDT уже отправлены вручную — записываем TXID.
 * force: true (деньги ушли, а сервер отказал: креатор заблокирован или после
 * заявки был возврат) требует reason.
 */
export function adminMarkPaid(
  id: Id,
  body: { txid: string; force?: boolean; reason?: string },
): Promise<CrResult<AdminWithdrawal>> {
  const payload: Record<string, unknown> = { txid: body.txid };
  if (body.force) payload.force = true;
  if (body.reason) payload.reason = body.reason;
  return call<AdminWithdrawal>(`creators/withdrawals/${id}/mark-paid/`, "POST", payload);
}

/** Главный администратор. Исправить опечатку в TXID выплаченной заявки. */
export function adminFixTxid(id: Id, body: { txid: string; reason: string }): Promise<CrResult<AdminWithdrawal>> {
  return call<AdminWithdrawal>(`creators/withdrawals/${id}/txid/`, "POST", body);
}

/** Главный администратор. Перевод не прошёл в сети: paid → approved. Причина обязательна. */
export function adminReopenWithdrawal(id: Id, reason: string): Promise<CrResult<AdminWithdrawal>> {
  return call<AdminWithdrawal>(`creators/withdrawals/${id}/reopen/`, "POST", { reason });
}

/* ------------------------------------------------------------------ */
/* Creator Credits, уровни, журнал, настройки                          */
/* ------------------------------------------------------------------ */

/** Любой сотрудник. Все выдачи Creator Credits, новые сверху. */
export function adminCredits(params: { creator?: Id; page?: number } = {}): Promise<CrResult<Paged<AdminCreditRow>>> {
  return call<Paged<AdminCreditRow>>(`creators/credits/${queryString(params)}`);
}

/** Любой сотрудник. */
export function adminLevels(): Promise<CrResult<{ results: AdminLevel[] }>> {
  return call<{ results: AdminLevel[] }>("creators/levels/");
}

export type AdminLevelChanges = {
  title?: string;
  percent?: string | number;
  min_publications?: number;
  min_registrations?: number;
  min_paying?: number;
  reason?: string;
};

/** Главный администратор. Шлите только изменённые поля; процент — строкой. */
export function adminEditLevel(key: string, changes: AdminLevelChanges): Promise<CrResult<AdminLevel>> {
  return call<AdminLevel>(`creators/levels/${encodeURIComponent(key)}/`, "PATCH", changes);
}

/** Любой сотрудник. Журнал ручных действий, только чтение. */
export function adminLog(
  params: { creator?: Id; action?: string; actor?: Id; page?: number } = {},
): Promise<CrResult<Paged<AdminLogRow>>> {
  return call<Paged<AdminLogRow>>(`creators/log/${queryString(params)}`);
}

/**
 * Главный администратор. Сотруднику сервер отвечает 403 superuser_required —
 * по этому ответу панель и узнаёт роль (отдельного поля is_superuser API не отдаёт).
 */
export function adminSettings(): Promise<CrResult<AdminSettings>> {
  return call<AdminSettings>("creators/settings/");
}

/** Главный администратор. Шлите только изменённые ключи; hold_days — от 0 до 90. */
export function adminPatchSettings(
  changes: Partial<{ mode: CrMode; payouts_enabled: boolean; hold_days: number }>,
): Promise<CrResult<AdminSettings>> {
  return call<AdminSettings>("creators/settings/", "PATCH", changes);
}

/* ------------------------------------------------------------------ */
/* Платежи                                                             */
/* ------------------------------------------------------------------ */

/** Ответ ручной отметки возврата; payment — строка платежа в том виде, как в списке /payments/. */
export type AdminMarkRefunded<P = Record<string, unknown>> = {
  reversed: number;
  clawback_debited: number;
  payment: P;
};

/**
 * Главный администратор. Ручная отметка «платёж возвращён» (refund) или
 * «мошенничество» (fraud): комиссия креатора отменяется; кредиты покупателя
 * изымаются только при clawback_credits: true. Причина обязательна.
 */
export function adminMarkRefunded<P = Record<string, unknown>>(
  paymentId: Id,
  body: { kind: "refund" | "fraud"; reason: string; clawback_credits: boolean },
): Promise<CrResult<AdminMarkRefunded<P>>> {
  return call<AdminMarkRefunded<P>>(`payments/${paymentId}/mark-refunded/`, "POST", body);
}

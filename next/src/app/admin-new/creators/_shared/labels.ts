/**
 * Раздел «Creators» панели: русские подписи кодов, которые отдаёт сервер.
 *
 * Панель — без переводов, как вся /admin-new. Незнакомый код (сервер прислал
 * новое значение) показываем как есть: лучше сырой код, чем пустая ячейка.
 */

export const SU_ONLY = "Только главный администратор";

export type Tone = "wait" | "ok" | "fail" | "muted";

export const APPLICATION_STATUS: Record<string, string> = {
  new: "Новая",
  approved: "Одобрена",
  rejected: "Отклонена",
  blocked: "Заблокирована",
};

export const CREATOR_STATUS: Record<string, string> = {
  active: "Активен",
  blocked: "Заблокирован",
};

export const PUBLICATION_STATUS: Record<string, string> = {
  review: "На проверке",
  approved: "Подтверждена",
  rejected: "Отклонена",
};

export const WITHDRAWAL_STATUS: Record<string, string> = {
  review: "На проверке",
  approved: "Одобрена",
  paid: "Выплачена",
  rejected: "Отклонена",
};

export const COMMISSION_STATUS: Record<string, string> = {
  accrued: "Начислена",
  held: "Придержана",
  reversed: "Отменена: возврат",
  void: "Аннулирована",
};

/** Цвет плашки по статусу: ждёт решения, всё хорошо, отказ. */
export const STATUS_TONE: Record<string, Tone> = {
  new: "wait",
  review: "wait",
  held: "wait",
  approved: "ok",
  paid: "ok",
  active: "ok",
  accrued: "ok",
  rejected: "fail",
  blocked: "fail",
  reversed: "fail",
  void: "fail",
};

/** Почему привязка реферала закончилась (CreatorReferral.end_reason). */
export const END_REASON: Record<string, string> = {
  admin_rebind: "перепривязан",
  admin_unbind: "привязка снята",
  merge_self: "слияние аккаунтов",
  merge_dropped: "слияние аккаунтов",
};

/** Причины пометки «подозрительная» (flags.reasons). */
export const SUSPECT_REASON: Record<string, string> = {
  same_device_as_creator: "то же устройство, что у креатора",
  same_device_as_referral: "то же устройство, что у другого реферала",
  same_ip_as_creator: "тот же IP, что у креатора",
  repeat_registration: "повторная регистрация",
};

const COMMISSION_REASON: Record<string, string> = {
  released: "выпущена администратором",
  restored: "восстановлена",
  admin_void: "аннулирована администратором",
  creator_blocked: "креатор заблокирован",
  creator_inactive: "аккаунт креатора отключён",
  referral_suspect: "привязка на проверке",
  merge_self: "собственная покупка",
  self_purchase: "собственная покупка",
  buyer_staff: "покупатель — сотрудник",
  buyer_unlimited: "безлимитный аккаунт",
  test_payment: "тестовый платёж",
  no_token_purchase: "не покупка пакета",
  referral_share_paid: "выплачена обычная реферальная доля",
  zero_base: "нулевая сумма",
  no_base: "сумма не определена",
  unsupported_currency: "сумма не определена",
  unsupported_provider: "сумма не определена",
  fraud: "мошенничество",
  refund: "возврат",
};

/** Причина статуса комиссии. «refund:<источник>» — «возврат: <источник>», текст после двоеточия как есть. */
export function commissionReason(reason: string | null | undefined): string {
  const code = String(reason ?? "");
  if (!code) return "";
  if (code.startsWith("refund:")) return `возврат: ${code.slice("refund:".length)}`;
  return COMMISSION_REASON[code] ?? code;
}

export const PROVIDERS: Record<string, string> = {
  freedompay: "FreedomPay",
  gopay: "Единый QR (GoPay)",
  yookassa: "ЮKassa",
  crypto_nowpayments: "Крипта",
  telegram_stars: "Telegram Stars",
};

export const MODE: Record<string, string> = {
  off: "Выключена",
  staff: "Только сотрудники",
  on: "Открыта всем",
};

export const LANG: Record<string, string> = {
  ru: "русский",
  en: "английский",
  kg: "кыргызский",
};

/** Причины выдачи Creator Credits, которые выбирает администратор (ТЗ п.21). Порядок — как в списке. */
export const GRANT_CATEGORIES: { key: string; label: string }[] = [
  { key: "start", label: "Старт" },
  { key: "activity", label: "Активность" },
  { key: "content", label: "За контент" },
  { key: "result", label: "За результат" },
  { key: "special", label: "Специальный бонус" },
  { key: "other", label: "Другое" },
];

/** Действия журнала (AdminActionLog.action) — в порядке вкладок раздела. */
export const LOG_ACTIONS: { key: string; label: string }[] = [
  { key: "application.approve", label: "Заявка: одобрена" },
  { key: "application.reject", label: "Заявка: отклонена" },
  { key: "application.block", label: "Заявка: отклонена с запретом" },
  { key: "application.unblock", label: "Заявка: запрет снят" },
  { key: "creator.level_change", label: "Креатор: смена уровня" },
  { key: "creator.block", label: "Креатор: блокировка" },
  { key: "creator.unblock", label: "Креатор: разблокировка" },
  { key: "creator.code_set", label: "Креатор: создал промокод" },
  { key: "creator.code_change", label: "Креатор: смена промокода" },
  { key: "creator.payout_address_change", label: "Креатор: смена адреса выплат" },
  { key: "publication.approve", label: "Публикация: подтверждена" },
  { key: "publication.reject", label: "Публикация: отклонена" },
  { key: "referral.rebind", label: "Реферал: перепривязка" },
  { key: "referral.clear_suspect", label: "Реферал: пометка снята" },
  { key: "commission.void", label: "Комиссия: аннулирована" },
  { key: "commission.release", label: "Комиссия: выпущена" },
  { key: "commission.restore", label: "Комиссия: восстановлена" },
  { key: "withdrawal.approve", label: "Выплата: одобрена" },
  { key: "withdrawal.reject", label: "Выплата: отклонена" },
  { key: "withdrawal.mark_paid", label: "Выплата: отмечена выплаченной" },
  { key: "withdrawal.fix_txid", label: "Выплата: исправлен TXID" },
  { key: "withdrawal.reopen", label: "Выплата: возвращена в работу" },
  { key: "credits.grant", label: "Creator Credits: начисление" },
  { key: "level.edit", label: "Уровень: изменены условия" },
  { key: "settings.edit", label: "Настройки программы" },
  { key: "payment.mark_refunded", label: "Платёж: отметка возврата" },
];

const LOG_ACTION_LABEL: Record<string, string> = Object.fromEntries(
  LOG_ACTIONS.map((item) => [item.key, item.label]),
);

export function logActionLabel(action: string | null | undefined): string {
  const code = String(action ?? "");
  return LOG_ACTION_LABEL[code] ?? code;
}

/** Подпись по таблице; кода в таблице нет — показываем сам код. */
export function labelFrom(table: Record<string, string>, key: string | null | undefined): string {
  const code = String(key ?? "");
  return table[code] ?? code;
}

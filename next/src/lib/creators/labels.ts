/**
 * EsAI Creators: подписи статусов, соцсетей, источников и причин — русские
 * тексты по умолчанию и перевод по ключу namespace `creators`.
 *
 * Ключ перевода = префикс + ключ таблицы (`status.withdrawal.paid`). Названия
 * уровней (CREATOR PRO…) приходят с сервера и не переводятся.
 */
import type { CrT } from "./errors";
import type { Network } from "./types";

/** `status.application.<status>` */
export const APPLICATION_STATUS_RU: Record<string, string> = {
  new: "Заявка на рассмотрении",
  approved: "Заявка одобрена",
  rejected: "Заявка отклонена",
  blocked: "Подача заявки закрыта",
};

/** `status.publication.<status>` */
export const PUBLICATION_STATUS_RU: Record<string, string> = {
  review: "На проверке",
  approved: "Подтверждено",
  rejected: "Отклонено",
};

/** `status.withdrawal.<status>` */
export const WITHDRAWAL_STATUS_RU: Record<string, string> = {
  review: "На проверке",
  approved: "Одобрено",
  paid: "Выплачено",
  rejected: "Отклонено",
};

/**
 * `status.commission.<key>`. У сервера статус accrued один, а человеку важно,
 * можно ли уже вывести: hold — срок холда не вышел, available — вышел.
 * reversed у сервера тоже один, а причин две: возврат платежа (reversed) и
 * любая другая отмена (cancelled) — про возврат говорим, только когда он был.
 * void — комиссию аннулировал администратор (см. commissionStatusKey).
 */
export const COMMISSION_STATUS_RU: Record<string, string> = {
  hold: "В холде",
  available: "Доступно",
  held: "На проверке",
  reversed: "Отменена: возврат платежа",
  cancelled: "Отменена",
  void: "Аннулирована",
};

/** `network.<network>` */
export const NETWORK_RU: Record<string, string> = {
  instagram: "Instagram",
  tiktok: "TikTok",
  youtube: "YouTube",
  telegram: "Telegram",
  facebook: "Facebook",
  x: "X (Twitter)",
  vk: "ВКонтакте",
  other: "Другое",
};

/** `source.<source>` — откуда пришёл реферал. */
export const SOURCE_RU: Record<string, string> = {
  link: "Ссылка",
  promo: "Промокод",
  bot: "Telegram-бот",
  admin: "Администратор",
};

/** `credits.category.<category>` — причина выдачи Creator Credits. */
export const CREDIT_CATEGORY_RU: Record<string, string> = {
  start: "Старт",
  activity: "Активность",
  content: "За контент",
  result: "За результат",
  special: "Специальный бонус",
  other: "Другое",
  merge: "Перенос с аккаунта Telegram",
};

/** `nav.<key>` — пункт меню. «Creators» — имя программы, одинаковое на всех языках. */
export const NAV_RU: Record<string, string> = {
  link: "Creators",
};

/** Соцсети в порядке списка выбора (значения поля network). */
export const NETWORKS: Network[] = ["instagram", "tiktok", "youtube", "telegram", "facebook", "x", "vk", "other"];

/** Префиксы ключей по виду статуса. */
const STATUS_TABLES = {
  application: { prefix: "status.application.", table: APPLICATION_STATUS_RU },
  publication: { prefix: "status.publication.", table: PUBLICATION_STATUS_RU },
  withdrawal: { prefix: "status.withdrawal.", table: WITHDRAWAL_STATUS_RU },
  commission: { prefix: "status.commission.", table: COMMISSION_STATUS_RU },
} as const;

export type StatusKind = keyof typeof STATUS_TABLES;

/**
 * Подпись по таблице: `t(prefix + key)` с русским текстом по умолчанию.
 * Ключа нет в таблице (сервер прислал новое значение) — показываем его как есть.
 */
export function labelOf(t: CrT, prefix: string, table: Record<string, string>, key: string | null | undefined): string {
  const name = String(key ?? "");
  const ru = table[name];
  if (ru === undefined) return name;
  const fn = t as (key: string, options?: Record<string, unknown>) => unknown;
  const out = fn(`${prefix}${name}`, { ns: "creators", defaultValue: ru });
  return typeof out === "string" && out ? out : ru;
}

/**
 * Ключ подписи комиссии. accrued: срок холда ещё не вышел — hold, вышел —
 * available. reversed: сервер прислал причину refund — reversed («возврат
 * платежа»), любую другую — cancelled (просто «Отменена»). Остальные статусы —
 * как у сервера.
 */
export function commissionStatusKey(
  commission: { status: string; available_at?: string | null; reason?: string | null },
  now: number = Date.now(),
): string {
  if (commission.status === "reversed") return commission.reason === "refund" ? "reversed" : "cancelled";
  if (commission.status !== "accrued") return commission.status;
  const at = commission.available_at ? Date.parse(commission.available_at) : NaN;
  return Number.isFinite(at) && at > now ? "hold" : "available";
}

/** Подпись статуса заявки, публикации, вывода или комиссии. */
export function statusLabel(t: CrT, kind: StatusKind, status: string | null | undefined): string {
  const { prefix, table } = STATUS_TABLES[kind];
  // Сырой accrued без даты холда: деньги начислены — показываем «Доступно».
  const key = kind === "commission" && status === "accrued" ? "available" : status;
  return labelOf(t, prefix, table, key);
}

export function networkLabel(t: CrT, network: string | null | undefined): string {
  return labelOf(t, "network.", NETWORK_RU, network);
}

export function sourceLabel(t: CrT, source: string | null | undefined): string {
  return labelOf(t, "source.", SOURCE_RU, source);
}

/** Причина выдачи кредитов; незнакомая категория — готовая подпись сервера. */
export function creditCategoryLabel(t: CrT, category: string | null | undefined, serverLabel?: string): string {
  const name = String(category ?? "");
  if (CREDIT_CATEGORY_RU[name] === undefined) return serverLabel || name;
  return labelOf(t, "credits.category.", CREDIT_CATEGORY_RU, name);
}

/** Пункт меню «Creators» — для файлов вне папок программы (Nav, Footer, сайдбар чата). */
export function navLabel(t: CrT): string {
  return labelOf(t, "nav.", NAV_RU, "link");
}

/**
 * Фильтры списка платежей в админке и разбор фильтра из адреса страницы.
 * Отдельный файл без React — чтобы разбор проверял node-тест (filters.test.mjs).
 */
export type PaymentFilter = { key: string; label: string; query: string };

export const FILTERS: PaymentFilter[] = [
  { key: "all", label: "Все", query: "" },
  { key: "qr", label: "Единый QR", query: "provider=gopay" },
  { key: "crypto", label: "Крипта", query: "provider=crypto_nowpayments" },
  { key: "card", label: "Карты (сом)", query: "provider=freedompay" },
  { key: "rub", label: "Карты (₽)", query: "provider=yookassa" },
  { key: "unpaid", label: "Без оплаты", query: "success=0" },
  { key: "review", label: "Нужен разбор", query: "needs_review=1" },
  { key: "test", label: "Тестовые", query: "is_test=1" },
  // Деньги пришли в GoPay, а кредиты не начислены: сюда ведёт красная строка из настроек.
  { key: "unsettled", label: "Оплачено, не зачислено", query: "unsettled=1" },
];

/**
 * Фильтр из параметров адреса. Нужен один случай: ссылка «Оплачено, но не
 * зачислено» из настроек (?unsettled=1) открывает список сразу с этим фильтром.
 *
 * Параметры берём у роутера (useSearchParams), а НЕ из window.location: при
 * переходе по <Link> Next меняет адрес уже после первого рендера новой
 * страницы, и window.location в этот момент ещё показывает старую — фильтр
 * молча терялся, и владелец видел весь список вместо двух платежей.
 */
export function filterFromParams(params: { get(name: string): string | null } | null | undefined): string {
  try {
    return params?.get("unsettled") === "1" ? "unsettled" : "all";
  } catch {
    return "all";
  }
}

/**
 * Причина разбора словами. Сервер кладёт в flags.needs_review короткий код
 * (например paid_after_refund_mark) — владельцу он ничего не говорит, а строка
 * означает «здесь деньги, посмотрите руками». Незнакомый код показываем как есть:
 * лучше сырой текст, чем пропавшая причина.
 */
const REVIEW_LABELS: Record<string, string> = {
  paid_after_refund_mark: "оплачен после отметки возврата",
  discount_reused: "скидка использована дважды",
  "mismatch:amount": "сумма не совпала с заказом",
  "mismatch:mode": "тестовый и боевой режим не совпали",
  "mismatch:test_non_staff": "тестовая оплата не сотрудником",
  "mismatch:order_id": "чужой номер заказа",
  "mismatch:payment_id": "чужой номер платежа",
  "mismatch:ids_missing": "GoPay не прислал номера платежа",
};

export function reviewLabel(flag: unknown): string {
  const code = String(flag ?? "");
  return REVIEW_LABELS[code] ?? code;
}

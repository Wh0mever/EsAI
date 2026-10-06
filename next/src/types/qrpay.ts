/**
 * Контракты оплаты по единому QR (core/payments/gopay).
 *
 * Суммы — СТРОКИ («392.00»): это деньги, и на экране они показываются ровно
 * так, как их назвал сервер, без пересчёта в браузере.
 */

/** Состояние счёта глазами экрана оплаты (сервер считает его сам: ui_state). */
export type QrUiState =
  | "awaiting_payment"
  | "processing"
  | "paid"
  | "expired"
  | "cancelled"
  | "failed";

/** Приложение банка: кнопка «открыть в приложении» на телефоне. */
export type QrApp = {
  code: string;
  name: string;
  /** готовая ссылка на оплату именно этого счёта (своя схема банка или https) */
  url: string;
  icon: string;
  /** false — банк не умеет на этой платформе; null — сервер не знает */
  ios: boolean | null;
  android: boolean | null;
};

/** POST /api/plans/purchase/ (method=elqr) и GET plans/purchase/qr/<order_id>/ */
export type QrInvoice = {
  kind: "qr";
  provider: string;
  resumed?: boolean;
  order_id: string;
  status: string;
  ui_state: QrUiState;
  amount: string;
  currency: string;
  /** цена до скидки «при уходе»; null — скидки нет */
  original_amount: string | null;
  discount_percent: number | null;
  package: { id: number | string | null; name: string; tokens: number; bonus_tokens: number };
  credits: { total: number; credited: number };
  /** data — строка, которая кодируется в QR целиком; пусто у тестового счёта без QR */
  qr: { data: string; image_url: string };
  apps: QrApp[];
  /** страница оплаты у GoPay: «все банки» и выход из встроенных браузеров */
  checkout_url: string;
  created_at: string | null;
  expires_at: string | null;
  /** время сервера на момент ответа — по нему правим отсчёт при сбитых часах */
  server_time: string | null;
  seconds_left: number;
  lifetime_seconds: number;
  is_test: boolean;
  can_cancel: boolean;
  return_to: string;
};

/** POST plans/purchase/qr/<order_id>/cancel/ */
export type QrCancelResult = {
  result: "cancelled" | "committed" | "closed" | "not_open" | "busy" | "retry";
  /** ЕДИНСТВЕННОЕ поле, по которому ветвится экран: true — уходим с QR, false — остаёмся */
  released: boolean;
  invoice: QrInvoice;
};

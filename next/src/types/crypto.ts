/**
 * Контракты криптооплаты (core/payments/crypto).
 *
 * Все суммы монет — СТРОКИ и остаются строками: у восьмнадцати знаков после
 * запятой в JS не хватает точности, а это число человек копирует в кошелёк.
 */

/** Список монет: GET /api/payments/crypto/currencies/ */
export type CryptoCurrency = {
  /** код процессора, напр. "usdttrc20" */
  code: string;
  coin: string;
  network: string;
  label: string;
  /** монета требует memo (TON, XRP) */
  extra_id_required: boolean;
  /** насколько дорога сеть: low | medium | high */
  network_cost: "low" | "medium" | "high" | string;
  popular: boolean;
  /** минимальная сумма в долларах, если процессор её назвал */
  min_usd: string | null;
};

export type CryptoCurrenciesResponse = {
  enabled: boolean;
  rate_kgs_to_usd?: string;
  /** комиссия процессора уже в сумме к переводу */
  fee_paid_by_user?: boolean;
  currencies: CryptoCurrency[];
};

/** Состояние счёта глазами экрана оплаты. */
export type CryptoUiState =
  | "awaiting_payment"
  | "confirming"
  | "partially_paid"
  | "paid"
  | "expired"
  | "failed";

/** POST /api/plans/purchase/ (pay_currency=USD) и GET purchase/crypto/<order_id>/ */
export type CryptoInvoice = {
  kind: "crypto";
  resumed?: boolean;
  order_id: string;
  provider: string;
  status: string;
  ui_state: CryptoUiState;
  package: { id: number | string | null; tokens: number; bonus_tokens: number };
  price: { kgs: string; usd: string; currency: string; rate_kgs_to_usd: string };
  pay: {
    currency: string;
    coin: string;
    network: string;
    label: string;
    address: string;
    extra_id: string | null;
    extra_id_required: boolean;
    amount: string;
    amount_paid: string;
    amount_remaining: string;
  };
  credits: { total: number; credited: number };
  tx_hash: string | null;
  explorer_url: string | null;
  confirmations: number | null;
  created_at: string | null;
  expires_at: string | null;
  seconds_left: number;
  last_checked_at: string | null;
  return_to: string;
};

/** Ошибки создания счёта (detail + подсказки). */
export type CryptoPurchaseError = {
  detail: string;
  min_usd?: string;
  amount_usd?: string;
};

/** GET /api/plans/purchase/pending/ */
export type PendingPayment =
  | {
      kind: "card";
      order_id: string;
      amount: string;
      currency: string;
      package: string;
      redirect_url: string;
      created_at: string;
    }
  | {
      kind: "crypto";
      order_id: string;
      amount: string;
      currency: string;
      package: string;
      redirect_url: null;
      status_url: string;
      coin: string;
      network: string;
      pay_amount: string;
      amount_remaining: string;
      expires_at: string | null;
      created_at: string;
    }
  | {
      /** единый QR (GoPay): продолжается на нашем экране, по номеру заказа */
      kind: "qr";
      order_id: string;
      amount: string;
      currency: string;
      package: string;
      redirect_url: null;
      status_url: string;
      expires_at: string | null;
      /** время сервера на момент ответа — отсчёт баннера идёт по нему; старый сервер не присылает */
      server_time?: string | null;
      created_at: string;
    };

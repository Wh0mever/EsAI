// lib/freedompay/pay.ts
// Freedom Pay: SDK wait/setup, tokenize for card binding, charge with 3DS.

export type CardPayload = {
  number: string;      // digits only
  holder: string;
  expMonth: string;    // "MM"
  expYear: string;     // "YY" or "YYYY"
  cvv: string;         // not used for tokenize
};

export type PaymentOptions = {
  orderId: string;
  amount: number;      // SDK uses integer units (1 == 1 KGS)
  currency: string;    // "KGS" | "USD" | ...
  description?: string;
  test?: boolean;      // true -> test=1
  user?: { email?: string; phone?: string };
  autoClearing?: 0 | 1;
};

export type PayResult = {
  payment_status?: "success" | "error" | "need_confirm";
  [k: string]: any;
};

declare global {
  interface Window {
    FreedomPaySDK?: any;
    FreedomPay?: any;
    freedomPay?: any;
    __fp_script_loaded__?: boolean;
  }
}

function isFPDebug() {
  const v = (process.env.NEXT_PUBLIC_FREEDOM_PAY_DEBUG || "").toLowerCase();
  return v === "1" || v === "true" || v === "full" || v === "on";
}

function isFPTestMode(): 0 | 1 {
  const raw = (process.env.NEXT_PUBLIC_FREEDOM_PAY_TEST
    || (process.env as any).NEXT_PUBLIC_FREEDOM_PAY_TEST_MODE
    || (process.env as any).NEXT_PUBLIC_FREEDOMPAY_TEST
    || "").toString().trim().toLowerCase();
  if (raw === "1" || raw === "true" || raw === "yes" || raw === "on" || raw === "test" || raw === "sandbox") {
    return 1;
  }
  return 0;
}

function maskPan(pan: string) {
  const d = (pan || "").replace(/\D+/g, "");
  if (d.length <= 8) return d.replace(/\d/g, "*");
  return d.slice(0, 6) + d.slice(6, -4).replace(/\d/g, "*") + d.slice(-4);
}

function mask(str: string) {
  return (str || "").replace(/./g, "*");
}

/* ---------- internals ---------- */
async function waitFreedomPaySDK(timeoutMs = 12000): Promise<any> {
  if (typeof window === "undefined") throw new Error("FreedomPaySDK must run in browser");
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const check = () => {
      const g = window.FreedomPaySDK || window.FreedomPay || window.freedomPay;
      if (g) {
        if (!window.FreedomPaySDK) window.FreedomPaySDK = g;
        resolve(window.FreedomPaySDK);
        return;
      }
      if (Date.now() - start > timeoutMs) {
        const loaded = !!window.__fp_script_loaded__;
        reject(new Error(loaded ? "FreedomPaySDK global not exported" : "FreedomPaySDK is not loaded"));
        return;
      }
      requestAnimationFrame(check);
    };
    check();
  });
}

// turn dotenv string with literal '\n' into real newlines; trim spaces
function normalizePemLike(str: string) {
  let s = (str || "").replace(/\\n/g, "\n").replace(/\\r/g, "\r").trim();
  if ((s.startsWith("'") && s.endsWith("'")) || (s.startsWith('"') && s.endsWith('"'))) {
    s = s.slice(1, -1).trim();
  }
  return s;
}

// get public key for SDK.setup: return base64-only content (strip PEM headers)
function getPublicKeyForSDK(): string {
  const raw = process.env.NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY || "";
  let pk = normalizePemLike(raw);
  if (pk.includes("BEGIN PUBLIC KEY") && pk.includes("END PUBLIC KEY")) {
    const m = pk.match(/-----BEGIN PUBLIC KEY-----([\s\S]*?)-----END PUBLIC KEY-----/);
    if (m) pk = m[1];
  }
  pk = pk.replace(/\s+/g, "");
  return pk;
}

function assertEnv() {
  if (!process.env.NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY) throw new Error("Missing NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY");
  if (!process.env.NEXT_PUBLIC_FREEDOM_PAY_TOKEN) throw new Error("Missing NEXT_PUBLIC_FREEDOM_PAY_TOKEN");
}

function normalizeYear(y: string) {
  const yy = (y || "").trim();
  return yy.length === 4 ? yy.slice(2) : yy;
}

function validateCardForCharge(c: CardPayload) {
  if (!/^\d{13,19}$/.test(c.number)) throw new Error("Invalid card number");
  if (!/^\d{2}$/.test(c.expMonth) || +c.expMonth < 1 || +c.expMonth > 12) throw new Error("Invalid month");
  if (!/^\d{2,4}$/.test(c.expYear)) throw new Error("Invalid year");
  if (!/^\d{3,4}$/.test(c.cvv)) throw new Error("Invalid CVV");
  if (!c.holder?.trim()) throw new Error("Holder required");
}

function validateCardForTokenize(c: { number: string; holder: string; expMonth: string; expYear: string }) {
  if (!/^\d{13,19}$/.test(c.number)) throw new Error("Invalid card number");
  if (!/^\d{2}$/.test(c.expMonth) || +c.expMonth < 1 || +c.expMonth > 12) throw new Error("Invalid month");
  if (!/^\d{2,4}$/.test(c.expYear)) throw new Error("Invalid year");
  if (!c.holder?.trim()) throw new Error("Holder required");
}

async function setupSDK() {
  assertEnv();
  const sdk = await waitFreedomPaySDK();
  const publicKey = getPublicKeyForSDK();
  const token = (process.env.NEXT_PUBLIC_FREEDOM_PAY_TOKEN as string).trim();
  try {
    if (isFPDebug()) {
      console.log("[FP] setup", { publicKeyLength: publicKey.length, token: mask(token) });
    }
  } catch {}
  sdk.setup(publicKey, token); // idempotent on provider side
  return sdk;
}
/* -------------------------------- */

/** Tokenize only: get card token for binding, no payment, no 3DS */
export async function tokenizeBankCard(card: {
  number: string;
  holder: string;
  expMonth: string;
  expYear: string; // YY or YYYY
  cvv?: string;    // optional; some providers require CVV for tokenize
}): Promise<string> {
  validateCardForTokenize(card);
  const sdk = await setupSDK();

  const JSTokenizeOptionsBankCard: any = {
    type: "bank_card",
    options: {
      card_number: card.number.replace(/\D+/g, ""),
      card_holder_name: card.holder.trim().replace(/\s+/g, " ").toUpperCase(),
      card_exp_month: card.expMonth.trim().padStart(2, "0"),
      card_exp_year: normalizeYear(card.expYear.trim()),
    },
  };
  if (card.cvv && /^\d{3,4}$/.test(card.cvv)) {
    JSTokenizeOptionsBankCard.options.card_cvv = Number(card.cvv.trim());
  }
  try {
    if (isFPDebug()) {
      console.log("[FP] tokenize request", {
        type: JSTokenizeOptionsBankCard.type,
        options: {
          card_number: maskPan(JSTokenizeOptionsBankCard.options.card_number),
          card_holder_name: JSTokenizeOptionsBankCard.options.card_holder_name,
          card_exp_month: JSTokenizeOptionsBankCard.options.card_exp_month,
          card_exp_year: JSTokenizeOptionsBankCard.options.card_exp_year,
          card_cvv: JSTokenizeOptionsBankCard.options.card_cvv ? mask(String(JSTokenizeOptionsBankCard.options.card_cvv)) : undefined,
        },
      });
    }
  } catch {}

  const testFlag = isFPTestMode();
  const res = await (testFlag ? sdk.tokenize(JSTokenizeOptionsBankCard, { test: testFlag }) : sdk.tokenize(JSTokenizeOptionsBankCard));
  try {
    if (isFPDebug()) {
      console.log("[FP] tokenize response", { ok: !!res?.token, tokenLength: res?.token ? String(res.token).length : 0, raw: res });
    }
  } catch {}
  if (!res?.token) throw new Error("Tokenize failed");
  return String(res.token);
}

/** One-shot charge: direct payment with 3DS if required */
export async function payWithBankCard(
  card: CardPayload,
  opts: PaymentOptions,
  threeDSContainerId = "fp-3ds"
): Promise<PayResult> {
  validateCardForCharge(card);
  const sdk = await setupSDK();

  const JSPaymentOptions = {
    order_id: opts.orderId,
    auto_clearing: opts.autoClearing ?? 0,
    amount: opts.amount,
    currency: opts.currency,
    description: opts.description ?? "",
    test: opts.test ? 1 : 0,
    options: {
      custom_params: {},
      user: { email: opts.user?.email ?? "", phone: opts.user?.phone ?? "" },
    },
  };

  const JSTransactionOptionsBankCard = {
    type: "bank_card",
    options: {
      card_number: card.number.replace(/\D+/g, ""),
      card_holder_name: card.holder.trim(),
      card_exp_month: card.expMonth.trim(),
      card_exp_year: normalizeYear(card.expYear.trim()),
      card_cvv: Number(card.cvv.trim()),
    },
  };
  try {
    if (isFPDebug()) {
      console.log("[FP] charge request", {
        payment: {
          ...JSPaymentOptions,
        },
        transaction: {
          type: JSTransactionOptionsBankCard.type,
          options: {
            card_number: maskPan(JSTransactionOptionsBankCard.options.card_number),
            card_holder_name: JSTransactionOptionsBankCard.options.card_holder_name,
            card_exp_month: JSTransactionOptionsBankCard.options.card_exp_month,
            card_exp_year: JSTransactionOptionsBankCard.options.card_exp_year,
            card_cvv: mask(String(JSTransactionOptionsBankCard.options.card_cvv)),
          },
        },
      });
    }
  } catch {}

  let res: PayResult = await sdk.charge(JSPaymentOptions, JSTransactionOptionsBankCard);
  try { if (isFPDebug()) console.log("[FP] charge response", res); } catch {}
  if (res?.payment_status === "need_confirm") {
    res = await sdk.confirmInIframe(res, threeDSContainerId);
    try { if (isFPDebug()) console.log("[FP] confirmInIframe response", res); } catch {}
  }
  return res;
}

/** Recurring/auto charge by previously saved token (безакцептный). */
export async function payByCardToken(
  token: string,
  opts: PaymentOptions,
  threeDSContainerId = "fp-3ds"
): Promise<PayResult> {
  const sdk = await setupSDK();

  const JSPaymentOptions = {
    order_id: opts.orderId,
    auto_clearing: opts.autoClearing ?? 0,
    amount: opts.amount,
    currency: opts.currency,
    description: opts.description ?? "",
    test: opts.test ? 1 : 0,
    options: {
      custom_params: {},
      user: { email: opts.user?.email ?? "", phone: opts.user?.phone ?? "" },
    },
  };

  const JSTransactionOptionsToken = {
    type: "bank_card_token",
    options: { token },
  };
  try {
    if (isFPDebug()) {
      console.log("[FP] charge by token request", {
        payment: JSPaymentOptions,
        transaction: JSTransactionOptionsToken,
      });
    }
  } catch {}

  // For безакцептных платежей 3DS should not be required.
  // However, if provider still returns need_confirm, handle via iframe to be safe.
  let res: PayResult = await sdk.charge(JSPaymentOptions, JSTransactionOptionsToken);
  try { if (isFPDebug()) console.log("[FP] charge by token response", res); } catch {}
  if (res?.payment_status === "need_confirm") {
    res = await sdk.confirmInIframe(res, threeDSContainerId);
    try { if (isFPDebug()) console.log("[FP] confirmInIframe response", res); } catch {}
  }
  return res;
}

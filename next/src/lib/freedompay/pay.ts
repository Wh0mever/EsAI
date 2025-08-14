// lib/freedompay/pay.ts
// Single-file Freedom Pay wrapper: waits for SDK, normalizes public key, runs 3DS.

export type CardPayload = {
  number: string;    // digits only
  holder: string;
  expMonth: string;  // "MM"
  expYear: string;   // "YY" or "YYYY"
  cvv: string;
};

export type PaymentOptions = {
  orderId: string;
  amount: number;    // minor units (e.g., 1 == 1 KGS in FP SDK)
  currency: string;  // "KGS" | "USD" | ...
  description?: string;
  test?: boolean;    // true -> test=1
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

/** Wait until SDK global appears (supports multiple possible names). */
async function waitFreedomPaySDK(timeoutMs = 12000): Promise<any> {
  if (typeof window === "undefined") {
    throw new Error("FreedomPaySDK must run in browser");
  }
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const check = () => {
      const g = window.FreedomPaySDK || window.FreedomPay || window.freedomPay;
      if (g) {
        if (!window.FreedomPaySDK) window.FreedomPaySDK = g; // alias
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

/** Turn dotenv string with literal '\n' into real newlines; trim spaces. */
function normalizePemLike(str: string) {
  let s = (str || "").replace(/\\n/g, "\n").replace(/\\r/g, "\r").trim();
  if ((s.startsWith("'") && s.endsWith("'")) || (s.startsWith('"') && s.endsWith('"'))) {
    s = s.slice(1, -1).trim();
  }
  return s;
}

/** Get public key for SDK.setup: accept both PEM and base64. */
function getPublicKeyForSDK(): string {
  const raw = process.env.NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY || "";
  const pk = normalizePemLike(raw);
  if (pk.includes("BEGIN PUBLIC KEY") && pk.includes("END PUBLIC KEY")) return pk;
  if (/^[A-Za-z0-9+/=]+$/.test(pk) && pk.length > 100) return pk;
  return pk.replace(/\s+/g, "");
}

function assertEnv() {
  if (!process.env.NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY) throw new Error("Missing NEXT_PUBLIC_FREEDOM_PAY_PUBLIC_KEY");
  if (!process.env.NEXT_PUBLIC_FREEDOM_PAY_TOKEN) throw new Error("Missing NEXT_PUBLIC_FREEDOM_PAY_TOKEN");
}

function normalizeYear(y: string) {
  const yy = y.trim();
  return yy.length === 4 ? yy.slice(2) : yy;
}

function validateCard(c: CardPayload) {
  if (!/^\d{13,19}$/.test(c.number)) throw new Error("Invalid card number");
  if (!/^\d{2}$/.test(c.expMonth) || +c.expMonth < 1 || +c.expMonth > 12) throw new Error("Invalid month");
  if (!/^\d{2,4}$/.test(c.expYear)) throw new Error("Invalid year");
  if (!/^\d{3,4}$/.test(c.cvv)) throw new Error("Invalid CVV");
  if (!c.holder.trim()) throw new Error("Holder required");
}

/** Main API */
export async function payWithBankCard(
  card: CardPayload,
  opts: PaymentOptions,
  threeDSContainerId = "fp-3ds"
): Promise<PayResult> {
  const sdk = await waitFreedomPaySDK();  // wait for global
  assertEnv();
  validateCard(card);

  const publicKey = getPublicKeyForSDK();
  const token = (process.env.NEXT_PUBLIC_FREEDOM_PAY_TOKEN as string).trim();

  // Idempotent init on provider side
  sdk.setup(publicKey, token);

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
      card_number: card.number,
      card_holder_name: card.holder.trim(),
      card_exp_month: card.expMonth.trim(),
      card_exp_year: normalizeYear(card.expYear.trim()),
      card_cvv: Number(card.cvv.trim()),
    },
  };

  let res: PayResult = await sdk.charge(JSPaymentOptions, JSTransactionOptionsBankCard);

  if (res?.payment_status === "need_confirm") {
    res = await sdk.confirmInIframe(res, threeDSContainerId);
  }

  return res;
}

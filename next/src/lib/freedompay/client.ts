// lib/freedompay/client.ts
declare global {
  interface Window {
    FreedomPaySDK?: any;
    FreedomPay?: any;
    freedomPay?: any;
    __fp_script_loaded__?: boolean;
  }
}

function normalizePemLike(str: string) {
  let s = (str || "").replace(/\\n/g, "\n").replace(/\\r/g, "\r").trim();
  if ((s.startsWith("'") && s.endsWith("'")) || (s.startsWith('"') && s.endsWith('"'))) s = s.slice(1, -1).trim();
  return s;
}

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

async function waitSDK(timeoutMs = 12000): Promise<any> {
  if (typeof window === "undefined") throw new Error("FreedomPaySDK must run in browser");
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const check = () => {
      const g = window.FreedomPaySDK || window.FreedomPay || window.freedomPay;
      if (g) {
        if (!window.FreedomPaySDK) window.FreedomPaySDK = g;
        return resolve(window.FreedomPaySDK);
      }
      if (Date.now() - start > timeoutMs) {
        const loaded = !!window.__fp_script_loaded__;
        return reject(new Error(loaded ? "FreedomPaySDK global not exported" : "FreedomPaySDK is not loaded"));
      }
      requestAnimationFrame(check);
    };
    check();
  });
}

/** idempotent setup */
async function setupSDK() {
  assertEnv();
  const sdk = await waitSDK();
  const publicKey = getPublicKeyForSDK();
  const token = (process.env.NEXT_PUBLIC_FREEDOM_PAY_TOKEN as string).trim();
  sdk.setup(publicKey, token);
  return sdk;
}

/** Только токенизация – для «привязки» карты */
export async function tokenizeCard(input: {
  number: string;
  expMonth: string;
  expYear: string; // YY или YYYY
  holder: string;
}) {
  const sdk = await setupSDK();
  const payload = {
    type: "bank_card",
    options: {
      card_number: input.number.replace(/\D+/g, ""),
      card_holder_name: input.holder.trim(),
      card_exp_month: input.expMonth.trim(),
      card_exp_year: input.expYear.trim().slice(-2),
    },
  };
  const resp = await sdk.tokenize(payload);
  if (!resp?.token) throw new Error("Tokenize failed");
  return { token: String(resp.token) };
}

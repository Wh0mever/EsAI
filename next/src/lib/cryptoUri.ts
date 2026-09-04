/**
 * Ссылки для кошельков и вспомогательные форматы.
 *
 * QR-код с одним адресом работает везде, но заставляет человека вбивать сумму
 * руками — а ошибка в сумме превращается в недоплату. Поэтому там, где схема
 * реально поддерживается кошельками, кодируем адрес ВМЕСТЕ с суммой.
 *
 * Где поддержки нет (жетоны: USDT в TRON, BSC, TON), честно оставляем голый
 * адрес: полурабочая ссылка хуже понятной инструкции «отправьте ровно столько».
 */

export type WalletUriInput = {
  payCurrency: string;
  coin: string;
  network: string;
  address: string;
  amount: string;
  memo?: string | null;
};

export type WalletUri = {
  uri: string;
  /** true — ссылку можно открыть кошельком, false — это просто адрес */
  deepLink: boolean;
};

/**
 * Перевод суммы в наименьшие единицы (веи, нанотоны) через BigInt.
 * Через число нельзя: 0.1 + 0.2 в JS уже не 0.3, а тут это чужие деньги.
 */
export function toMinorUnits(amount: string, decimals: number): string {
  const clean = String(amount || "0").trim();
  if (!/^\d*\.?\d*$/.test(clean) || clean === "" || clean === ".") return "0";
  const [whole, fraction = ""] = clean.split(".");
  const padded = (fraction + "0".repeat(decimals)).slice(0, decimals);
  const digits = `${whole || "0"}${padded}`.replace(/^0+(?=\d)/, "");
  try {
    return BigInt(digits).toString();
  } catch {
    return "0";
  }
}

const plain = (address: string): WalletUri => ({ uri: address, deepLink: false });

export function buildWalletUri(input: WalletUriInput): WalletUri {
  const code = String(input.payCurrency || "").toLowerCase();
  const address = String(input.address || "");
  const amount = String(input.amount || "");
  if (!address) return plain("");

  switch (code) {
    case "btc":
      return { uri: `bitcoin:${address}?amount=${amount}`, deepLink: true };
    case "ltc":
      return { uri: `litecoin:${address}?amount=${amount}`, deepLink: true };
    case "doge":
      return { uri: `dogecoin:${address}?amount=${amount}`, deepLink: true };
    case "eth":
      // EIP-681: сумма в веях, сеть 1 (Ethereum mainnet).
      return { uri: `ethereum:${address}@1?value=${toMinorUnits(amount, 18)}`, deepLink: true };
    case "sol":
      return { uri: `solana:${address}?amount=${amount}`, deepLink: true };
    case "xmr":
      return { uri: `monero:${address}?tx_amount=${amount}`, deepLink: true };
    case "ton": {
      const memo = input.memo ? `&text=${encodeURIComponent(input.memo)}` : "";
      return {
        uri: `ton://transfer/${address}?amount=${toMinorUnits(amount, 9)}${memo}`,
        deepLink: true,
      };
    }
    default:
      // USDT/USDC в любой сети, TRX, BNB, XRP: жетоны и сети, где ссылку
      // понимают единицы кошельков. QR с адресом — самое надёжное.
      return plain(address);
  }
}

/** Короткий вид адреса — только для тесных мест (баннер), не для экрана оплаты. */
export function shortAddress(address: string, head = 6, tail = 6): string {
  const value = String(address || "");
  if (value.length <= head + tail + 3) return value;
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}

/** Секунды -> «14:32» (и «1:02:15», если счёт длиннее часа). */
export function formatCountdown(totalSeconds: number): string {
  const left = Math.max(0, Math.floor(totalSeconds || 0));
  const hours = Math.floor(left / 3600);
  const minutes = Math.floor((left % 3600) / 60);
  const seconds = left % 60;
  const mm = String(minutes).padStart(2, "0");
  const ss = String(seconds).padStart(2, "0");
  return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`;
}

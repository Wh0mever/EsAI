/**
 * Последний криптосчёт этой вкладки.
 *
 * Основной источник незавершённой оплаты — сервер (GET purchase/pending/).
 * Это подстраховка на случай, когда вкладку перезагрузили раньше, чем ответ
 * успел прийти: адрес и сумма всё равно живут на сервере, здесь только номер
 * заказа, чтобы открыть тот же экран.
 *
 * sessionStorage, а не localStorage: счёт живёт час и относится к этой вкладке.
 */
export type CryptoSession = {
  order_id: string;
  package_name?: string;
  coin?: string;
  network?: string;
  saved_at: number;
};

const KEY = "esai.crypto.order";
// Дольше самого счёта хранить нечего.
const MAX_AGE_MS = 2 * 60 * 60 * 1000;

export function saveCryptoSession(value: Omit<CryptoSession, "saved_at">): void {
  try {
    window.sessionStorage.setItem(
      KEY,
      JSON.stringify({ ...value, saved_at: Date.now() } satisfies CryptoSession)
    );
  } catch {
    // приватный режим Safari и подобное — молча живём без подсказки
  }
}

export function readCryptoSession(): CryptoSession | null {
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CryptoSession;
    if (!parsed?.order_id) return null;
    if (Date.now() - (parsed.saved_at || 0) > MAX_AGE_MS) {
      clearCryptoSession();
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function clearCryptoSession(): void {
  try {
    window.sessionStorage.removeItem(KEY);
  } catch {
    // ничего не делаем: это всего лишь подсказка
  }
}

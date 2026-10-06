/**
 * Последний QR-счёт этого браузера.
 *
 * Основной сценарий на телефоне: человек уходит в приложение банка, платит и
 * возвращается. Браузер к этому времени мог выгрузить вкладку (iOS при
 * нехватке памяти, встроенные браузеры) или открыть сайт в новой — страница
 * загружается заново, окна с QR нет. Сервер в «незавершённых» знает только
 * НЕоплаченные счета, так что без этой подсказки только что заплативший видел
 * бы пустую витрину — а это момент, когда люди платят второй раз.
 *
 * Поэтому localStorage, а не sessionStorage (как у крипты): в новой вкладке
 * sessionStorage пуст. Здесь только номер заказа — что с ним на самом деле,
 * всегда спрашиваем у сервера (useQrReturn).
 */
export type QrSession = {
  order_id: string;
  package_name?: string;
  saved_at: number;
};

const KEY = "esai.qr.order";
// QR живёт минуты; два часа — запас на «заплатил и вернулся не сразу».
const MAX_AGE_MS = 2 * 60 * 60 * 1000;

export function saveQrSession(value: Omit<QrSession, "saved_at">): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify({ ...value, saved_at: Date.now() } satisfies QrSession));
  } catch {
    // приватный режим Safari и подобное — молча живём без подсказки
  }
}

export function readQrSession(): QrSession | null {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as QrSession;
    if (!parsed || typeof parsed.order_id !== "string" || !parsed.order_id) return null;
    if (Date.now() - (Number(parsed.saved_at) || 0) > MAX_AGE_MS) {
      clearQrSession();
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

/**
 * Забыть подсказку. С номером заказа — только если хранится именно он: экран
 * старого счёта не должен стирать подсказку о новом, созданном позже.
 */
export function clearQrSession(orderId?: string): void {
  try {
    if (orderId) {
      const raw = window.localStorage.getItem(KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as QrSession | null;
      if (parsed && typeof parsed.order_id === "string" && parsed.order_id !== orderId) return;
    }
    window.localStorage.removeItem(KEY);
  } catch {
    // ничего не делаем: это всего лишь подсказка
  }
}

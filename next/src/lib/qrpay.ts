/**
 * Чистые помощники экрана оплаты по QR: без React, без window — их гоняют
 * тесты (qrpay.test.mjs) прямо в Node.
 *
 * Всё, что здесь «определяется» (платформа, встроенный браузер), — лучшая
 * догадка по строке user-agent. Поэтому на экране от догадки ничего не
 * ЗАВИСИТ: кнопки банков — обычные ссылки, QR показан всегда, кнопка страницы
 * оплаты есть всегда.
 */
import type { QrApp, QrInvoice, QrUiState } from "@/types/qrpay";

export type QrPlatform = "ios" | "android" | "desktop";
export type QrEmbed = "tg_miniapp" | "inapp" | "browser";

/** Сколько кнопок банков сервер отдаёт максимум — клиент ничего сверх не режет. */
const APPS_MAX = 24;

export function detectPlatform(ua: string, platform?: string, maxTouchPoints?: number): QrPlatform {
  const agent = String(ua || "");
  // iPad с «настольным» Safari называет себя Mac — выдаёт его только тач-экран.
  if (/iP(hone|ad|od)/.test(agent)) return "ios";
  if (platform === "MacIntel" && Number(maxTouchPoints || 0) > 1) return "ios";
  if (/Android/i.test(agent)) return "android";
  return "desktop";
}

type TelegramWindow = { Telegram?: { WebApp?: { initData?: unknown } } } | null | undefined;

export function detectEmbed(ua: string, win?: TelegramWindow): QrEmbed {
  // Скрипт Telegram подключён и на обычном сайте — Mini App это только тогда,
  // когда Telegram реально передал подписанные данные.
  const initData = win?.Telegram?.WebApp?.initData;
  if (typeof initData === "string" && initData.length > 0) return "tg_miniapp";
  if (/Instagram|FBAN|FBAV|FB_IAB|Line\/|Telegram|; wv\)/.test(String(ua || ""))) return "inapp";
  return "browser";
}

const UNSAFE_SCHEMES = new Set(["javascript", "data", "vbscript", "file", "blob", "about"]);

/**
 * Ссылку банка отдаёт сторонний сервис, а мы ставим её в href. Своя схема
 * (mbank://…) — норма, а вот исполняемые и локальные схемы не пускаем.
 */
export function isSafeAppUrl(url: string): boolean {
  if (typeof url !== "string" || url.length === 0 || url.length > 2000) return false;
  const match = /^([a-z][a-z0-9+.\-]{1,31}):/i.exec(url);
  if (!match) return false;
  return !UNSAFE_SCHEMES.has(match[1].toLowerCase());
}

/** https-ссылка (страница оплаты, картинка QR, значок банка) — и ничего кроме. */
export function isHttpsUrl(url: unknown): url is string {
  return typeof url === "string" && url.length <= 2000 && /^https:\/\/[^\s/]+/i.test(url);
}

export function appsForPlatform(apps: QrApp[], platform: QrPlatform): QrApp[] {
  // На компьютере приложение банка не откроешь — там сканируют код телефоном.
  if (platform === "desktop" || !Array.isArray(apps)) return [];
  const out: QrApp[] = [];
  for (const app of apps) {
    if (!app || typeof app.url !== "string") continue;
    // Прячем только явное «не работает»: null значит «сервер не знает».
    if (platform === "ios" ? app.ios === false : app.android === false) continue;
    if (!isSafeAppUrl(app.url)) continue;
    out.push(app);
    if (out.length >= APPS_MAX) break;
  }
  return out;
}

/**
 * Первые `visible` банков сразу, остальные — под «Показать все банки».
 * Один-единственный спрятанный банк прятать незачем: кнопка «показать»
 * заняла бы столько же места, сколько он сам.
 */
export function splitApps(apps: QrApp[], visible = 8): { main: QrApp[]; rest: QrApp[] } {
  const list = Array.isArray(apps) ? apps : [];
  if (list.length <= visible + 1) return { main: list, rest: [] };
  return { main: list.slice(0, visible), rest: list.slice(visible) };
}

/**
 * Банки, чей значок лежит у нас: public/images/banks/<код>.webp — те же значки
 * приложений, что отдаёт GoPay. Свой файл не зависит от чужого сервера и виден
 * сразу: банк узнают по значку, а не по первой букве названия.
 */
const LOCAL_BANK_ICONS = new Set([
  "mbank",
  "odengi",
  "bakaibank",
  "optima",
  "megapay",
  "kompanion",
  "elcart",
  "demirbank",
  "kicb",
  "eldik",
  "nambaone",
  "simbank",
]);

const bankKey = (code: unknown): string => (typeof code === "string" ? code.trim().toLowerCase() : "");

/** Адрес нашего значка банка; пусто — такого банка у нас нет. */
export function localBankIcon(code: unknown): string {
  const key = bankKey(code);
  return LOCAL_BANK_ICONS.has(key) ? `/images/banks/${key}.webp` : "";
}

/**
 * Откуда брать значок банка, по порядку: наш файл, затем https-адрес от
 * сервера (банк, которого у нас ещё нет). Пустой список — рисуем букву.
 */
export function bankIconSources(code: unknown, remote?: unknown): string[] {
  const out: string[] = [];
  const local = localBankIcon(code);
  if (local) out.push(local);
  if (isHttpsUrl(remote)) out.push(remote);
  return out;
}

/** Главный банк страны («есть у каждого»): его кнопка первая и крупнее прочих. */
export const FEATURED_BANK = "mbank";

/** Вынуть главный банк из списка; остальные остаются в порядке сервера. */
export function splitFeatured(apps: QrApp[], code: string = FEATURED_BANK): { featured: QrApp | null; others: QrApp[] } {
  const list = Array.isArray(apps) ? apps : [];
  const index = list.findIndex((app) => bankKey(app?.code) === code);
  if (index < 0) return { featured: null, others: list };
  return { featured: list[index], others: [...list.slice(0, index), ...list.slice(index + 1)] };
}

/** Банк как значок с подписью — без ссылки на оплату. */
export type BankBadge = { code: string; name: string; icon: string };

/**
 * Банки, которые в Кыргызстане знает почти каждый. По их значкам «единый QR»
 * узнают ещё до того, как счёт создан и список банков пришёл с сервера.
 */
export const SHOWCASE_BANKS: BankBadge[] = [
  { code: "mbank", name: "MBank", icon: "" },
  { code: "odengi", name: "О!Деньги", icon: "" },
  { code: "bakaibank", name: "Bakai", icon: "" },
  { code: "optima", name: "Optima24", icon: "" },
  { code: "megapay", name: "MegaPay", icon: "" },
];

/**
 * Ряд «Работает с» под QR на компьютере: банки этого счёта, у которых есть
 * значок (буквы в таком ряду ничего не говорят). Списка нет — известные всем.
 * Не влезли в `max` — последнее место занимает счётчик «+N».
 */
export function worksWithBanks(apps: QrApp[], max = 7): { shown: BankBadge[]; more: number } {
  const seen = new Set<string>();
  const withIcon: BankBadge[] = [];
  let total = 0;
  for (const app of Array.isArray(apps) ? apps : []) {
    const key = bankKey(app?.code);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    total += 1;
    if (bankIconSources(key, app.icon).length === 0) continue;
    withIcon.push({ code: key, name: typeof app.name === "string" && app.name ? app.name : key, icon: app.icon });
  }
  if (withIcon.length === 0) return { shown: SHOWCASE_BANKS.slice(0, Math.max(1, max)), more: 0 };
  const limit = Math.max(1, max);
  if (total <= limit) return { shown: withIcon, more: total - withIcon.length };
  const shown = withIcon.slice(0, limit - 1);
  return { shown, more: total - shown.length };
}

/**
 * Какая доля срока QR ещё впереди (0…1) — для полоски под таймером.
 * Срок неизвестен — null: полоску не рисуем, чем показывать выдуманную.
 */
export function lifetimeLeft(secondsLeftNow: number, lifetimeSeconds: number): number | null {
  if (!Number.isFinite(lifetimeSeconds) || lifetimeSeconds <= 0) return null;
  if (!Number.isFinite(secondsLeftNow) || secondsLeftNow <= 0) return 0;
  return Math.min(1, secondsLeftNow / lifetimeSeconds);
}

/** Пауза до следующего опроса. Первые две минуты — самые частые: человек платит. */
export function pollDelayMs(elapsedMs: number, failures: number, state: QrUiState): number {
  let base: number;
  if (state === "awaiting_payment") base = elapsedMs < 2 * 60 * 1000 ? 3000 : 5000;
  else if (state === "processing") base = 5000;
  else base = 10000;
  if (failures > 0) return Math.min(20000, base * 2 ** failures);
  return base;
}

/** После закрытия QR ещё минуту смотрим: оплата могла уйти на последней секунде. */
const EXPIRED_GRACE_MS = 60 * 1000;
/** «Зачисляем» дольше пяти минут — это уже разбор вручную, опрос не поможет. */
const PROCESSING_LIMIT_MS = 5 * 60 * 1000;

export function shouldStopPolling(
  state: QrUiState,
  expiresAtMs: number,
  nowMs: number,
  startedProcessingMs?: number
): boolean {
  if (state === "paid" || state === "failed" || state === "cancelled") return true;
  if (state === "expired") {
    if (!Number.isFinite(expiresAtMs)) return true;
    return nowMs - expiresAtMs > EXPIRED_GRACE_MS;
  }
  if (state === "processing") {
    if (typeof startedProcessingMs !== "number" || !Number.isFinite(startedProcessingMs)) return false;
    return nowMs - startedProcessingMs > PROCESSING_LIMIT_MS;
  }
  return false;
}

/** Насколько часы сервера впереди часов браузера (мс). Не разобрали — 0. */
export function clockSkewMs(serverTimeIso: string | null, receivedAtMs: number): number {
  if (!serverTimeIso) return 0;
  const server = Date.parse(serverTimeIso);
  if (!Number.isFinite(server) || !Number.isFinite(receivedAtMs)) return 0;
  return server - receivedAtMs;
}

/**
 * Сколько секунд осталось по часам СЕРВЕРА. Округляем вверх: «00:00» на
 * экране должно значить «время вышло», а не «осталось полсекунды».
 */
export function secondsLeft(expiresAtIso: string | null, nowMs: number, skewMs: number): number {
  if (!expiresAtIso) return 0;
  const deadline = Date.parse(expiresAtIso);
  if (!Number.isFinite(deadline)) return 0;
  const left = Math.ceil((deadline - (nowMs + (Number.isFinite(skewMs) ? skewMs : 0))) / 1000);
  return left > 0 ? left : 0;
}

/** Шаги кнопки «Оплатить другим способом»: idle → sending → (hold 30 с → armed). */
export type QrCancelPhase = "idle" | "sending" | "hold" | "armed";

/**
 * Что делает нажатие «Оплатить другим способом».
 *
 * Состояние счёта проверяется РАНЬШЕ паузы: пауза («банк обрабатывает оплату,
 * подождите») имеет смысл только пока QR ждёт оплаты. Счёт закрылся (истёк,
 * банк отказал) — держать человека не из-за чего, а кнопка на экране закрытого
 * счёта иначе молчала бы до конца паузы.
 */
export function otherMethodStep(
  state: QrUiState,
  phase: QrCancelPhase
): "leave" | "wait" | "cancel" | "abandon" {
  if (state !== "awaiting_payment") return "leave";
  if (phase === "sending" || phase === "hold") return "wait";
  // Второе нажатие после паузы: банк оплату так и не подтвердил — уходим.
  return phase === "armed" ? "abandon" : "cancel";
}

/** Таймер подсказки сработал настолько позже срока — страница была заморожена. */
const APP_OPEN_TIMER_SLACK_MS = 1500;

/**
 * Показать ли «Приложение не открылось?» после нажатия на банк.
 *
 * Мало посмотреть, видна ли страница в момент срабатывания таймера: iOS
 * замораживает таймеры ушедшей вкладки, и он срабатывает, когда человек уже
 * ВЕРНУЛСЯ из банка — страница снова видна, хотя приложение открылось.
 * Поэтому помним, уходила ли страница с экрана после нажатия, и не верим
 * таймеру, который сработал заметно позже срока (значит, страница спала).
 */
export function appNotOpened(wentHidden: boolean, hiddenNow: boolean, elapsedMs: number, waitMs: number): boolean {
  if (wentHidden || hiddenNow) return false;
  if (!Number.isFinite(elapsedMs)) return false;
  return elapsedMs <= waitMs + APP_OPEN_TIMER_SLACK_MS;
}

/** Имя файла с QR: хвост номера заказа, чтобы два сохранённых кода не спутать. */
export function qrFileName(orderId: string): string {
  const tail = String(orderId || "")
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "")
    .slice(-6);
  return tail ? `esai-qr-${tail}.png` : "esai-qr.png";
}

export function isQrInvoice(value: unknown): value is QrInvoice {
  if (!value || typeof value !== "object") return false;
  const v = value as { kind?: unknown; order_id?: unknown };
  return v.kind === "qr" && typeof v.order_id === "string" && v.order_id.length > 0;
}

const UI_STATES: QrUiState[] = ["awaiting_payment", "processing", "paid", "expired", "cancelled", "failed"];

const str = (v: unknown): string => (typeof v === "string" ? v : v == null ? "" : String(v));
const num = (v: unknown): number => {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
};
const flag = (v: unknown): boolean | null => (v === true ? true : v === false ? false : null);

/**
 * Привести ответ сервера к полной форме QrInvoice.
 *
 * Контракт обещает все ключи, но экран оплаты — последнее место, где можно
 * упасть из-за одного недоставшего поля: человек в этот момент платит.
 * Незнакомое состояние читаем как «ждём оплату» — на этом экране ничего
 * необратимого сделать нельзя, а опрос поправит картину.
 */
export function normalizeQrInvoice(value: QrInvoice): QrInvoice {
  const raw = value as unknown as Record<string, unknown>;
  const pkg = (raw.package || {}) as Record<string, unknown>;
  const credits = (raw.credits || {}) as Record<string, unknown>;
  const qr = (raw.qr || {}) as Record<string, unknown>;
  const state = UI_STATES.includes(raw.ui_state as QrUiState) ? (raw.ui_state as QrUiState) : "awaiting_payment";
  const apps: QrApp[] = [];
  if (Array.isArray(raw.apps)) {
    for (const item of raw.apps as Record<string, unknown>[]) {
      if (!item || typeof item !== "object" || typeof item.url !== "string") continue;
      const code = str(item.code);
      apps.push({
        code,
        name: str(item.name) || code,
        url: item.url,
        icon: str(item.icon),
        ios: flag(item.ios),
        android: flag(item.android),
      });
    }
  }
  const pkgId = pkg.id;
  return {
    kind: "qr",
    provider: str(raw.provider),
    resumed: raw.resumed === true,
    order_id: str(raw.order_id),
    status: str(raw.status),
    ui_state: state,
    amount: str(raw.amount),
    currency: str(raw.currency) || "KGS",
    original_amount: raw.original_amount == null || raw.original_amount === "" ? null : str(raw.original_amount),
    discount_percent: raw.discount_percent == null ? null : num(raw.discount_percent),
    package: {
      id: typeof pkgId === "number" || typeof pkgId === "string" ? pkgId : null,
      name: str(pkg.name),
      tokens: num(pkg.tokens),
      bonus_tokens: num(pkg.bonus_tokens),
    },
    credits: { total: num(credits.total), credited: num(credits.credited) },
    qr: { data: str(qr.data), image_url: str(qr.image_url) },
    apps,
    checkout_url: str(raw.checkout_url),
    created_at: typeof raw.created_at === "string" ? raw.created_at : null,
    expires_at: typeof raw.expires_at === "string" ? raw.expires_at : null,
    server_time: typeof raw.server_time === "string" ? raw.server_time : null,
    seconds_left: Math.max(0, Math.floor(num(raw.seconds_left))),
    lifetime_seconds: Math.max(0, Math.floor(num(raw.lifetime_seconds))),
    is_test: raw.is_test === true,
    can_cancel: raw.can_cancel === true,
    return_to: str(raw.return_to),
  };
}

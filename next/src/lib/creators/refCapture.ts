/**
 * EsAI Creators: переход по ссылке ?ref=CODE на любой странице сайта.
 *
 * Раньше ?ref= читали только страницы входа, а ссылка креатора ведёт на
 * главную (esai.kg/?ref=TORA20) — такой переход терялся. Здесь два действия:
 * 1) cookie esai_ref — та же, что ставят страницы входа (имя, 30 дней,
 *    последний переход побеждает); сервер читает её при регистрации и для
 *    обычной партнёрской программы, и для программы Creators;
 * 2) счётчик «Переходы» креатора: один POST на устройство в день.
 *
 * Ничего не показывает и никогда не бросает. Адрес страницы не переписывает.
 */
import Cookies from "js-cookie";
import { postClick } from "./api";

/** Алфавит referral_uid, кодов креаторов и ссылок бота (ref_CODE). */
const REF_RE = /^[A-Za-z0-9]{4,32}$/;
const REF_COOKIE = "esai_ref";
const REF_COOKIE_DAYS = 30;
const CLICKS_STORAGE = "esai_ref_clicks";
const CLICKS_KEEP = 20;
/** Коды, переход по которым уже отправлен с этой загрузки страницы. */
const inFlight = new Set<string>();

/** Сегодня по местному времени: YYYY-MM-DD. */
function today(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** {CODE: день последнего отправленного перехода}; хранилище недоступно — null. */
function readClicks(): Record<string, string> | null {
  try {
    const raw = window.localStorage.getItem(CLICKS_STORAGE);
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return {};
    const out: Record<string, string> = {};
    for (const [code, day] of Object.entries(parsed)) {
      if (typeof day === "string") out[code] = day;
    }
    return out;
  } catch {
    return null;
  }
}

function writeClicks(clicks: Record<string, string>): void {
  try {
    // Держим только свежие записи: дни сортируются как строки.
    const kept = Object.entries(clicks)
      .sort((a, b) => (a[1] < b[1] ? 1 : a[1] > b[1] ? -1 : 0))
      .slice(0, CLICKS_KEEP);
    window.localStorage.setItem(CLICKS_STORAGE, JSON.stringify(Object.fromEntries(kept)));
  } catch {}
}

export function captureRef(): void {
  if (typeof window === "undefined") return;
  let code = "";
  try {
    const raw = new URLSearchParams(window.location.search).get("ref");
    if (!raw) return;
    code = raw.trim();
  } catch {
    return;
  }
  if (!REF_RE.test(code)) return;

  try {
    Cookies.set(REF_COOKIE, code, { expires: REF_COOKIE_DAYS, sameSite: "lax" });
  } catch {}

  const key = code.toUpperCase();
  const day = today();
  const clicks = readClicks();
  if (clicks && clicks[key] === day) return;
  // Эффект страницы может сработать дважды раньше, чем придёт ответ.
  if (inFlight.has(key)) return;
  inFlight.add(key);

  // Хранилище недоступно — переход всё равно отправляем: сервер сам не
  // посчитает второй раз одно устройство за день.
  void postClick(key)
    .then((res) => {
      if (!res.ok) return;
      const fresh = readClicks();
      if (!fresh) return;
      fresh[key] = day;
      writeClicks(fresh);
    })
    .catch(() => {});
}

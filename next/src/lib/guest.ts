// Guest identity for anonymous chat usage.
// A stable UUID is generated once and kept in localStorage under `esai_guest_id`,
// then sent to the chat backend via the `X-Guest-Id` header so the server can
// track the free guest quota without requiring registration.

const GUEST_ID_KEY = "esai_guest_id";

function uuid(): string {
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }
  } catch {}
  // RFC4122-ish fallback
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/** Returns the persisted guest id, creating one on first call. SSR-safe. */
export function getGuestId(): string {
  if (typeof window === "undefined") return "";
  try {
    let id = localStorage.getItem(GUEST_ID_KEY) || "";
    if (!id) {
      id = uuid();
      localStorage.setItem(GUEST_ID_KEY, id);
    }
    return id;
  } catch {
    // localStorage unavailable (private mode / blocked) — fall back to a
    // per-session id so the request still carries a header.
    return uuid();
  }
}

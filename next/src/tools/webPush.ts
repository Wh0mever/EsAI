// tools/webPush.ts
//
// Web Push subscription helpers for the EsAI PWA.
//
// iOS quirk: Notification.requestPermission() and pushManager.subscribe() MUST
// be called from a user gesture (a real click handler), otherwise iOS silently
// rejects. So `enablePush()` is designed to be wired to a button's onClick.
// `autoResubscribe()` never requests permission — it only refreshes an existing
// subscription for users who already granted it (endpoints can rotate).

import { fetchData } from "@/tools/fetchData";

// VAPID public key: env-provided, with a hard-coded fallback so the feature
// works even if the env var is missing at build time.
const VAPID_PUBLIC =
  process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY ||
  "BPn53NaOSbOmmEEEtQ1zrQMwN2eO9a5947AOJXA5QM3_0clMN3vPNVZi7trvhi95NY1zwJP3xRmrLZXpvuIxJF8";

/** Convert a base64url VAPID key into the Uint8Array subscribe() expects. */
function urlBase64ToUint8Array(base64String: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  // Back the array by an explicit ArrayBuffer so the type is
  // Uint8Array<ArrayBuffer> (not ArrayBufferLike), which subscribe() requires
  // under the TS 5.7+ lib.dom typings.
  const buffer = new ArrayBuffer(rawData.length);
  const outputArray = new Uint8Array(buffer);
  for (let i = 0; i < rawData.length; i += 1) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

/** Whether the browser supports the Web Push stack at all. */
export function pushSupported(): boolean {
  return (
    typeof navigator !== "undefined" &&
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

/** Current notification permission, or 'unsupported' when Push isn't available. */
export function pushPermission(): NotificationPermission | "unsupported" {
  if (!pushSupported()) return "unsupported";
  return Notification.permission;
}

/** POST the subscription to the backend. Uses sub.toJSON() to get the keys. */
async function sendSubscription(sub: PushSubscription): Promise<void> {
  const json = sub.toJSON();
  const keys = json.keys || ({} as Record<string, string>);
  await fetchData(
    "users/push/subscribe/",
    "POST",
    {
      endpoint: sub.endpoint,
      keys: { p256dh: keys.p256dh, auth: keys.auth },
    },
    true
  );
}

/**
 * Ask for notification permission and subscribe. MUST be called from a user
 * gesture (iOS requirement). Returns the resulting state.
 */
export async function enablePush(): Promise<"granted" | "denied" | "unsupported" | "error"> {
  if (!pushSupported()) return "unsupported";
  try {
    const permission = await Notification.requestPermission();
    if (permission !== "granted") return permission === "denied" ? "denied" : "error";

    const reg = await navigator.serviceWorker.ready;
    const sub =
      (await reg.pushManager.getSubscription()) ||
      (await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC),
      }));

    await sendSubscription(sub);
    return "granted";
  } catch {
    return "error";
  }
}

/**
 * Silently refresh the push subscription for users who already granted
 * permission (endpoints can rotate). Never prompts. Safe no-op otherwise.
 */
export async function autoResubscribe(): Promise<void> {
  try {
    if (!pushSupported()) return;
    if (Notification.permission !== "granted") return;

    const reg = await navigator.serviceWorker.ready;
    const sub =
      (await reg.pushManager.getSubscription()) ||
      (await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC),
      }));

    await sendSubscription(sub);
  } catch {
    /* silent — best-effort refresh */
  }
}

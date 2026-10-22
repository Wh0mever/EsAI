// «Скачать»: шитшет — только на телефоне/планшете, на компьютере — файл (tools/saveMedia.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/tools/saveMedia.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { isHandheld, pickSaveRoute } from "./saveMedia.ts";

const MAC_SAFARI = {
  userAgent:
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
  platform: "MacIntel",
  maxTouchPoints: 0,
};
const MAC_CHROME = {
  userAgent:
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
  platform: "MacIntel",
  maxTouchPoints: 0,
  uaMobile: false,
};
const WIN_EDGE = {
  userAgent:
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
  platform: "Win32",
  maxTouchPoints: 0,
  uaMobile: false,
};
// Ноутбук с сенсорным экраном — всё равно компьютер.
const WIN_TOUCH_LAPTOP = { ...WIN_EDGE, maxTouchPoints: 10 };
const LINUX_FIREFOX = {
  userAgent: "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0",
  platform: "Linux x86_64",
  maxTouchPoints: 0,
};
const IPHONE = {
  userAgent:
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
  platform: "iPhone",
  maxTouchPoints: 5,
};
// iPadOS по умолчанию выдаёт себя за Mac: отличает только тачскрин.
const IPAD_AS_MAC = { ...MAC_SAFARI, maxTouchPoints: 5 };
const ANDROID_PHONE = {
  userAgent:
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
  platform: "Linux armv8l",
  maxTouchPoints: 5,
  uaMobile: true,
};
const ANDROID_TABLET = {
  userAgent:
    "Mozilla/5.0 (Linux; Android 14; SM-X710) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
  platform: "Linux armv8l",
  maxTouchPoints: 10,
  uaMobile: false,
};
// Telegram на телефоне открывает сайт во встроенном браузере: UA телефона с приставкой Telegram.
const TELEGRAM_IOS = { ...IPHONE, userAgent: `${IPHONE.userAgent} Telegram-iOS` };

test("компьютер: всегда файл, даже когда браузер умеет делиться файлами", () => {
  for (const pc of [MAC_SAFARI, MAC_CHROME, WIN_EDGE, WIN_TOUCH_LAPTOP, LINUX_FIREFOX]) {
    assert.equal(isHandheld(pc), false, pc.userAgent);
    assert.equal(pickSaveRoute(pc, true), "download", pc.userAgent);
    assert.equal(pickSaveRoute(pc, false), "download", pc.userAgent);
  }
});

test("телефон и планшет: системное окно, если оно умеет файлы", () => {
  for (const phone of [IPHONE, IPAD_AS_MAC, ANDROID_PHONE, ANDROID_TABLET, TELEGRAM_IOS]) {
    assert.equal(isHandheld(phone), true, phone.userAgent);
    assert.equal(pickSaveRoute(phone, true), "share", phone.userAgent);
  }
});

test("без файлового Share: iOS открывает файл (download там не работает), Android качает", () => {
  assert.equal(pickSaveRoute(IPHONE, false), "open");
  assert.equal(pickSaveRoute(IPAD_AS_MAC, false), "open");
  assert.equal(pickSaveRoute(ANDROID_PHONE, false), "download");
  assert.equal(pickSaveRoute(ANDROID_TABLET, false), "download");
});

test("признак mobile из userAgentData решает за неизвестный UA", () => {
  const unknown = { userAgent: "Mozilla/5.0 (X11; Linux aarch64)", platform: "Linux aarch64", maxTouchPoints: 5 };
  assert.equal(isHandheld(unknown), false);
  assert.equal(isHandheld({ ...unknown, uaMobile: true }), true);
});

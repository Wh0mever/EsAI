// «Склейка»: свои видео — проверки до загрузки, имя файла, подписи и разбор отказов (uploadLogic.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/merge/*.test.mjs
import "../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const u = await import("./uploadLogic.ts");
const { MERGE_ERROR_RU } = await import("./mergeText.ts");

const MB = 1024 * 1024;
const L = u.DEFAULT_UPLOAD_LIMITS;
const file = (name, size = 5 * MB, type = "video/mp4") => ({ name, size, type });
const usage = (files, bytes) => ({ files, bytes, max_files: 10, max_bytes: 600 * MB });

test("пределы по умолчанию — те же, что у сервера (CONTRACT_M §9.1)", () => {
  assert.equal(L.max_bytes, 94371840);
  assert.equal(L.max_mb, 90);
  assert.equal(L.min_duration_s, 0.5);
  assert.equal(L.max_duration_s, 60);
  assert.equal(L.max_side, 4096);
  assert.equal(L.max_fps, 120);
  assert.equal(L.max_per_project, 3);
  assert.equal(L.max_files, 10);
  assert.equal(L.max_total_bytes, 629145600);
  assert.deepEqual(L.extensions, ["mp4", "mov", "m4v", "webm"]);
  assert.equal(L.accept, "video/mp4,video/quicktime,video/webm,.mp4,.mov,.m4v,.webm");
});

test("fileExtension и uploadName: расширение решает, без него — тип файла", () => {
  assert.equal(u.fileExtension("IMG_0001.MOV"), "mov");
  assert.equal(u.fileExtension("C:\\fakepath\\clip.final.webm"), "webm");
  assert.equal(u.fileExtension(".mp4"), "");
  assert.equal(u.fileExtension("video"), "");
  assert.equal(u.uploadName(file("IMG_0001.MOV", 1, "video/quicktime")), "IMG_0001.MOV");
  assert.equal(u.uploadName(file("clip.m4v", 1, "")), "clip.m4v");
  // Галерея отдала имя без расширения — дописываем по типу, сервер всё равно смотрит на байты.
  assert.equal(u.uploadName(file("video:1234", 1, "video/quicktime")), "video:1234.mov");
  assert.equal(u.uploadName(file("", 1, "video/webm")), "video.webm");
  assert.equal(u.uploadName(file("clip.avi", 1, "video/x-msvideo")), null);
  assert.equal(u.uploadName(file("photo.png", 1, "image/png")), null);
  assert.equal(u.uploadName(file("clip.3gp", 1, "video/3gpp")), null);
});

test("precheckFile: размер, тип, пустой файл и место — в порядке сервера", () => {
  assert.equal(u.precheckFile(file("a.mp4")), null);
  assert.equal(u.precheckFile(file("a.mp4", 90 * MB)), null, "ровно 90 МБ — можно");
  assert.deepEqual(u.precheckFile(file("a.mp4", 90 * MB + 1)), { code: "upload_too_big" });
  assert.deepEqual(u.precheckFile(file("a.avi", 200 * MB, "video/x-msvideo")), { code: "upload_too_big" }, "сначала размер");
  assert.deepEqual(u.precheckFile(file("photo.png", MB, "image/png")), { code: "upload_bad_type" });
  assert.deepEqual(u.precheckFile(file("a.mp4", 0)), { code: "upload_unreadable" });
  assert.deepEqual(u.precheckFile(file("a.mp4"), L, usage(10, 0)), { code: "upload_quota" }, "10 файлов");
  assert.deepEqual(u.precheckFile(file("a.mp4", 50 * MB), L, usage(3, 560 * MB)), { code: "upload_quota" }, "600 МБ");
  assert.equal(u.precheckFile(file("a.mp4", 40 * MB), L, usage(3, 560 * MB)), null, "ровно 600 МБ — можно");
  assert.equal(u.precheckFile(file("a.mp4"), L, null), null, "место неизвестно — решит сервер");
});

test("precheckMedia: длина 0,5–60 с с допуском 0,5 с и кадр до 4096; непрочитанное — к серверу", () => {
  assert.equal(u.precheckMedia({ duration: 12, width: 1920, height: 1080 }), null);
  assert.deepEqual(u.precheckMedia({ duration: 0.3, width: 640, height: 360 }), { code: "upload_too_short" });
  assert.equal(u.precheckMedia({ duration: 60.03, width: 1080, height: 1920 }), null, "обрезка «1:00»");
  assert.equal(u.precheckMedia({ duration: 60.5, width: 1080, height: 1920 }), null);
  assert.deepEqual(u.precheckMedia({ duration: 60.6, width: 1080, height: 1920 }), { code: "upload_too_long" });
  assert.deepEqual(u.precheckMedia({ duration: 10, width: 4100, height: 2160 }), { code: "upload_resolution" });
  assert.equal(u.precheckMedia({ duration: 10, width: 4096, height: 2160 }), null);
  // WebM без длины (Infinity), HEVC, который Chrome не читает (0×0), — не наш отказ.
  assert.equal(u.precheckMedia({ duration: Infinity, width: 1280, height: 720 }), null);
  assert.equal(u.precheckMedia({ duration: Number.NaN, width: 0, height: 0 }), null);
  assert.equal(u.precheckMedia(null), null);
  assert.equal(u.precheckMedia({ duration: 5 }, { ...L, max_duration_s: 3 }).code, "upload_too_long", "предел с сервера");
});

test("precheckText — тот же текст, что пришёл бы от сервера", () => {
  const spec = u.precheckText({ code: "upload_too_long" });
  assert.equal(spec.key, "merge.err.upload_too_long");
  assert.equal(spec.ru, "Видео длиннее 60 секунд. Обрежьте его и загрузите снова.");
});

test("uploadErrorText: код сервера, поле file, сломанный multipart, 413", () => {
  const err = (code, data = {}, message = "") => ({ status: 400, code, message, data });
  assert.equal(u.uploadErrorText(err("upload_no_video")).key, "merge.err.upload_no_video");
  assert.equal(u.uploadErrorText(err("bad_request", { field: "file" })).key, "merge.err.bad_request_file");
  // 400 DRF без поля (multipart не разобрался) — для человека файл не прочитался.
  const broken = u.uploadErrorText(err("bad_request", { detail: "Multipart form parse error" }, "Multipart form parse error"));
  assert.equal(broken.key, "merge.err.upload_unreadable");
  assert.equal(broken.ru, MERGE_ERROR_RU.upload_unreadable);
  // 413 API уже переводит в upload_too_big (mergeApi.test.mjs).
  assert.equal(u.uploadErrorText({ status: 413, code: "upload_too_big", message: "", data: { max_mb: 90 } }).key, "merge.err.upload_too_big");
  // Неизвестный код — русский текст сервера.
  assert.deepEqual(u.uploadErrorText(err("brand_new", {}, "Новый отказ")), { key: "", ru: "Новый отказ", params: {} });
  // 429 загрузки: свой текст с минутами из wait (предел — 20 в час, общий «подождите немного» врёт).
  const slow = u.uploadErrorText({ status: 429, code: "throttled", message: "Request was throttled.", data: { wait: 1730 } });
  assert.deepEqual(slow, { key: "merge.err.upload_throttled", ru: MERGE_ERROR_RU.upload_throttled, params: { min: 29 } });
  assert.equal(u.uploadErrorText(err("throttled", { wait: 5 })).params.min, 1, "меньше минуты — «1 мин»");
  assert.equal(u.uploadErrorText(err("throttled")).key, "merge.err.throttled", "без wait — общий текст");
  assert.equal(u.uploadErrorCode(err("throttled", { wait: 60 })), "upload_throttled");
  assert.equal(u.uploadErrorCode(err("throttled", { wait: "90" })), "throttled", "wait не число");
  assert.equal(u.uploadErrorText(err("upload_busy")).key, "merge.err.upload_busy");
  assert.equal(u.uploadErrorText(err("upload_frame_rate", { max_fps: 120, fps: 6000 })).key, "merge.err.upload_frame_rate");
});

test("retryableUpload: «Повторить» — только когда файл не виноват", () => {
  for (const code of ["network", "server_error", "bad_response", "throttled", "upload_throttled", "upload_busy",
    "upload_unavailable", "unauthorized"]) {
    assert.equal(u.retryableUpload(code), true, code);
  }
  for (const code of ["upload_too_big", "upload_bad_type", "upload_unreadable", "upload_no_video", "upload_frame_rate",
    "upload_too_long", "upload_quota", "aborted"]) {
    assert.equal(u.retryableUpload(code), false, code);
  }
});

test("uploadsFull: десять файлов из десяти — отказ виден до выбора", () => {
  assert.equal(u.uploadsFull(null), false);
  assert.equal(u.uploadsFull(usage(9, 0)), false);
  assert.equal(u.uploadsFull(usage(10, 0)), true);
  assert.equal(u.uploadsFull({ files: 3, bytes: 0, max_files: 3, max_bytes: 0 }), true, "предел с сервера");
});

test("uploadExpiry: «до ДД.ММ», за три дня и меньше — «скоро»", () => {
  const now = new Date(2026, 9, 21, 12, 0);
  const at = (days) => new Date(now.getTime() + days * 86_400_000).toISOString();
  assert.deepEqual(u.uploadExpiry(at(20), now), { date: "10.11", soon: false });
  assert.equal(u.uploadExpiry(at(3.5), now).soon, false);
  assert.equal(u.uploadExpiry(at(3), now).soon, true);
  assert.equal(u.uploadExpiry(at(0.2), now).soon, true);
  assert.equal(u.uploadExpiry(null, now), null);
  assert.equal(u.uploadExpiry("не дата", now), null);
});

test("formatMb и numberLocale: «9,9 МБ», целые от 10 МБ, крошечный — не ноль", () => {
  assert.equal(u.formatMb(12.34 * MB, "ru-RU"), "12");
  assert.equal(u.formatMb(9.94 * MB, "ru-RU"), "9,9");
  assert.equal(u.formatMb(9.94 * MB, "en-US"), "9.9");
  assert.equal(u.formatMb(45563, "ru-RU"), "0,1");
  assert.equal(u.formatMb(0, "ru-RU"), "0");
  assert.equal(u.formatMb(600 * MB, "ru-RU"), "600");
  assert.equal(u.numberLocale("en"), "en-US");
  assert.equal(u.numberLocale("kg"), "ky-KG");
  assert.equal(u.numberLocale("ru"), "ru-RU");
});

test("uploadShare: проценты в долю, после отправки — полная полоска", () => {
  assert.equal(u.uploadShare(0, "upload"), 0);
  assert.equal(u.uploadShare(42, "upload"), 0.42);
  assert.equal(u.uploadShare(140, "upload"), 1);
  assert.equal(u.uploadShare(Number.NaN, "upload"), 0);
  assert.equal(u.uploadShare(5, "processing"), 1);
});

test("probeVideoFile без браузера — null (проверит сервер)", async () => {
  assert.equal(await u.probeVideoFile(new Blob([new Uint8Array([1])])), null);
});

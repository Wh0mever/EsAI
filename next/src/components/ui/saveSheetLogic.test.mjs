// Шторка «Скачать» (saveSheetLogic.ts): код ответа из ошибки загрузки и «файла больше нет» (404/410).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/ui/saveSheetLogic.test.mjs
// saveMedia.ts импортирует соседей без расширения — хук идёт первой строкой, модули подключаются после него.
import "../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const { fileGone, httpStatusOf } = await import("./saveSheetLogic.ts");
const { followMedia, holdMedia } = await import("../../tools/saveMedia.ts");

const named = (name, message) => Object.assign(new Error(message), { name });

test("httpStatusOf: код из HttpError, у прочих ошибок — null", () => {
  assert.equal(httpStatusOf(named("HttpError", "HTTP 404")), 404);
  assert.equal(httpStatusOf(named("HttpError", "HTTP 410")), 410);
  assert.equal(httpStatusOf(named("HttpError", "HTTP 502")), 502);
  for (const e of [
    named("TypeError", "Failed to fetch"),
    named("BadType", "not a media file"),
    named("AbortError", "HTTP 404"),
    named("HttpError", "HTTP"),
    named("HttpError", "HTTP 404 Not Found"),
    { name: "HttpError", message: 404 },
    "HTTP 404",
    null,
    undefined,
  ]) {
    assert.equal(httpStatusOf(e), null, String(e?.message ?? e));
  }
});

test("fileGone: только 404 и 410 — повтор не поможет", () => {
  assert.equal(fileGone(404), true);
  assert.equal(fileGone(410), true);
  for (const http of [200, 403, 429, 500, 502, 503, 0, null, undefined]) assert.equal(fileGone(http), false, String(http));
});

test("ошибка загрузки из tools/saveMedia несёт тот же код ответа", async () => {
  const realFetch = globalThis.fetch;
  try {
    for (const status of [404, 410, 502]) {
      globalThis.fetch = async () => new Response("<html>нет</html>", { status, headers: { "content-type": "text/html" } });
      const url = `/media/gone-${status}.mp4`;
      // Держим запись, как шторка: без этого saveMedia ставит таймер на 2 минуты и тест ждал бы его.
      const release = holdMedia(url);
      const error = await followMedia(url, () => {}).blob.then(
        () => null,
        (e) => e,
      );
      release();
      assert.equal(httpStatusOf(error), status);
      assert.equal(fileGone(httpStatusOf(error)), status !== 502);
    }
  } finally {
    globalThis.fetch = realFetch;
  }
});

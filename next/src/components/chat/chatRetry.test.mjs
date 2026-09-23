// «Повторить» и довоз ролика после обрыва (components/chat/chatRetry.ts):
// ошибки здесь = лишняя платная генерация или потерянный ролик.
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/chat/chatRetry.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { findNewVideo, planRetry } from "./chatRetry.ts";

const CONT = "Продолжи.";
const u = (content, extra = {}) => ({ role: "user", content, ...extra });
const a = (content, extra = {}) => ({ role: "assistant", content, ...extra });
const video = (id, prompt) => a("Готово — видео сгенерировано 🎬", {
  id,
  attachments: [{ type: "video", url: `/media/ai_videos/${id}.mp4`, ...(prompt !== undefined ? { prompt } : {}) }],
});

test("после «Продолжить» повторяется продолжение, продолжаемый ответ остаётся", () => {
  // [U1, A1] → «Продолжить» (continueFrom = 2) → частичный A2 + ошибка.
  const msgs = [u("Напиши рассказ"), a("Жил-был…"), a("и вот одн"), a("Сетевая ошибка.", { variant: "error" })];
  const plan = planRetry(msgs, 2, CONT);
  assert.deepEqual(plan, { keep: 2, content: CONT, attachments: [], extend: null, isContinue: true });
});

test("«Продолжить» ничего не добавило (paywall) — «Повторить» снова про вопрос", () => {
  const msgs = [u("Напиши рассказ"), a("Жил-был…")];
  const plan = planRetry(msgs, 2, CONT);
  assert.equal(plan.isContinue, false);
  assert.equal(plan.content, "Напиши рассказ");
  assert.equal(plan.keep, 1);
});

test("обычный повтор несёт те же файлы и тот же продлеваемый ролик", () => {
  const files = [{ type: "file", url: "/media/u/doc.pdf", name: "doc.pdf" }];
  const msgs = [
    u("старый вопрос"),
    a("старый ответ"),
    u("  что дальше?  ", { attachments: files, _extend: "/media/ai_videos/src.mp4" }),
    a("Видео не получилось сгенерировать. Кредиты не списаны.", { variant: "error" }),
  ];
  const plan = planRetry(msgs, null, CONT);
  assert.deepEqual(plan, {
    keep: 3,
    content: "что дальше?",
    attachments: files,
    extend: "/media/ai_videos/src.mp4",
    isContinue: false,
  });
  // Чат из истории: служебного _extend нет — обычный повтор без продления.
  const fromHistory = planRetry([u("вопрос", { id: 5 }), a("ответ", { id: 6 })], null, CONT);
  assert.equal(fromHistory.extend, null);
  assert.deepEqual(fromHistory.attachments, []);
});

test("нечего повторять — null", () => {
  assert.equal(planRetry([], null, CONT), null);
  assert.equal(planRetry([a("привет")], null, CONT), null);
  assert.equal(planRetry([u("   "), a("ошибка", { variant: "error" })], null, CONT), null);
});

test("ответ на СЛЕДУЮЩИЙ вопрос не подменяет ожидаемый ролик", () => {
  // Обрыв на ролике P; пока ждали, человек снял ролик Q (id 11, уже на экране).
  const history = [u("кот бежит"), u("собака летит"), video(11, "собака летит")];
  assert.equal(findNewVideo(history, "кот бежит", ["11"]), null);
  // Даже если ответ на Q ещё не успел появиться на экране — чужой prompt.
  assert.equal(findNewVideo(history, "кот бежит", []), null);
  // Фоновая задача дописала ролик P в конец чата — находим его.
  const later = [...history, video(12, "кот бежит")];
  assert.equal(findNewVideo(later, "кот бежит", ["11"])?.id, 12);
});

test("тот же текст отправлен ещё раз — показанный ролик не берём повторно", () => {
  const history = [u("кот бежит"), u("кот бежит"), video(7, "кот бежит")];
  assert.equal(findNewVideo(history, "кот бежит", ["7"]), null);
  const later = [...history, video(9, "кот бежит")];
  assert.equal(findNewVideo(later, "кот бежит", ["7"])?.id, 9);
});

test("старые вложения без prompt и длинный вопрос (сервер режет до 2000)", () => {
  assert.equal(findNewVideo([u("кот"), video(3)], "кот", [])?.id, 3);
  const long = "к".repeat(2500);
  assert.equal(findNewVideo([u(long), video(4, long.slice(0, 2000))], long, [])?.id, 4);
  // Не видео (картинка) — не наш ролик.
  const img = a("готово", { id: 5, attachments: [{ type: "image", url: "/m/1.png", prompt: "кот" }] });
  assert.equal(findNewVideo([u("кот"), img], "кот", []), null);
  assert.equal(findNewVideo("не массив", "кот", []), null);
});

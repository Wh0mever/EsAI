// EsAI Creators: заявка на участие — проверка формы и состояние посетителя
// (components/creators/public/applyLogic.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/creators/public/applyLogic.test.mjs
import "../../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const A = await import("./applyLogic.ts");

const filled = (over = {}) => ({
  ...A.emptyValues(),
  name: "Тора",
  telegram: "@tora",
  country: "Кыргызстан",
  instagram_url: "https://instagram.com/tora",
  followers: "12000",
  occupation: "Снимаю короткие видео",
  motivation: "Хочу рассказывать про EsAI",
  ...over,
});

test("заполненная форма проходит и даёт тело запроса с именами полей сервера", () => {
  const res = A.validateApplication(filled({ other_links: "https://vk.com/tora\nhttps://x.com/tora", samples: "" }));
  assert.deepEqual(res.issues, {});
  assert.equal(res.linksMissing, false);
  assert.deepEqual(res.body, {
    name: "Тора",
    telegram: "@tora",
    country: "Кыргызстан",
    instagram_url: "https://instagram.com/tora",
    tiktok_url: "",
    youtube_url: "",
    other_links: ["https://vk.com/tora", "https://x.com/tora"],
    followers: 12000,
    occupation: "Снимаю короткие видео",
    motivation: "Хочу рассказывать про EsAI",
    samples: [],
  });
});

test("обязательные поля: пустые и из одних пробелов", () => {
  const res = A.validateApplication({ ...A.emptyValues(), name: "   " });
  for (const name of ["name", "telegram", "country", "occupation", "motivation"]) {
    assert.deepEqual(res.issues[name], { kind: "required" }, name);
  }
  assert.deepEqual(res.issues.followers, { kind: "followers" });
  assert.equal(res.body, null);
});

test("длина: пределы как на сервере, считаем после обрезки пробелов", () => {
  assert.equal(A.validateApplication(filled({ name: "я".repeat(120) })).body?.name.length, 120);
  assert.deepEqual(A.validateApplication(filled({ name: "я".repeat(121) })).issues.name, { kind: "too_long", max: 120 });
  assert.deepEqual(A.validateApplication(filled({ telegram: "t".repeat(65) })).issues.telegram, { kind: "too_long", max: 64 });
  assert.deepEqual(A.validateApplication(filled({ country: "c".repeat(65) })).issues.country, { kind: "too_long", max: 64 });
  assert.deepEqual(A.validateApplication(filled({ motivation: "м".repeat(2001) })).issues.motivation, {
    kind: "too_long",
    max: 2000,
  });
  assert.ok(A.validateApplication(filled({ name: `  ${"я".repeat(120)}  ` })).body);
});

test("ссылки: только http(s), не длиннее 300, списки с пределом", () => {
  assert.deepEqual(A.validateApplication(filled({ tiktok_url: "@tora" })).issues.tiktok_url, { kind: "url" });
  assert.deepEqual(A.validateApplication(filled({ youtube_url: "ftp://youtube.com/x" })).issues.youtube_url, { kind: "url" });
  const long = `https://example.com/${"a".repeat(300)}`;
  assert.deepEqual(A.validateApplication(filled({ instagram_url: long })).issues.instagram_url, {
    kind: "url_too_long",
    max: 300,
  });
  const many = (n) => Array.from({ length: n }, (_, i) => `https://example.com/${i}`).join("\n");
  assert.ok(A.validateApplication(filled({ other_links: many(5), samples: many(10) })).body);
  assert.deepEqual(A.validateApplication(filled({ other_links: many(6) })).issues.other_links, {
    kind: "too_many_links",
    max: 5,
  });
  assert.deepEqual(A.validateApplication(filled({ samples: many(11) })).issues.samples, { kind: "too_many_links", max: 10 });
  assert.deepEqual(A.validateApplication(filled({ samples: "https://ok.example/1\nне ссылка" })).issues.samples, {
    kind: "url",
  });
});

test("нужна хотя бы одна ссылка на соцсеть; примеры работ за неё не считаются", () => {
  const none = A.validateApplication(filled({ instagram_url: "", samples: "https://example.com/work" }));
  assert.equal(none.linksMissing, true);
  assert.equal(none.body, null);
  assert.deepEqual(none.issues, {});
  assert.equal(A.validateApplication(filled({ instagram_url: "", other_links: "https://vk.com/tora" })).linksMissing, false);
  // Неверно написанная ссылка — ошибка поля, а не «ссылок нет».
  const bad = A.validateApplication(filled({ instagram_url: "@tora" }));
  assert.equal(bad.linksMissing, false);
  assert.deepEqual(bad.issues.instagram_url, { kind: "url" });
});

test("подписчики: целое от 0, пробелы-разделители допустимы", () => {
  assert.equal(A.parseFollowers("0"), 0);
  assert.equal(A.parseFollowers("10 000"), 10000);
  assert.equal(A.parseFollowers("2000000000"), 2000000000);
  for (const bad of ["", "-1", "1.5", "1e3", "10k", "2000000001", "99999999999"]) {
    assert.equal(A.parseFollowers(bad), null, bad);
  }
});

test("normalizeUrl: адрес без схемы получает https://, остальное не трогаем", () => {
  assert.equal(A.normalizeUrl(" instagram.com/tora "), "https://instagram.com/tora");
  assert.equal(A.normalizeUrl("www.youtube.com/@tora?x=1"), "https://www.youtube.com/@tora?x=1");
  assert.equal(A.normalizeUrl("http://example.com"), "http://example.com");
  assert.equal(A.normalizeUrl("HTTPS://example.com"), "HTTPS://example.com");
  assert.equal(A.normalizeUrl("@tora"), "@tora");
  assert.equal(A.normalizeUrl("просто текст"), "просто текст");
  assert.equal(A.normalizeUrl(""), "");
  const values = A.normalizeValues(filled({ tiktok_url: "tiktok.com/@tora", other_links: "vk.com/tora   x.com/tora" }));
  assert.equal(values.tiktok_url, "https://tiktok.com/@tora");
  assert.equal(values.other_links, "https://vk.com/tora\nhttps://x.com/tora");
  assert.equal(values.name, "Тора");
});

test("valuesFromApplication: прошлая заявка → значения формы", () => {
  const values = A.valuesFromApplication({
    id: 7,
    status: "rejected",
    created_at: "2026-10-01T10:00:00Z",
    decided_at: null,
    reject_reason: "Мало работ",
    name: "Тора",
    telegram: "@tora",
    country: "KG",
    instagram_url: "https://instagram.com/tora",
    tiktok_url: "",
    youtube_url: "",
    other_links: ["https://vk.com/tora", "https://x.com/tora"],
    followers: 1500,
    occupation: "Блогер",
    motivation: "Интересно",
    samples: ["https://example.com/1"],
  });
  assert.equal(values.other_links, "https://vk.com/tora\nhttps://x.com/tora");
  assert.equal(values.followers, "1500");
  assert.equal(values.samples, "https://example.com/1");
  assert.ok(A.validateApplication(values).body);
  assert.deepEqual(A.valuesFromApplication(null), A.emptyValues());
  // Неполный ответ сервера не должен ронять форму.
  assert.deepEqual(A.valuesFromApplication({}), A.emptyValues());
});

test("firstField: первое поле с ошибкой — в порядке полей на экране", () => {
  assert.equal(A.firstField(["samples", "country", "followers"]), "country");
  assert.equal(A.firstField(["unknown"]), null);
  assert.equal(A.firstField([]), null);
});

test("stageOf: что стоит на месте главной кнопки", () => {
  const me = (over) => ({ is_authenticated: true, is_creator: false, creator_status: null, application_status: null, ...over });
  assert.equal(A.stageOf(null), "guest");
  assert.equal(A.stageOf(me({ is_authenticated: false })), "guest");
  assert.equal(A.stageOf(me({})), "can_apply");
  assert.equal(A.stageOf(me({ application_status: "new" })), "pending");
  assert.equal(A.stageOf(me({ application_status: "rejected" })), "rejected");
  assert.equal(A.stageOf(me({ application_status: "blocked" })), "apply_blocked");
  assert.equal(A.stageOf(me({ is_creator: true, creator_status: "active", application_status: "approved" })), "creator");
  assert.equal(A.stageOf(me({ is_creator: true, creator_status: "blocked", application_status: "approved" })), "creator_blocked");
  // Одобренная заявка без креатора (после слияния аккаунтов): можно подать снова.
  assert.equal(A.stageOf(me({ application_status: "approved" })), "can_apply");

  assert.deepEqual(
    ["guest", "can_apply", "pending", "rejected", "apply_blocked", "creator", "creator_blocked"].filter(A.canApply),
    ["can_apply", "rejected"],
  );
});

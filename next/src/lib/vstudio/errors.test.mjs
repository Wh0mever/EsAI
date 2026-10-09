// Видеостудия: разбор ошибок API и тексты (lib/vstudio/errors.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/lib/vstudio/errors.test.mjs
import "./nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import i18next from "i18next";

const E = await import("./errors.ts");

// Подделка i18next.t: ключа нет в словаре — возвращает defaultValue с подстановками.
const fakeT = (key, opts = {}) =>
  String(opts.defaultValue ?? key).replace(/\{\{\s*(\w+)\s*\}\}/g, (_, n) => (n in opts ? String(opts[n]) : ""));

test("error_code читается из тела, а не из res.error", () => {
  const err = E.errorFromResponse({
    ok: false,
    status: 402,
    data: { error: "Недостаточно кредитов для генерации видео.", error_code: "insufficient_balance", balance_tokens: 40, required_estimate: 164 },
    error: "HTTP 402",
  });
  assert.equal(err.code, "insufficient_balance");
  assert.equal(err.status, 402);
  assert.equal(err.message, "Недостаточно кредитов для генерации видео.");
  assert.equal(err.data.balance_tokens, 40);
});

test("без error_code код берётся из HTTP-статуса", () => {
  assert.equal(E.errorFromResponse({ ok: false, status: 0, data: null, error: "Failed to fetch" }).code, "network");
  assert.equal(E.errorFromResponse({ ok: false, status: 401, data: { detail: "Нет учётных данных" } }).code, "unauthorized");
  assert.equal(E.errorFromResponse({ ok: false, status: 429, data: { detail: "Request was throttled." } }).code, "throttled");
  assert.equal(E.errorFromResponse({ ok: false, status: 413, data: "<html>413</html>", error: "HTTP 413" }).code, "file_too_large");
  assert.equal(E.errorFromResponse({ ok: false, status: 502, data: null, error: "HTTP 502" }).code, "server_error");
  assert.equal(E.errorFromResponse({ ok: false, status: 400, data: {} }).code, "bad_request");
  // «HTTP 502» от fetchData — не текст для человека.
  assert.equal(E.errorFromResponse({ ok: false, status: 502, data: null, error: "HTTP 502" }).message, "");
  assert.equal(E.errorFromResponse({ ok: false, status: 429, data: { detail: "Подождите" } }).message, "Подождите");
});

test("toResult: пустое тело у ответа с данными — bad_response; у 204 — норма", () => {
  const empty = E.toResult({ ok: true, status: 200, data: null });
  assert.equal(empty.ok, false);
  assert.equal(empty.error.code, "bad_response");
  const deleted = E.toResult({ ok: true, status: 204, data: null }, { allowEmpty: true });
  assert.deepEqual(deleted, { ok: true, status: 204, data: null });
  const good = E.toResult({ ok: true, status: 201, data: { uid: "x" } });
  assert.deepEqual(good, { ok: true, status: 201, data: { uid: "x" } });
});

test("402 и 403 premium_locked ведут в существующий PaywallModal", () => {
  const e402 = E.errorFromResponse({
    ok: false,
    status: 402,
    data: { error_code: "insufficient_balance", balance_tokens: 40, required_estimate: 164, reserved_credits: 120 },
  });
  const r = E.reactionFor(e402);
  assert.equal(r.kind, "paywall");
  assert.deepEqual(r.paywall, {
    reason: "insufficient_balance",
    minPackageKgs: undefined,
    balanceTokens: 40,
    requiredEstimate: 164,
    limit: undefined,
  });
  assert.equal(r.missing, 124);
  assert.equal(E.missingCredits(e402), 124);

  const e403 = E.errorFromResponse({ ok: false, status: 403, data: { error_code: "premium_locked", min_package_kgs: 190 } });
  const r2 = E.reactionFor(e403);
  assert.equal(r2.kind, "paywall");
  assert.equal(r2.paywall.reason, "premium_locked");
  assert.equal(r2.paywall.minPackageKgs, 190);
  assert.equal(r2.missing, 0);
});

test("остальные коды: вход, флаг, цена, блок, лимит, 404, загрузка, сеть, 5xx", () => {
  const react = (status, data) => E.reactionFor(E.errorFromResponse({ ok: false, status, data }));
  assert.equal(react(401, { detail: "x" }).kind, "auth");
  assert.equal(react(403, { error_code: "vstudio_disabled" }).kind, "disabled");

  const rq = react(409, { error_code: "price_changed", credits: 171, breakdown: [{ key: "price.video", params: {}, credits: 171 }] });
  assert.equal(rq.kind, "requote");
  assert.equal(rq.credits, 171);
  assert.equal(rq.breakdown.length, 1);

  const bl = react(422, {
    error_code: "blocked",
    errors: [{ code: "frames_refs_conflict", params: { model: "Veo 3.1 Fast" }, message: "m", fixes: [{ action: "use_frames_only" }, { action: "use_refs_only" }] }],
    warnings: [{ code: "faces_risk", params: {}, message: "w" }],
  });
  assert.equal(bl.kind, "blocked");
  assert.equal(bl.errors[0].code, "frames_refs_conflict");
  assert.deepEqual(E.issueFixes(bl.errors[0]).map((f) => f.action), ["use_frames_only", "use_refs_only"]);
  assert.equal(bl.warnings[0].fix, null);

  const lim = react(409, { error_code: "too_many_open", limit: 2, kind: "video" });
  assert.deepEqual(lim, { kind: "limit", limit: 2, of: "video" });

  for (const code of ["project_not_found", "take_not_found", "asset_not_found", "shot_not_found"]) {
    assert.equal(react(404, { error_code: code }).kind, "not_found", code);
  }
  assert.equal(react(404, { detail: "Not found." }).kind, "not_found");
  for (const code of ["file_too_large", "unsupported_type", "bad_image", "too_many_pixels", "video_refs_unsupported"]) {
    assert.equal(react(422, { error_code: code }).kind, "upload", code);
  }
  assert.equal(react(0, null).kind, "offline");
  assert.equal(react(429, { detail: "x" }).kind, "retry_later");
  assert.equal(react(503, { error_code: "provider_unavailable" }).kind, "retry_later");
  assert.equal(react(500, null).kind, "retry_later");
  assert.equal(react(409, { error_code: "already_submitted" }).kind, "message");
  assert.equal(E.reactionFor(E.abortedError()).kind, "ignore");
  assert.equal(E.isAborted(E.abortedError()), true);
});

test("errorText: ключ vstudio:errors.<code>, defaultValue — текст бэкенда", () => {
  const calls = [];
  const t = (key, opts) => {
    calls.push([key, opts]);
    return fakeT(key, opts);
  };
  const err = E.errorFromResponse({ ok: false, status: 409, data: { error: "Цена стала 171 кр.", error_code: "price_changed", credits: 171 } });
  assert.equal(E.errorText(t, err), "Цена стала 171 кр.");
  assert.equal(calls[0][0], "errors.price_changed");
  assert.equal(calls[0][1].ns, "vstudio");
  assert.equal(calls[0][1].credits, 171);
});

test("errorText: без текста бэкенда — свой русский с подстановками из тела", () => {
  const err = E.errorFromResponse({ ok: false, status: 409, data: { error_code: "too_many_open", limit: 2, kind: "video" } });
  assert.equal(
    E.errorText(fakeT, err),
    "Одновременно можно запустить не больше 2 — дождитесь, пока одна генерация закончится.",
  );
  assert.equal(E.errorText(fakeT, { code: "network", message: "" }), "Нет сети — результаты не пропадут.");
  assert.equal(E.errorText(fakeT, { code: "совсем_новый_код", message: "" }), "Что-то пошло не так. Попробуйте ещё раз.");
  assert.equal(E.errorText(fakeT, E.abortedError()), "");
  // Причина неудачного дубля — тоже группа errors.
  assert.match(E.errorText(fakeT, { code: "image_real_person", message: "" }), /реальных людей/);
});

test("issueText: предупреждения из группы warnings, списки через запятую", () => {
  const warn = { code: "prompt_long", params: { model: "Seedance 2.0", soft: 150, words: 480 }, message: "" };
  assert.equal(
    E.issueText(fakeT, warn, "warnings"),
    "Seedance 2.0 лучше всего понимает до ~150 слов, а у вас 480. Детали в конце могут потеряться — попробуйте «Сжать с ИИ».",
  );
  const keys = [];
  E.issueText((k, o) => (keys.push(k), fakeT(k, o)), warn, "warnings");
  assert.equal(keys[0], "warnings.prompt_long");

  const bad = { code: "invalid_param", params: { model: "Veo 3.1 Fast", field: "duration", value: 10, allowed: [4, 6, 8] }, message: "" };
  assert.equal(E.issueText(fakeT, bad, "errors"), "Veo 3.1 Fast не поддерживает длительность = 10. Доступно: 4, 6, 8.");
  // Текст бэкенда главнее своего.
  assert.equal(E.issueText(fakeT, { ...bad, message: "С сервера" }, "errors"), "С сервера");
});

test("у каждого кода §4.7 и §8.4 есть русский текст", () => {
  const blocking = [
    "prompt_empty", "prompt_too_long", "prompt_doc_invalid", "mention_not_attached", "asset_not_found",
    "asset_not_ready", "asset_failed", "refs_not_supported", "too_many_refs", "frames_not_supported",
    "last_frame_not_supported", "last_frame_with_refs", "frames_refs_conflict", "ref_too_small",
    "ref_bad_aspect", "video_refs_unsupported", "invalid_param", "model_unavailable", "too_many_inputs",
    "service_misconfigured",
  ];
  const warnings = [
    "prompt_long", "looks_like_script", "ref_unmentioned", "tag_unknown", "frame_soft_pin",
    "duration_forced", "faces_risk", "aspect_in_text", "lang_hint", "input_excluded",
  ];
  const http = [
    "bad_request", "insufficient_balance", "premium_locked", "vstudio_disabled", "project_not_found",
    "take_not_found", "asset_not_found", "shot_not_found", "price_changed", "too_many_open",
    "already_submitted", "file_too_large", "unsupported_type", "bad_image", "too_many_pixels",
    "video_refs_unsupported", "blocked", "prompt_doc_invalid", "condense_failed", "provider_unavailable",
    "service_misconfigured",
  ];
  assert.deepEqual([...E.BLOCKING_CODES].sort(), [...blocking].sort());
  assert.deepEqual([...E.WARNING_CODES].sort(), [...warnings].sort());
  for (const code of [...blocking, ...http]) assert.ok(E.ERROR_RU[code], code);
  for (const code of warnings) assert.ok(E.WARNING_RU[code], code);
  // Подстановки — только в формате i18next.
  for (const text of [...Object.values(E.ERROR_RU), ...Object.values(E.WARNING_RU)]) {
    assert.ok(!/(^|[^{])\{\w+\}(?!\})/.test(text), text);
  }
});

test("подстановки, которые бэкенд пишет только в русский текст", () => {
  // Кто виноват: референс с номером, кадр, выключенное фото.
  assert.equal(E.derivedParams({ asset: "a", slot: "reference", n: 2 }).subject, "@Image 2");
  assert.equal(E.derivedParams({ asset: "a", slot: "first_frame", n: null }).subject, "@Первый кадр");
  assert.equal(E.derivedParams({ asset: "a", slot: "last_frame", n: null }).subject, "@Последний кадр");
  assert.equal(E.derivedParams({ asset: "a", slot: "reference", n: null }).subject, "Выключенное фото");
  assert.equal(E.derivedParams({ model: "x" }).subject, undefined);
  assert.deepEqual(E.derivedParams({ field: "aspect_ratio", value: "21:9", allowed: ["16:9", "9:16"] }), {
    field_text: "пропорции",
    value_text: "21:9",
    allowed_text: "16:9, 9:16",
  });
  assert.equal(E.derivedParams({ current: "auto" }).current_text, "Авто");
  assert.equal(E.derivedParams({ current: "9:16" }).current_text, "9:16");
  assert.deepEqual(E.derivedParams({ lo: 0.4, hi: 2.5 }), { lo_text: "2:5", hi_text: "5:2" });
  assert.equal(E.ratioText(1.5), "3:2");
  assert.equal(E.ratioText(0), "");
  assert.equal(E.ratioText(null), "");
  // С t кадры и имена полей переводятся по ключам subject.* и fields.*.
  const keys = [];
  E.derivedParams({ slot: "first_frame", field: "duration" }, (k, o) => (keys.push(k), o.defaultValue));
  assert.deepEqual(keys, ["subject.first_frame", "fields.duration"]);
});

test("кадр: свой род и i18next context frame", () => {
  const seen = [];
  const t = (k, o) => (seen.push([k, o.context]), fakeT(k, o));
  const frame = { code: "ref_too_small", params: { asset: "a", slot: "first_frame", n: null, model: "Seedance 2.0", min: 300 }, message: "" };
  assert.equal(E.issueText(t, frame, "errors"), "@Первый кадр слишком маленький для Seedance 2.0: нужно от 300 px по короткой стороне.");
  assert.deepEqual(seen.at(-1), ["errors.ref_too_small", "frame"]);
  const refIssue = { ...frame, params: { ...frame.params, slot: "reference", n: 1 } };
  assert.equal(E.issueText(t, refIssue, "errors"), "@Image 1 слишком маленькое для Seedance 2.0: нужно от 300 px по короткой стороне.");
  assert.equal(seen.at(-1)[1], undefined);
  assert.equal(
    E.issueRu("input_excluded", { asset: "a", slot: "reference", n: null }, "warnings"),
    "Выключенное фото не учитывается и не оплачивается.",
  );
  assert.equal(E.issueRu("too_many_inputs", { max: 16 }, "errors"), "Слишком много материалов в одном запросе (максимум 16).");
});

/* ---------- закрытый дубль: причина по коду, а не по статусу ---------- */

const LANGS = ["ru", "en", "kg"];
const LOCALES = Object.fromEntries(
  LANGS.map((lang) => [lang, JSON.parse(fs.readFileSync(new URL(`../../locales/${lang}/vstudio.json`, import.meta.url), "utf8"))]),
);
// Настоящий i18next с теми же правилами, что в src/i18n/i18n.ts: context и откат на ru.
const i18n = i18next.createInstance();
await i18n.init({
  lng: "ru",
  fallbackLng: "ru",
  supportedLngs: LANGS,
  ns: ["vstudio"],
  defaultNS: "vstudio",
  resources: Object.fromEntries(LANGS.map((lang) => [lang, { vstudio: LOCALES[lang] }])),
  interpolation: { escapeValue: false },
});
const tFor = (lang) => i18n.getFixedT(lang, "vstudio");

// Коды, которыми конвейер закрывает дубль сам (ERRORS в core/vstudio/pipeline.py),
// и статус, с которым дубль приходит. Текст бэкенда — как он лежит в take.error.message.
const PIPELINE = {
  journal_unavailable: ["failed", "Не удалось запустить генерацию. Кредиты не списаны — попробуйте ещё раз."],
  queue_timeout: ["failed", "Генерация слишком долго ждала очереди. Кредиты не списаны — попробуйте ещё раз."],
  service_misconfigured: ["failed", "Студия временно недоступна. Мы уже чиним. Кредиты не списаны."],
  internal_error: ["failed", "Не удалось запустить генерацию. Кредиты не списаны — попробуйте ещё раз."],
  bad_result: ["failed", "Модель вернула файл, который не удалось открыть. Кредиты не списаны — попробуйте ещё раз."],
  submit_unknown: ["lost", "Не удалось подтвердить запуск — кредиты не списаны, мы проверим вручную."],
  provider_timeout: ["lost", "Модель так и не вернула результат. Кредиты не списаны, мы проверим вручную."],
  provider_unreachable: ["lost", "Не удалось забрать результат у модели. Кредиты не списаны, мы проверим вручную."],
  save_failed: ["lost", "Не удалось сохранить результат. Кредиты не списаны, мы проверим вручную."],
};
const LOST_CODES = Object.keys(PIPELINE).filter((code) => PIPELINE[code][0] === "lost");

const closed = (status, code, over = {}) => ({
  status,
  kind: "video",
  error: code ? { code, message: PIPELINE[code]?.[1] ?? "", input: null } : null,
  ...over,
});

const PIPELINE_PY = new URL("../../../../core/vstudio/pipeline.py", import.meta.url);

test(
  "список кодов конвейера совпадает с ERRORS бэкенда — новый код без текста не пройдёт",
  { skip: fs.existsSync(PIPELINE_PY) ? false : "рядом нет core/ (только фронтенд)" },
  () => {
    const block = /^ERRORS = \{\r?\n([\s\S]*?)^\}/m.exec(fs.readFileSync(PIPELINE_PY, "utf8"));
    assert.ok(block, "ERRORS не найден в pipeline.py");
    const codes = [...block[1].matchAll(/^\s*"(\w+)":/gm)].map((m) => m[1]);
    assert.deepEqual(codes.sort(), Object.keys(PIPELINE).sort());
  },
);

test("у каждого кода конвейера свой текст в ru, en и kg", () => {
  for (const code of Object.keys(PIPELINE)) {
    assert.ok(E.ERROR_RU[code], code);
    assert.equal(LOCALES.ru.errors[code], E.ERROR_RU[code], `ru: ${code}`);
    for (const lang of LANGS) {
      const text = LOCALES[lang].errors[code];
      assert.ok(typeof text === "string" && text.trim(), `${lang}: ${code}`);
    }
  }
  // У lost четыре причины — и четыре разных текста в каждом языке.
  for (const lang of LANGS) {
    assert.equal(new Set(LOST_CODES.map((code) => LOCALES[lang].errors[code])).size, LOST_CODES.length, lang);
  }
});

test("закрытый дубль: текст по error.code и в failed, и в lost", () => {
  for (const lang of LANGS) {
    for (const [code, [status]] of Object.entries(PIPELINE)) {
      assert.equal(E.takeErrorText(tFor(lang), closed(status, code)), LOCALES[lang].errors[code], `${lang}: ${status} ${code}`);
    }
  }
  // Переводы ещё не загрузились (t отдаёт defaultValue) — текст бэкенда того же кода, не чужой.
  for (const [code, [status, backend]] of Object.entries(PIPELINE)) {
    assert.equal(E.takeErrorText(fakeT, closed(status, code)), backend, code);
    assert.equal(E.takeErrorText(fakeT, closed(status, code, { error: { code, message: "", input: null } })), E.ERROR_RU[code], code);
  }
});

test("lost + save_failed: «ролик снят, но не сохранён», а не «не подтвердили запуск»", () => {
  const take = closed("lost", "save_failed");
  assert.equal(
    E.takeErrorText(tFor("ru"), take),
    "Ролик снят, но сохранить его не удалось. Кредиты не списаны — мы довезём его вручную.",
  );
  for (const lang of LANGS) {
    const text = E.takeErrorText(tFor(lang), take);
    assert.equal(text, LOCALES[lang].errors.save_failed, lang);
    assert.notEqual(text, LOCALES[lang].errors.submit_unknown, lang);
    assert.notEqual(text, E.takeErrorText(tFor(lang), closed("lost", "submit_unknown")), lang);
  }
  assert.match(E.takeErrorText(tFor("en"), take), /video was generated.*couldn't save it.*not charged.*deliver/);
  assert.match(E.takeErrorText(tFor("kg"), take), /Ролик тартылды.*сактоо мүмкүн болбоду.*Кредит алынган жок.*жеткирип беребиз/);
});

test("картинка: свой текст кода (context image), без него — общий текст кода", () => {
  const message = "Не удалось сохранить картинку. Кредиты не списаны — попробуйте ещё раз.";
  const image = closed("failed", "save_failed", { kind: "image", error: { code: "save_failed", message, input: null } });
  for (const lang of LANGS) {
    assert.equal(E.takeErrorText(tFor(lang), image), LOCALES[lang].errors.save_failed_image, lang);
    // У provider_timeout ключа _image нет: картинка, не вернувшаяся за 8 минут, — тот же текст.
    assert.equal(
      E.takeErrorText(tFor(lang), closed("lost", "provider_timeout", { kind: "image" })),
      LOCALES[lang].errors.provider_timeout,
      lang,
    );
  }
  assert.equal(E.takeErrorText(fakeT, image), message);
});

test("код, которого фронт не знает: текст бэкенда, иначе общая фраза статуса без причины", () => {
  const unknown = (status, message = "") => ({ status, kind: "video", error: { code: "совсем_новый_код", message, input: null } });
  for (const lang of LANGS) {
    const t = tFor(lang);
    assert.equal(E.takeErrorText(t, unknown("lost")), LOCALES[lang].errors.take_lost, lang);
    assert.equal(E.takeErrorText(t, unknown("failed")), LOCALES[lang].errors.unknown, lang);
    assert.equal(E.takeErrorText(t, closed("lost", null)), LOCALES[lang].errors.take_lost, lang);
    assert.equal(E.takeErrorText(t, closed("failed", null)), LOCALES[lang].errors.unknown, lang);
    assert.equal(E.takeErrorText(t, unknown("lost", "Новая причина с сервера.")), "Новая причина с сервера.", lang);
    // Запасная фраза не называет ни одну из известных причин.
    for (const code of Object.keys(PIPELINE)) assert.notEqual(LOCALES[lang].errors.take_lost, LOCALES[lang].errors[code], `${lang}: ${code}`);
  }
  assert.equal(E.takeErrorText(fakeT, unknown("lost")), E.CLIENT_RU.take_lost);
  assert.equal(E.takeErrorText(fakeT, unknown("failed")), E.CLIENT_RU.unknown);
  assert.doesNotMatch(E.CLIENT_RU.take_lost, /запуск|сохран|модел|очеред/i);
  // Код без текста, но с сообщением бэкенда — показываем сообщение.
  assert.equal(E.takeErrorText(fakeT, { status: "lost", kind: "video", error: { code: "", message: "Текст", input: null } }), "Текст");
});

test("дубль без ошибки (идёт, готов, отменён) — причины нет", () => {
  for (const status of ["queued", "submitting", "running", "saving", "done", "canceled"]) {
    assert.equal(E.takeErrorText(fakeT, closed(status, "save_failed")), "", status);
  }
});

test("errorText: unknownText — только для кода без своего текста", () => {
  assert.equal(E.errorText(fakeT, { code: "совсем_новый_код", message: "", unknownText: "Запасной" }), "Запасной");
  assert.equal(E.errorText(fakeT, { code: "совсем_новый_код", message: "С сервера", unknownText: "Запасной" }), "С сервера");
  assert.equal(E.errorText(fakeT, { code: "network", message: "", unknownText: "Запасной" }), "Нет сети — результаты не пропадут.");
});

test("interpolationParams и fillRu", () => {
  assert.deepEqual(E.interpolationParams({ a: 1, b: ["x", 2], c: null, d: true, e: "s" }), {
    a: 1, b: "x, 2", c: "", d: "true", e: "s",
  });
  assert.equal(E.fillRu("{{n}} из {{ max }} {{none}}", { n: 2, max: 3 }), "2 из 3 ");
  assert.equal(E.firstBlockingCode([{ code: "prompt_empty", params: {}, message: "" }]), "prompt_empty");
  assert.equal(E.firstBlockingCode([]), null);
});

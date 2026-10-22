// «Склейка»: звук — цены и счётчик символов как у сервера, начало голоса, дорожки, отказы (audioLogic.ts).
// Запуск (Node 22.6+):  node --experimental-strip-types --test src/components/merge/*.test.mjs
import "../../lib/vstudio/nodeTsHooks.mjs";
import { test } from "node:test";
import assert from "node:assert/strict";

const a = await import("./audioLogic.ts");
const m = await import("./mergeLogic.ts");
const { MERGE_ERROR_RU, MERGE_FAIL_RU } = await import("./mergeText.ts");

const P = a.DEFAULT_AUDIO_PRICES;
const L = a.DEFAULT_AUDIO_LIMITS;
const frag = (duration_s, title = "") => ({ duration_s, title });
const track = (over = {}) => ({
  id: "1814eb6841284714b356aa88f5d67b29",
  kind: "voice",
  source: "generated",
  status: "ready",
  url: "/media/merge/audio/1/c649e44f29a84a9db5aefae65bd543a1.mp3",
  duration_s: 3.03,
  text: "Проверка голоса за кадром",
  prompt: "",
  title: "",
  voice_id: "voice_ru_1",
  voice_name: "Тестовый голос",
  start_fragment: 2,
  start_fragment_effective: 2,
  seconds: null,
  credits_reserved: 0,
  credits_charged: 5,
  error: "",
  error_code: null,
  request_id: null,
  created_at: "2026-10-22T06:57:55.781849+00:00",
  expires_at: "2026-11-21T06:57:56.803662+00:00",
  ...over,
});

test("пределы и цены по умолчанию — те же, что у сервера (CONTRACT_M §10.2)", () => {
  assert.deepEqual(P, { voice_per_1k: 20, voice_min: 5, music_per_min: 30 });
  assert.equal(L.voice_chars, 2000, "голос склейки — 2000 знаков (у мультстудии на сцену — 1000)");
  assert.equal(L.prompt_min_chars, 3);
  assert.equal(L.prompt_chars, 400);
  assert.equal(L.music_min_s, 3);
  assert.equal(L.music_max_s, 300);
  assert.equal(L.upload_max_bytes, 20971520);
  assert.equal(L.upload_max_mb, 20);
  assert.equal(L.extensions.length, 23);
  assert.ok(L.accept.startsWith("audio/*,.mp3,.m4a,.aac,.wav"));
  assert.ok(L.accept.endsWith(".caf,.wma,.mka"));
  assert.deepEqual(L.clip_volumes, { keep: 1, quiet: 0.3, off: 0 });
  assert.deepEqual([...a.CLIP_SOUNDS], ["keep", "quiet", "off"]);
  assert.ok(a.isClipSound("quiet") && !a.isClipSound("loud") && !a.isClipSound(null));
});

test("счётчик символов: пробелы и переводы строк — один пробел, смайлик — один символ", () => {
  assert.equal(a.cleanText("  Привет,\n\n  мир\t! "), "Привет, мир !");
  assert.equal(a.textChars("  Привет,\n\n  мир\t! "), 13);
  assert.equal(a.textChars("😀 ok"), 4, "кодовые точки, как len() в Python");
  assert.equal(a.textChars(""), 0);
  assert.equal(a.textChars("   \n "), 0);
  assert.equal(a.textChars(null), 0);
});

test("цена голоса: 1–250 символов — 5 кр, дальше по 20 кр за 1000 (CONTRACT_M §10.4)", () => {
  const text = (n) => "а".repeat(n);
  assert.equal(a.voicePrice(text(0)), 5, "пустой — минимум (кнопка всё равно выключена)");
  assert.equal(a.voicePrice(text(1)), 5);
  assert.equal(a.voicePrice(text(250)), 5);
  assert.equal(a.voicePrice(text(251)), 6);
  assert.equal(a.voicePrice(text(500)), 10);
  assert.equal(a.voicePrice(text(1000)), 20);
  assert.equal(a.voicePrice(text(1951)), 40);
  assert.equal(a.voicePrice(text(2000)), 40, "предел склейки — 40 кр, как voice_price сервера");
  // Считаются символы после чистки: лишние пробелы не стоят денег.
  assert.equal(a.voicePrice(`${"а".repeat(250)}${" ".repeat(400)}`), 5);
  assert.equal(a.voicePrice("а".repeat(300), { voice_per_1k: 40, voice_min: 1, music_per_min: 30 }), 12);
});

test("длина и цена музыки — как music_seconds/music_price сервера", () => {
  assert.equal(a.musicSeconds([]), 0);
  assert.equal(a.musicSeconds([frag(null), frag(0)]), 0);
  assert.equal(a.musicSeconds([frag(2.2)]), 3, "не короче 3 с");
  assert.equal(a.musicSeconds([frag(2.5), frag(4), frag(3), frag(5)]), 15, "14,5 → 15");
  assert.equal(a.musicSeconds([frag(14.04)]), 15, "округляется вверх, как ceil у сервера");
  assert.equal(a.musicSeconds([frag(14.0004)]), 14, "сумма до тысячных: 14,0004 → 14,000");
  assert.equal(a.musicSeconds([frag(7.003), frag(7)]), 15, "14,003 → 15");
  assert.equal(a.mergeTotal([frag(2.5), frag(null), frag(1.23456)]), 3.735);
  assert.equal(a.musicSeconds([frag(200), frag(150)]), 300, "не длиннее 5 минут");
  assert.equal(a.musicPrice(15), 8);
  assert.equal(a.musicPrice(300), 150);
  assert.equal(a.musicPrice(3), 2);
  assert.equal(a.musicPrice(1, { voice_per_1k: 20, voice_min: 5, music_per_min: 30 }), 1);
  assert.equal(a.musicPrice(0), 0);
});

test("musicQuote: фрагменты те же, что у сервера, — его цена, иначе по формуле", () => {
  const state = { music_quote: { seconds: 15, credits: 9 }, total_duration_s: 14.5, prices: P, limits: L };
  assert.deepEqual(a.musicQuote(state, [frag(10), frag(4.5)]), { seconds: 15, credits: 9 }, "цены сервера могли поменяться");
  assert.deepEqual(a.musicQuote(state, [frag(14.5), frag(6)]), { seconds: 21, credits: 11 }, "сохранение ещё не дошло");
  assert.deepEqual(a.musicQuote(null, [frag(60)]), { seconds: 60, credits: 30 });
  assert.equal(a.musicQuote(state, []), null);
  assert.equal(a.musicQuote({ ...state, music_quote: null, total_duration_s: 0 }, []), null);
});

test("начало голоса: секунда начала каждого фрагмента и где он начнётся на самом деле", () => {
  assert.deepEqual(a.fragmentStarts([frag(2.5), frag(4), frag(3), frag(5)]), [0, 2.5, 6.5, 9.5]);
  assert.deepEqual(a.fragmentStarts([frag(null), frag(3.333), frag(1)]), [0, 0, 3.333], "без длины — 0 с");
  assert.deepEqual(a.fragmentStarts([]), []);
  assert.equal(a.effectiveStart(2, 4), 2);
  assert.equal(a.effectiveStart(5, 4), 3, "фрагменты убрали — с последнего");
  assert.equal(a.effectiveStart(-3, 4), 0);
  assert.equal(a.effectiveStart(null, 4), 0);
  assert.equal(a.effectiveStart(1.7, 4), 1);
  assert.equal(a.effectiveStart(3, 0), 0);
  const opts = a.startOptions([frag(2.5, " Своё "), frag(4, "Дубль"), frag(3, "")]);
  assert.deepEqual(opts, [
    { index: 0, n: 1, at: 0, title: "Своё" },
    { index: 1, n: 2, at: 2.5, title: "Дубль" },
    { index: 2, n: 3, at: 6.5, title: "" },
  ]);
  assert.equal(m.formatDuration(opts[2].at), "0:07", "подпись «с 0:07» — те же M:SS, что у ленты");
});

test("дорожки: готовая, делается, неудачная — у каждого вида свои; последний — самый свежий", () => {
  const voice = track();
  const failedVoice = track({ id: "a".repeat(32), status: "failed", error_code: "audio_failed", credits_charged: 0, url: null });
  const music = track({ id: "b".repeat(32), kind: "music", text: "", prompt: "пианино", voice_id: "", voice_name: "", start_fragment: null, start_fragment_effective: null, seconds: 15, credits_charged: 8 });
  const pendingMusic = track({ id: "c".repeat(32), kind: "music", status: "pending", credits_reserved: 8, credits_charged: 0, url: null });
  const tracks = [music, pendingMusic, voice, failedVoice];
  assert.deepEqual(a.trackSlot(tracks, "voice"), { ready: voice, pending: null, failed: failedVoice });
  assert.deepEqual(a.trackSlot(tracks, "music"), { ready: music, pending: pendingMusic, failed: null });
  assert.deepEqual(a.trackSlot(null, "music"), { ready: null, pending: null, failed: null });
  assert.equal(a.hasPending({ tracks }), true);
  assert.equal(a.hasPending({ tracks: [voice, music] }), false);
  assert.equal(a.hasPending(null), false);
  const done = { ...pendingMusic, status: "ready", credits_reserved: 0, credits_charged: 8 };
  assert.deepEqual(a.settledTracks(tracks, [music, done, voice]), [done]);
  assert.deepEqual(a.settledTracks(tracks, tracks), [], "всё ещё делается");
  assert.deepEqual(a.settledTracks(tracks, [music, voice]), [], "дорожку убрали — не «готова»");
});

test("что со звуком: из состояния, из краткой сводки склейки, по умолчанию", () => {
  const voice = track();
  const own = track({ id: "d".repeat(32), kind: "music", source: "upload", title: "Мой трек", credits_charged: 0 });
  const gen = track({ id: "e".repeat(32), kind: "music", credits_charged: 8 });
  const s = (tracks, clip_sound = "keep") => ({ tracks, clip_sound });

  const both = a.soundInfo(s([gen, voice], "quiet"));
  assert.deepEqual(both, { voice: true, music: "generated", clip: "quiet", pending: false });
  assert.deepEqual(a.soundParts(both), ["voice", "music", "quiet"]);
  assert.equal(a.paidSound(both), "both");

  const ownOnly = a.soundInfo(s([own], "off"));
  assert.deepEqual(a.soundParts(ownOnly), ["own", "off"]);
  assert.equal(a.paidSound(ownOnly), null, "свой трек бесплатный");
  assert.equal(a.paidSound(a.soundInfo(s([voice, own]))), "voice");
  assert.equal(a.paidSound(a.soundInfo(s([gen]))), "music");
  // Копия «Изменить и склеить заново»: 0 кр в этой склейке, но оплачена в прежней.
  assert.equal(a.paidSound(a.soundInfo(s([track({ credits_charged: 0 })]))), "voice");

  const none = a.soundInfo(s([]));
  assert.equal(a.hasSound(none), false);
  assert.equal(a.hasSound(a.soundInfo(s([], "off"))), true);

  const summary = { clip_sound: "keep", music_volume: 0.35, voice_volume: 1, voice: false, music: true, pending: true };
  const brief = a.soundInfo(null, summary);
  assert.deepEqual(brief, { voice: false, music: "unknown", clip: "keep", pending: true });
  assert.deepEqual(a.soundParts(brief), ["music"]);
  assert.equal(a.paidSound(brief), null, "про оплату сводка не знает — не обещаем");
  assert.deepEqual(a.soundInfo(null, null), { voice: false, music: null, clip: "keep", pending: false });
  assert.equal(a.soundInfo(s([], "loud")).clip, "keep");
});

test("до запроса: почему «Озвучить» и «Создать» нельзя — тем же текстом, что у сервера", () => {
  assert.equal(a.voiceRefusal("  ", "v1").key, "merge.err.audio_text_empty");
  const long = a.voiceRefusal("а".repeat(2001), "v1");
  assert.equal(long.key, "merge.err.voice_too_long");
  assert.equal(m.fillText(long.ru, long.params), "Текст длиннее 2000 символов — сократите его.");
  assert.equal(a.voiceRefusal(`${"а".repeat(2000)}   `, "v1"), null, "пробелы по краям не считаются");
  assert.equal(a.voiceRefusal(`${"а".repeat(1000)}\n\n${"б".repeat(999)}`, "v1"), null, "абзацы — один пробел: 2000");
  assert.equal(a.textChars(`${"а".repeat(1000)}\n\n${"б".repeat(999)}`), 2000);
  // Предел — из ответа сервера (limits.voice_chars), а не зашитое число.
  const serverLimits = { voice_chars: 1500 };
  assert.equal(a.voiceRefusal("а".repeat(1501), "v1", serverLimits).params.max, 1500);
  assert.equal(a.voiceRefusal("а".repeat(1500), "v1", serverLimits), null);
  assert.equal(a.voiceRefusal("Текст", "").key, "merge.err.audio_voice_id");
  assert.equal(a.voiceRefusal("Текст", "v1"), null);

  assert.equal(a.musicRefusal("пи", 15).key, "merge.err.audio_prompt_short");
  const longPrompt = a.musicRefusal("м".repeat(401), 15);
  assert.equal(m.fillText(longPrompt.ru, longPrompt.params), "Описание музыки — не длиннее 400 символов.");
  assert.equal(a.musicRefusal("пианино", 0).key, "merge.err.audio_no_fragments");
  assert.equal(a.musicRefusal("пианино", 15), null);
});

test("свой трек до загрузки: размер, расширение (или тип файла), пустой файл", () => {
  const f = (name, size = 3 * 1024 * 1024, type = "audio/mpeg") => ({ name, size, type });
  assert.equal(a.precheckAudio(f("song.MP3")), null);
  assert.equal(a.precheckAudio(f("song.mp3", 21 * 1024 * 1024)), "audio_too_big");
  assert.equal(a.precheckAudio(f("song.txt", 100, "text/plain")), "audio_bad_type");
  assert.equal(a.precheckAudio(f("song.mp3", 0)), "audio_unreadable");
  assert.equal(a.precheckAudio(f("Запись 12", 1000, "audio/x-m4a")), null, "без расширения — по типу");
  assert.equal(a.audioUploadName(f("Запись 12", 1000, "audio/x-m4a")), "Запись 12.m4a");
  assert.equal(a.audioUploadName(f("clip.mov", 1000, "video/quicktime")), "clip.mov", "видео принимается ради звука");
  assert.equal(a.audioUploadName(f("", 1000, "audio/wav")), "music.wav");
  assert.equal(a.audioUploadName(f("x", 1000, "image/png")), null);
});

test("отказы сервера звука (CONTRACT_M §10.7.1): у каждого кода — свой текст", () => {
  const server = {
    voice_too_long: "Текст длиннее 2000 символов — сократите его.",
    audio_no_fragments: "Сначала добавьте фрагменты: музыка создаётся под длину склейки.",
    audio_too_big: "Файл больше 20 МБ. Выберите трек поменьше или сожмите его.",
    audio_bad_type: "Этот формат не подходит — загрузите MP3, M4A, WAV, OGG, FLAC или другой аудиофайл.",
    audio_unreadable: "Файл не читается — возможно, он повреждён. Выберите другой трек.",
    audio_no_sound: "В файле нет звука, который можно использовать. Выберите другой трек.",
    audio_too_long: "Трек длиннее 5 минут. Обрежьте его и загрузите снова.",
    audio_unsupported:
      "Такой трек не подходит: в нём больше 8 каналов или частота выше 192 кГц. Сохраните его как обычное стерео, например в MP3, и загрузите снова.",
    music_busy: "Сейчас готовится много музыки — попробуйте через минуту. Кредиты не списаны.",
    project_not_found: "Склейка не найдена.",
    audio_not_found: "Дорожка не найдена.",
    render_in_progress: "Склейка уже идёт — изменить или удалить её можно после окончания.",
    audio_ready_locked:
      "Звук готовой склейки не меняется. Нажмите «Изменить и склеить заново» — звук перейдёт в новую склейку.",
    audio_busy: "Звук для этой склейки ещё делается — дождитесь его.",
    audio_pending: "Голос или музыка ещё делаются — дождитесь их и нажмите «Склеить».",
    audio_upload_busy: "Уже загружается другой трек — дождитесь окончания.",
    audio_failed: "Не получилось сделать звук — кредиты не списаны, попробуйте ещё раз.",
    audio_unavailable: "Сервис звука временно недоступен — кредиты не списаны, попробуйте позже.",
    audio_overloaded: "Сервис звука перегружен — подождите минуту и попробуйте снова. Кредиты не списаны.",
    audio_not_configured: "Голос и музыка по описанию пока не подключены. Свой трек можно загрузить.",
    upload_unavailable: "Загрузка сейчас недоступна: на сервере не хватает места. Попробуйте позже.",
  };
  for (const [code, text] of Object.entries(server)) {
    const s = a.audioErrorText({ code, message: "текст сервера", data: {} });
    assert.equal(s.key, `merge.err.${code}`, code);
    assert.equal(m.fillText(s.ru, s.params), text, code);
  }
  const price = a.audioErrorText({ code: "audio_price_changed", message: "", data: { credits: 12 } });
  assert.equal(m.fillText(price.ru, price.params), "Цена изменилась: теперь 12 кр. Проверьте и нажмите ещё раз.");
  assert.equal(a.audioErrorText({ code: "audio_price_changed", message: "Сервер", data: {} }).ru, "Сервер", "без цены — без дырки");
  assert.equal(a.audioErrorText({ code: "voice_too_long", message: "", data: { max: 800 } }).params.max, 800);
  assert.equal(a.audioErrorText({ code: "audio_too_big", message: "", data: { max_mb: 25 } }).params.max, 25);
  // 402 открывает пополнение; текст — запасной.
  assert.equal(a.audioErrorText({ code: "insufficient_balance", message: "", data: {} }).key, "merge.err.audio_balance");
  // Неизвестный код — русский текст сервера.
  assert.deepEqual(a.audioErrorText({ code: "audio_new", message: "Новый отказ", data: {} }), { key: "", ru: "Новый отказ", params: {} });
});

test("bad_request звука: поле решает, какой текст", () => {
  const bad = (field, extra = {}, message = "") => a.audioErrorText({ code: "bad_request", message, data: { field, ...extra } });
  assert.equal(bad("text").key, "merge.err.audio_text_empty");
  assert.equal(bad("voice_id").key, "merge.err.audio_voice_id");
  assert.equal(bad("start_fragment").key, "merge.err.audio_start_fragment");
  assert.equal(bad("voice_start_fragment", {}, "Такого фрагмента в склейке нет — выберите…").key, "merge.err.audio_start_fragment");
  assert.equal(bad("voice_start_fragment", {}, "Голоса за кадром пока нет — сначала озвучьте текст.").key, "merge.err.audio_no_voice");
  assert.equal(bad("prompt").key, "merge.err.audio_prompt_short");
  assert.equal(bad("prompt", { max: 400 }).key, "merge.err.audio_prompt_long");
  assert.equal(bad("file").key, "merge.err.audio_file");
  for (const f of ["clip_sound", "music_volume", "voice_volume", ""]) assert.equal(bad(f).key, "merge.err.audio_settings", f);
});

test("отказы: лимит своих треков — в минутах, обрыв связи — сверяемся с сервером", () => {
  const slow = a.audioErrorText({ code: "throttled", message: "", data: { wait: 600 } }, undefined, { upload: true });
  assert.equal(m.fillText(slow.ru, slow.params), "Загрузок за час слишком много — следующую можно через 10 мин.");
  assert.equal(a.audioErrorText({ code: "throttled", message: "", data: { wait: 30 } }).key, "merge.err.throttled");
  assert.equal(a.audioErrorText({ code: "network", message: "", data: {} }).key, "merge.err.network");
  for (const code of ["network", "server_error", "bad_response", "unknown"]) assert.equal(a.isTransportError({ code }), true, code);
  for (const code of ["audio_failed", "insufficient_balance", "audio_busy", "throttled"]) assert.equal(a.isTransportError({ code }), false, code);
});

test("неудачная дорожка (§10.7.2) и неудачная склейка со звуком (§10.7.3)", () => {
  const fail = (error_code, error = "") => a.trackErrorText({ error_code, error });
  assert.equal(fail("audio_stale").ru, "Звук не успел сделаться — кредиты не списаны, попробуйте ещё раз.");
  assert.equal(fail("audio_queue_down").ru, "Музыка не запустилась — кредиты не списаны, попробуйте ещё раз.");
  // Место музыки истекло в очереди, и все места заняты: дорожка закрыта, кредиты не списаны.
  assert.equal(fail("music_busy").key, "merge.err.music_busy");
  assert.equal(fail("music_busy").ru, "Сейчас готовится много музыки — попробуйте через минуту. Кредиты не списаны.");
  for (const code of ["audio_failed", "audio_unavailable", "audio_overloaded", "audio_not_configured"]) {
    assert.equal(fail(code).key, `merge.err.${code}`, code);
  }
  assert.deepEqual(fail("other", "Текст сервера"), { key: "", ru: "Текст сервера", params: {} });
  assert.equal(fail(null).key, "merge.err.audio_failed");
  assert.equal(fail("audio_price_changed", "Сервер").ru, "Сервер", "код с подстановкой без чисел — текст сервера");

  assert.equal(m.failureText("mix_failed", null).ru, "Не получилось свести звук — кредиты не списаны, попробуйте ещё раз.");
  assert.equal(m.failureText("audio_missing", null).key, "merge.fail.audio_missing");
  assert.ok(MERGE_FAIL_RU.audio_missing.includes("«Звук»"));
  // Склеить нельзя, пока звук делается, — тем же текстом, что отказ сервера.
  const block = m.blockText({ code: "audio_pending" });
  assert.equal(block.key, "merge.err.audio_pending");
  assert.equal(block.ru, MERGE_ERROR_RU.audio_pending);
  assert.equal(m.progressShare({ stage: "mixing", done: 4, total: 4 }), 0.95);
});

test("тексты звука: каждый ключ, который зовёт audioLogic, есть в таблице", () => {
  const keys = [
    "audio_text_empty", "voice_too_long", "audio_voice_id", "audio_start_fragment", "audio_no_voice",
    "audio_prompt_short", "audio_prompt_long", "audio_no_fragments", "audio_settings", "audio_file",
    "audio_too_big", "audio_bad_type", "audio_unreadable", "audio_no_sound", "audio_too_long", "audio_balance",
    "audio_not_found", "audio_ready_locked", "audio_busy", "audio_price_changed", "audio_pending",
    "audio_upload_busy", "audio_failed", "audio_unavailable", "audio_overloaded", "audio_not_configured",
    "audio_stale", "audio_queue_down", "audio_unsupported", "music_busy",
  ];
  for (const k of keys) assert.ok(MERGE_ERROR_RU[k]?.trim(), k);
});

test("повтор того же нажатия: request_id, слепок заказа", () => {
  const id = a.newRequestId();
  assert.ok(a.isRequestId(id), id);
  const fallback = a.newRequestId(() => 0.5);
  assert.ok(a.isRequestId(fallback));
  assert.equal(a.isRequestId("../x"), false);
  assert.equal(a.isRequestId("a".repeat(65)), false);
  assert.equal(a.voiceSignature(" Привет\n мир ", "v1"), a.voiceSignature("Привет мир", "v1"));
  assert.notEqual(a.voiceSignature("Привет", "v1"), a.voiceSignature("Привет", "v2"), "другой голос — другой заказ");
  assert.notEqual(a.voiceSignature("Привет", "v1"), a.voiceSignature("Привет!", "v1"));
  assert.equal(a.voiceSignature.length, 2, "начала голоса в слепке нет (MA_V6 B2)");
  assert.notEqual(a.musicSignature("пианино", 15), a.musicSignature("пианино", 16), "склейка стала длиннее — другой заказ");
});

test("опрос и громкость", () => {
  assert.equal(a.audioPollDelay(0), 3000);
  assert.equal(a.audioPollDelay(120_001), 10000);
  assert.equal(a.clampVolume(0.351, 1, 0.35), 0.35);
  assert.equal(a.clampVolume(3, 2, 1), 2);
  assert.equal(a.clampVolume(-1, 1, 0.35), 0);
  assert.equal(a.clampVolume("x", 1, 0.35), 0.35);
  assert.equal(a.volumePercent(0.35), 35);
  assert.equal(a.volumePercent(Number.NaN), 0);
});

test("голоса мультстудии: имя, ключи словаря, выбор голоса", () => {
  const bella = { id: "EXAVITQu4vr4xnSDxMaL", name: "Bella - Professional, Bright, Warm", description: "", gender: "female", age: "middle_aged" };
  assert.equal(a.voiceShortName(bella), "Bella");
  assert.equal(a.voiceNameKey(bella), "bella");
  assert.deepEqual(a.voiceTailWords(bella), ["Professional", "Bright", "Warm"]);
  assert.deepEqual(a.voiceTailWords({ name: "River", description: "calm and neutral" }), ["calm", "neutral"]);
  assert.equal(a.voiceWordKey("Middle-Aged"), "middle_aged");
  assert.equal(a.voiceWordKey(bella.age), "middle_aged");
  const list = [{ id: "v1" }, { id: "v2" }];
  assert.equal(a.pickVoice(list, "v2", "v1"), "v2");
  assert.equal(a.pickVoice(list, "gone", "v1"), "v1", "выбранного нет в списке — запомненный");
  assert.equal(a.pickVoice(list, "", null), "v1");
  assert.equal(a.pickVoice([], "v1"), "");
});

test("ответ на заказ не дошёл: тот же заказ — тот же request_id, сервер говорит, что вышло", () => {
  const mark = { project: "p1", sig: "v1|0|Привет", id: "r-1" };
  let made = 0;
  const make = () => `new-${++made}`;
  assert.equal(a.requestIdFor(mark, "p1", "v1|0|Привет", make), "r-1", "повтор того же нажатия");
  assert.equal(a.requestIdFor(mark, "p1", "v1|0|Привет!", make), "new-1", "текст поменяли — новый заказ");
  assert.equal(a.requestIdFor(mark, "p2", "v1|0|Привет", make), "new-2", "другая склейка");
  assert.equal(a.requestIdFor(null, "p1", "x", make), "new-3");

  const voice = track();
  const pending = track({ id: "f".repeat(32), status: "pending", url: null });
  assert.equal(a.afterLostAnswer("old", { ready: voice, pending: null, failed: null }), "done", "голос сменился — заказ выполнен");
  assert.equal(a.afterLostAnswer(voice.id, { ready: voice, pending: pending, failed: null }), "pending");
  assert.equal(a.afterLostAnswer(voice.id, { ready: voice, pending: null, failed: null }), "lost");
  assert.equal(a.afterLostAnswer(null, { ready: null, pending: null, failed: null }), "lost");
  // С ключом заказа (MA_FIX6) — по его дорожке: чужой готовый или делающийся звук — не он.
  const mine = track({ id: "m".repeat(32), request_id: "r-1" });
  const theirs = track({ id: "t".repeat(32), request_id: "r-other" });
  const minePending = track({ id: "n".repeat(32), status: "pending", url: null, request_id: "r-1" });
  assert.equal(a.afterLostAnswer(null, { ready: mine, pending: null, failed: null }, "r-1"), "done");
  assert.equal(a.afterLostAnswer(null, { ready: theirs, pending: null, failed: null }, "r-1"), "lost", "готов звук другой вкладки");
  assert.equal(a.afterLostAnswer(null, { ready: theirs, pending: minePending, failed: null }, "r-1"), "pending");
  assert.equal(a.afterLostAnswer(null, { ready: null, pending: pending, failed: null }, "r-1"), "lost", "делается чужой заказ");
  assert.equal(a.afterLostAnswer(null, { ready: voice, pending: null, failed: null }, "r-1"), "lost", "ключа у дорожки нет");
});

test("ползунки и «Звук роликов»: своё значение снимается, когда правка вернулась, новое — остаётся", () => {
  assert.deepEqual(a.settleLocal({ clip: "off", music: 0.5 }, { clip_sound: "off" }), { clip: undefined, music: 0.5, voice: undefined, start: undefined });
  assert.deepEqual(
    a.settleLocal({ music: 0.6 }, { music_volume: 0.5 }),
    { clip: undefined, music: 0.6, voice: undefined, start: undefined },
    "человек успел сдвинуть ещё раз — его значение на месте",
  );
  assert.equal(a.settleLocal({ voice: 1.2 }, { voice_volume: 1.2 }).voice, undefined);
  assert.equal(a.settleLocal({ start: 2 }, { voice_start_fragment: 2 }).start, undefined);
  assert.equal(a.settleLocal({ start: 2 }, { clip_sound: "keep" }).start, 2, "другое поле не трогаем");
});

test("пробелы — как str.split() сервера: U+001C–U+001F и U+0085 схлопываются, U+FEFF — символ", () => {
  // Python: " ".join("а\u001cб\u0085в\ufeffг".split()) == "а б в\ufeffг" (7 символов).
  assert.equal(a.cleanText("а\u001cб\u0085в\ufeffг"), "а б в\ufeffг");
  assert.equal(a.textChars("а\u001cб\u0085в\ufeffг"), 7);
  for (const ch of ["\t", "\n", "\v", "\f", "\r", " ", "\u001d", "\u001e", "\u001f", "\u00a0", "\u1680", "\u2000", "\u200a",
    "\u2028", "\u2029", "\u202f", "\u205f", "\u3000"]) {
    assert.equal(a.cleanText(`x${ch}${ch}y`), "x y", `U+${ch.codePointAt(0).toString(16)}`);
  }
  assert.equal(a.cleanText("x\u200by"), "x\u200by", "нулевой ширины — не пробел и у сервера");
  // У границы цены (250 символов → 5 кр, 251 → 6 кр) расхождение было бы на 1 кр и вечный audio_price_changed.
  const near = "а".repeat(249) + "\u001c" + "б";
  assert.equal(a.textChars(near), 251);
  assert.equal(a.voicePrice(near), 6);
  assert.equal(a.voicePrice("а".repeat(250) + "\ufeff"), 6, "U+FEFF сервер считает символом");
});

test("голос едет за своим роликом: перестановка, удаление, вставка в начало", () => {
  // Четыре фрагмента, голос — с №3 (индекс 2).
  const move = (from, to) => ({ kind: "move", from, to });
  assert.equal(a.followStart(2, 4, move(2, 0)), 0, "сам ролик голоса перенесли в начало");
  assert.equal(a.followStart(2, 4, move(0, 3)), 1, "ролик перед голосом унесли за него");
  assert.equal(a.followStart(2, 4, move(3, 0)), 3, "ролик после голоса поставили перед ним");
  assert.equal(a.followStart(2, 4, move(0, 1)), 2, "перестановка перед голосом — номер тот же");
  assert.equal(a.followStart(2, 4, move(3, 9)), 2, "за краем — к краю, голос не задет");
  assert.equal(a.followStart(2, 4, move(2, 9)), 3, "ролик голоса — в конец");
  assert.equal(a.followStart(2, 4, move(7, 0)), 2, "нет такого фрагмента — ничего не меняем");
  const remove = (index) => ({ kind: "remove", index });
  assert.equal(a.followStart(2, 4, remove(0)), 1, "убрали фрагмент перед голосом");
  assert.equal(a.followStart(2, 4, remove(3)), 2, "убрали фрагмент после голоса");
  assert.equal(a.followStart(2, 4, remove(2)), 2, "убрали сам ролик — на его месте следующий");
  assert.equal(a.followStart(3, 4, remove(3)), 2, "голос был на последнем — новый последний");
  assert.equal(a.followStart(0, 1, remove(0)), 0);
  assert.equal(a.followStart(9, 4, remove(0)), 2, "номер за концом — как у сервера, с последнего");
  assert.equal(a.followStart(2, 4, { kind: "insert", index: 0 }), 3, "ролик добавили в начало");
  assert.equal(a.followStart(0, 4, { kind: "insert", index: 0 }), 1);
  assert.equal(a.followStart(2, 4, { kind: "insert", index: 4 }), 2, "в конец — голос не задет");
  assert.equal(a.followStart(0, 0, { kind: "insert", index: 0 }), 0, "фрагментов не было");
});

test("голос длиннее остатка ролика — сколько секунд обрежется", () => {
  const items = [frag(5), frag(3), frag(4)];
  assert.equal(a.voiceCutS(3, 0, items), 0, "помещается");
  assert.equal(a.voiceCutS(10, 2, items), 6, "с №3 (с 8 с) осталось 4 с из 12");
  assert.equal(a.voiceCutS(4.3, 2, items), 0, "лишние 0,3 с — не пугаем");
  assert.equal(a.voiceCutS(4.6, 2, items), 0.6);
  assert.equal(a.voiceCutS(10, 9, items), 6, "номер за концом — с последнего");
  assert.equal(a.voiceCutS(null, 0, items), 0);
  assert.equal(a.voiceCutS(5, 0, []), 0);
});

/** Таймеры по команде теста: fire() — палец остановился. */
function fakeTimers() {
  let next = 1;
  const pending = new Map();
  return {
    set: (fn) => {
      const id = next++;
      pending.set(id, fn);
      return id;
    },
    clear: (id) => pending.delete(id),
    fire: () => {
      for (const [id, fn] of [...pending]) {
        pending.delete(id);
        fn();
      }
    },
    get size() {
      return pending.size;
    },
  };
}

/** Отправка, которой тест отвечает сам: answer(true) — принята, answer(false) — отказ. */
function fakeServer() {
  const sent = [];
  const answers = [];
  return {
    sent,
    run: (body) =>
      new Promise((resolve) => {
        sent.push(body);
        answers.push(resolve);
      }),
    answer: (ok) => answers.shift()(ok),
  };
}

const tick = () => new Promise((resolve) => setImmediate(resolve));

test("правки звука перед «Склеить»: отложенный ползунок уходит сразу, запуск ждёт всю очередь", async () => {
  const timers = fakeTimers();
  const server = fakeServer();
  const q = a.settingsQueue(server.run, timers);
  q.send({ clip_sound: "quiet" });
  q.later("music", () => ({ music_volume: 0.2 }), 350);
  await tick();
  assert.deepEqual(server.sent, [{ clip_sound: "quiet" }], "по одной: ползунок ждёт и палец, и очередь");
  let done = null;
  const flushed = q.flush().then((ok) => (done = ok));
  assert.equal(timers.size, 0, "отложенное ушло сразу, не дожидаясь 350 мс");
  await tick();
  assert.equal(done, null, "«Тише» ещё в пути — запуск ждёт");
  server.answer(true);
  await tick();
  assert.deepEqual(server.sent, [{ clip_sound: "quiet" }, { music_volume: 0.2 }], "порядок — как нажимали");
  assert.equal(done, null);
  server.answer(true);
  await flushed;
  assert.equal(done, true);
});

test("правки звука: отказ в пути — запуск не идёт; прежний отказ (уже показан) не мешает", async () => {
  const timers = fakeTimers();
  const server = fakeServer();
  const q = a.settingsQueue(server.run, timers);
  q.send({ clip_sound: "off" });
  await tick();
  server.answer(false);
  await tick();
  // Этот отказ был до «Склеить»: панель его показала и вернула прежнее значение.
  const quiet = q.flush();
  assert.equal(await quiet, true);
  q.send({ voice_start_fragment: 2 });
  const refused = q.flush();
  await tick();
  server.answer(false);
  assert.equal(await refused, false, "сервер не принял правку, ушедшую перед запуском");
  // Отправка упала исключением — это тоже отказ, и очередь живёт дальше.
  const broken = a.settingsQueue(async () => {
    throw new Error("сеть");
  }, timers);
  broken.send({ clip_sound: "keep" });
  assert.equal(await broken.flush(), false);
  assert.equal(await broken.flush(), true);
});

test("правки звука: тот же ползунок — последнее значение; ушли со страницы — отложенное забыто", async () => {
  const timers = fakeTimers();
  const server = fakeServer();
  const q = a.settingsQueue(server.run, timers);
  let volume = 0.1;
  q.later("voice", () => ({ voice_volume: volume }), 350);
  volume = 0.7;
  q.later("voice", () => ({ voice_volume: volume }), 350);
  q.later("start", () => null, 350);
  assert.equal(timers.size, 2, "второе движение заменило первое");
  timers.fire();
  await tick();
  assert.deepEqual(server.sent, [{ voice_volume: 0.7 }], "null — отправлять нечего (склейку сменили)");
  server.answer(true);
  q.later("music", () => ({ music_volume: 0.3 }), 350);
  q.cancel();
  assert.equal(timers.size, 0);
  assert.equal(await q.flush(), true);
  assert.equal(server.sent.length, 1);
});

test("после music_busy «Создать» ждёт минуту, как сказано в отказе, потом снова работает (MA_FIX4, MA_FIX5)", () => {
  // MA_FIX5: было 45 с при тексте сервера «попробуйте через минуту» — теперь одно и то же.
  assert.equal(a.MUSIC_BUSY_COOLDOWN_MS, 60_000);
  const t0 = 1_700_000_000_000;
  const busy = { code: "music_busy" };
  const until = a.musicCooldownUntil(busy, t0);
  assert.equal(until, t0 + 60_000);
  assert.equal(a.cooldownLeft(until, t0), 60, "сразу после отказа — 60 с");
  assert.equal(a.cooldownLeft(until, t0 + 1), 60, "неполная секунда — целая");
  assert.equal(a.cooldownLeft(until, t0 + 59_001), 1);
  assert.equal(a.cooldownLeft(until, t0 + 60_000), 0, "минута прошла — кнопка снова работает");
  assert.equal(a.cooldownLeft(until, t0 + 90_000), 0);
  assert.equal(a.cooldownLeft(0, t0), 0, "ожидания не было");
  // Другие отказы ожидания не начинают и не сбрасывают.
  for (const code of ["throttled", "audio_busy", "insufficient_balance", "audio_failed", "network"]) {
    assert.equal(a.musicCooldownUntil({ code }, t0 + 10_000, until), until, code);
    assert.equal(a.musicCooldownUntil({ code }, t0), 0, code);
  }
  assert.equal(a.musicCooldownUntil(null, t0, until), until);
  // Второй music_busy (после ожидания) — снова минута от него; раньше срока ожидание не короче.
  assert.equal(a.musicCooldownUntil(busy, t0 + 70_000, until), t0 + 130_000);
  assert.equal(a.musicCooldownUntil(busy, t0 - 10_000, until), until);
  // Отказ сервера (429) — тот же текст, что в плашке; подсказка у кнопки — свой ключ.
  assert.deepEqual(a.audioErrorText({ code: "music_busy", message: "", data: {} }), {
    key: "merge.err.music_busy",
    ru: "Сейчас готовится много музыки — попробуйте через минуту. Кредиты не списаны.",
    params: {},
  });
});

test("музыка не сделалась — форма повтора с её описанием (MA_FIX4)", () => {
  const failed = track({ kind: "music", status: "failed", prompt: "спокойное пианино", error_code: "music_busy" });
  assert.equal(a.retryPrompt("", failed), "спокойное пианино");
  assert.equal(a.retryPrompt("  \n ", failed), "спокойное пианино", "одни пробелы — поле пустое");
  assert.equal(a.retryPrompt("джаз", failed), "джаз", "набранное не трогаем");
  assert.equal(a.retryPrompt("", null), "");
  assert.equal(a.retryPrompt("", undefined), "");
  assert.equal(a.retryPrompt("", { ...failed, source: "upload", prompt: "" }), "", "свой трек описания не имеет");
  assert.equal(a.retryPrompt("", { ...failed, prompt: "   " }), "");
  // Неудачная — последняя по времени у своего вида (trackSlot), её и берём.
  const slot = a.trackSlot(
    [
      track({ id: "a".repeat(32), kind: "music", status: "ready", prompt: "старая готовая" }),
      track({ id: "b".repeat(32), kind: "music", status: "failed", prompt: "первая попытка" }),
      track({ id: "c".repeat(32), kind: "music", status: "failed", prompt: "вторая попытка" }),
    ],
    "music",
  );
  assert.equal(a.retryPrompt("", slot.failed), "вторая попытка");
});

test("ожидание голоса зависит от длины текста: до 600 символов — секунды, длиннее — до минуты (MA_FIX4)", () => {
  assert.equal(a.VOICE_LONG_CHARS, 600);
  assert.equal(a.voiceWait(""), "short");
  assert.equal(a.voiceWait(null), "short");
  assert.equal(a.voiceWait(undefined), "short");
  assert.equal(a.voiceWait("я".repeat(600)), "short");
  assert.equal(a.voiceWait("я".repeat(601)), "long");
  assert.equal(a.voiceWait("я".repeat(2000)), "long");
  // Считается так же, как счётчик: пробелы схлопываются, смайлик — один символ.
  assert.equal(a.voiceWait(`${"я".repeat(300)}\n\n\n   ${"я".repeat(299)}`), "short", "300 + пробел + 299 = 600");
  assert.equal(a.voiceWait("😀".repeat(600)), "short");
  assert.equal(a.voiceWait("😀".repeat(601)), "long");
});

test("новые тексты MA_FIX4 есть в ru/en/kg, подстановки на месте", async () => {
  const { readFileSync } = await import("node:fs");
  const get = (lang, key) =>
    key.split(".").reduce((o, k) => (o && typeof o === "object" ? o[k] : undefined), JSON.parse(readFileSync(new URL(`../../locales/${lang}/vstudio.json`, import.meta.url), "utf8")));
  const keys = {
    "merge.audio.voice.runningHintLong": "Текст длинный — это может занять до минуты.",
    "merge.audio.voice.pendingLong": "Голос озвучивается — длинный текст может занять до минуты.",
    "merge.audio.music.busyWait": "Сейчас готовится много музыки — попробуйте через {{n}} с.",
  };
  for (const [key, ru] of Object.entries(keys)) {
    assert.equal(get("ru", key), ru, key);
    for (const lang of ["en", "kg"]) {
      const text = get(lang, key);
      assert.ok(typeof text === "string" && text.trim() && text !== ru, `${lang} ${key}`);
      assert.equal(text.includes("{{n}}"), ru.includes("{{n}}"), `${lang} ${key}: {{n}}`);
    }
  }
});

test("плашка music_busy и отсчёт под «Создать» говорят одно: «попробуйте через минуту» = 60 с (MA_FIX5)", async () => {
  const { existsSync, readFileSync } = await import("node:fs");
  const locale = (lang) => JSON.parse(readFileSync(new URL(`../../locales/${lang}/vstudio.json`, import.meta.url), "utf8"));
  const banner = MERGE_ERROR_RU.music_busy;
  // Текст сервера (merge.audio.MSG_MUSIC_BUSY, CONTRACT_M §10.4/§10.7) — тот же, что в плашке
  // (сверяем, когда рядом лежит и сервер — в полном дереве репозитория).
  const backend = new URL("../../../../core/merge/audio.py", import.meta.url);
  if (existsSync(backend)) {
    const server = readFileSync(backend, "utf8").match(/^MSG_MUSIC_BUSY = "(.*)"$/m);
    assert.ok(server, "MSG_MUSIC_BUSY в merge/audio.py");
    assert.equal(server[1], banner);
  }
  assert.match(banner, /попробуйте через минуту/);
  assert.equal(a.MUSIC_BUSY_COOLDOWN_MS / 1000, 60, "минута в тексте — минута ожидания");
  // Отсчёт — тем же советом: «попробуйте через {{n}} с.», в начале отсчёта n = 60.
  const ru = locale("ru").merge.audio.music.busyWait;
  assert.equal(ru, "Сейчас готовится много музыки — попробуйте через {{n}} с.");
  const en = locale("en").merge;
  assert.match(en.err.music_busy, /try again in a minute/);
  assert.match(en.audio.music.busyWait, /try again in \{\{n\}\} s\./);
  const kg = locale("kg").merge;
  assert.match(kg.err.music_busy, /бир мүнөттөн кийин кайра аракет кылыңыз/);
  assert.match(kg.audio.music.busyWait, /\{\{n\}\} секунддан кийин кайра аракет кылыңыз/);
  for (const lang of ["ru", "en", "kg"]) {
    const m = locale(lang).merge;
    assert.equal(m.err.music_busy.split(" — ")[0], m.audio.music.busyWait.split(" — ")[0], `${lang}: одно начало`);
  }
});

test("форма повтора музыки: описание неудачной — один раз на склейку; ушли и вернулись — снова (MA_FIX5)", () => {
  const f1 = track({ id: "f".repeat(32), kind: "music", status: "failed", prompt: "спокойное пианино" });
  // Склейка X: музыка не вышла — поле пустое, описание подставлено, метка — её id.
  const step = a.prefillStep(null, f1, "");
  assert.deepEqual(step, { mark: f1.id, prompt: "спокойное пианино" });
  // Тот же ответ ещё раз (опрос), поле стёрли руками — второй раз не заполняем.
  assert.deepEqual(a.prefillStep(step.mark, f1, ""), { mark: f1.id, prompt: "" });
  // Ушли в другую склейку: черновик пуст, хук забывает метку (null при смене склейки).
  // Вернулись в X с той же неудачной музыкой — форма снова с её описанием (V4 frontend W3).
  assert.deepEqual(a.prefillStep(null, f1, ""), { mark: f1.id, prompt: "спокойное пианино" });
  // Набранное не трогаем, свой трек описания не даёт, неудачной нет — ничего.
  assert.deepEqual(a.prefillStep(null, f1, "джаз"), { mark: f1.id, prompt: "джаз" });
  assert.deepEqual(a.prefillStep(null, { ...f1, source: "upload", prompt: "" }, ""), { mark: f1.id, prompt: "" });
  assert.deepEqual(a.prefillStep("x", null, "текст"), { mark: "x", prompt: "текст" });
  // Новая неудачная после метки прежней — снова заполняем.
  const f2 = { ...f1, id: "e".repeat(32), prompt: "бодрый поп" };
  assert.deepEqual(a.prefillStep(f1.id, f2, ""), { mark: f2.id, prompt: "бодрый поп" });
});

// Шаги useMergeAudio вокруг request_id на настоящих функциях audioLogic: нажатие (makeVoice/makeMusic —
// метка по последнему известному состоянию), fail() после потерянного ответа (перечитывание; null — не
// дошло) и опрос (apply). mark — что хук бережёт в retry.current[kind].
function retryFlow(kind, project, sig) {
  let mark = null;
  let seq = 0;
  const make = () => `${kind}-req-${++seq}`;
  return {
    get mark() {
      return mark;
    },
    click(known, s = sig) {
      if (a.retryVerdict(mark, project, known, kind, false) !== "keep") mark = null;
      mark = a.retryMarkFor(mark, project, s, make);
      return mark.id;
    },
    lost(fresh) {
      if (!fresh) return "no-reload";
      const held = mark;
      const own = held && held.project === project ? held.id : null;
      const outcome = a.afterLostAnswer(null, a.trackSlot(fresh, kind), own);
      if (a.retryVerdict(mark, project, fresh, kind, false) !== "keep") mark = null;
      return outcome;
    },
    // Отказ (не обрыв связи) — как fail(): метку снимает только сбой провайдера на сам этот заказ
    // (order — его request_id) или звук склейки после перечитывания (fresh; null — не дошло).
    refused(err, opts = {}, fresh = null) {
      if (opts.order && mark?.id === opts.order && a.orderFailedHere(err)) mark = null;
      if (err.status === 400 || err.status === 429 || !fresh) return;
      if (a.retryVerdict(mark, project, fresh, kind, false) !== "keep") mark = null;
    },
    poll(state, inFlight = false) {
      if (a.retryVerdict(mark, project, state, kind, inFlight) !== "keep") mark = null;
    },
  };
}

test("request_id заказа, ответ на который не дошёл, снимает только его собственная неудача — по request_id дорожки (MA_FIX6)", () => {
  const X = "a".repeat(32);
  for (const kind of ["voice", "music"]) {
    const t = (status, request_id) => track({ id: `${kind}-${status}-${request_id}`, kind, status, url: null, request_id });
    const mark = { project: X, sig: "s", id: "req-1" };
    const verdict = (tracks, opts = {}) => a.retryVerdict(opts.mark === undefined ? mark : opts.mark, opts.project ?? X, tracks, kind, opts.inFlight ?? false);
    // Не вышел именно он — снимаем; сделан — метка больше не нужна.
    assert.equal(verdict([t("failed", "req-1")]), "drop", kind);
    assert.equal(verdict([t("ready", "req-0"), t("failed", "req-1")]), "drop", `${kind}: рядом прежняя готовая`);
    assert.equal(verdict([t("ready", "req-1")]), "done", kind);
    // Всё остальное id бережёт: повтор тем же id сервер отдаст той же дорожкой (200), второго списания нет.
    assert.equal(verdict([t("pending", "req-1")]), "keep", `${kind}: ещё делается`);
    assert.equal(verdict([t("failed", "req-0")]), "keep", `${kind}: прежняя неудачная на экране`);
    assert.equal(verdict([t("failed", null)]), "keep", `${kind}: неудачная без ключа`);
    assert.equal(verdict([t("failed", "tab-2")]), "keep", `${kind}: неудачная из другой вкладки`);
    assert.equal(verdict([t("ready", "tab-2")]), "keep", `${kind}: готов звук другой вкладки`);
    assert.equal(verdict([t("pending", "tab-2")]), "keep", `${kind}: делается заказ другой вкладки`);
    assert.equal(verdict([]), "keep", `${kind}: его дорожки ещё нет`);
    assert.equal(verdict(null), "keep", `${kind}: перечитывание не дошло`);
    assert.equal(verdict(undefined), "keep", `${kind}: состояние склейки ещё не пришло`);
    // В пути, другая склейка, метки нет, ключ совпал у другого вида — не трогаем.
    assert.equal(verdict([t("failed", "req-1")], { inFlight: true }), "keep", kind);
    assert.equal(verdict([t("failed", "req-1")], { project: "b".repeat(32) }), "keep", kind);
    assert.equal(verdict([t("failed", "req-1")], { mark: null }), "keep", kind);
    const otherKind = kind === "voice" ? "music" : "voice";
    assert.equal(verdict([track({ id: "x", kind: otherKind, status: "failed", url: null, request_id: "req-1" })]), "keep", kind);
  }
  // Метка — склейка, слепок и id: повтор того же — та же метка, иначе новый id.
  let n = 0;
  const make = () => `req-${++n}`;
  const mark = a.retryMarkFor(null, X, "s", make);
  assert.deepEqual(mark, { project: X, sig: "s", id: "req-1" });
  assert.equal(a.retryMarkFor(mark, X, "s", make), mark);
  assert.deepEqual(a.retryMarkFor(mark, X, "s!", make), { project: X, sig: "s!", id: "req-2" });
  assert.deepEqual(a.retryMarkFor(mark, "b".repeat(32), "s", make), { project: "b".repeat(32), sig: "s", id: "req-3" });
  assert.equal(a.requestIdFor(mark, X, "s", make), "req-1");
  assert.equal(a.dropRetry, undefined, "эвристика по id неудачной на экране убрана");
});

test("путь хука: прежняя неудачная, неудачная другой вкладки, перечитывание не дошло — повтор тем же request_id; своя неудача — новый; свой успех — метка снята (MA_FIX6)", () => {
  const X = "a".repeat(32);
  for (const kind of ["voice", "music"]) {
    const sig = kind === "voice" ? a.voiceSignature("Привет! Это голос за кадром.", "v1") : a.musicSignature("пианино", 15);
    const t = (status, request_id) => track({ id: `${kind}-${status}-${request_id}`, kind, status, url: null, request_id, prompt: "пианино" });
    const old = t("failed", "req-old");

    // 1) Прежняя неудачная на экране, ответ потерян, перечитывание не дошло — тот же id (MA_V5 B1).
    let flow = retryFlow(kind, X, sig);
    const first = flow.click([old]);
    assert.equal(flow.lost(null), "no-reload");
    assert.equal(flow.click([old]), first, `${kind}: прежняя неудачная + потерянный ответ`);
    // Перечитывание дошло раньше самого запроса — на сервере всё та же прежняя неудачная.
    assert.equal(flow.lost([old]), "lost");
    assert.equal(flow.click([old]), first, `${kind}: перечитывание обогнало запрос`);

    // 2) Неудачная из другой вкладки (её ключ другой), которую эта вкладка раньше не видела — тот же id
    //    (остаток MA_FIX5-REFIX: раньше такая «другая неудачная» снимала id).
    flow = retryFlow(kind, X, sig);
    const mine = flow.click([]);
    const tab = t("failed", "tab-2");
    assert.equal(flow.lost([tab]), "lost");
    flow.poll([tab]);
    assert.equal(flow.click([tab]), mine, `${kind}: неудачная другой вкладки`);

    // 3) Своя неудача — следующее нажатие новый заказ: через перечитывание и через опрос.
    flow = retryFlow(kind, X, sig);
    const lostOne = flow.click([old]);
    assert.equal(flow.lost([t("failed", lostOne)]), "lost");
    assert.equal(flow.mark, null, kind);
    const fresh = flow.click([t("failed", lostOne)]);
    assert.notEqual(fresh, lostOne, `${kind}: своя неудача — новый id`);
    flow = retryFlow(kind, X, sig);
    const polled = flow.click([]);
    assert.equal(flow.lost([t("pending", polled)]), "pending");
    flow.poll([t("pending", polled)]);
    assert.equal(flow.mark?.id, polled, `${kind}: делается — бережём`);
    flow.poll([t("failed", polled)], true);
    assert.equal(flow.mark?.id, polled, `${kind}: пока заказ в пути, опрос не трогает`);
    flow.poll([t("failed", polled)]);
    assert.equal(flow.mark, null, `${kind}: опрос увидел свою неудачу`);
    assert.notEqual(flow.click([t("failed", polled)]), polled);

    // 4) Свой успех снимает метку: перечитывание — «сделан», опрос после «делается» — тоже.
    flow = retryFlow(kind, X, sig);
    const made = flow.click([old]);
    assert.equal(flow.lost([t("ready", made)]), "done");
    assert.equal(flow.mark, null, `${kind}: свой успех`);
    assert.notEqual(flow.click([t("ready", made)]), made, `${kind}: после успеха нажатие — уже новый заказ`);
    flow = retryFlow(kind, X, sig);
    const slow = flow.click([]);
    assert.equal(flow.lost([t("pending", slow)]), "pending");
    flow.poll([t("ready", slow)]);
    assert.equal(flow.mark, null, `${kind}: опрос увидел свой успех`);
    // Чужой успех — не его: id бережём (раньше «голос сменился» снимал метку и закрывал форму).
    flow = retryFlow(kind, X, sig);
    const waiting = flow.click([]);
    assert.equal(flow.lost([t("ready", "tab-2")]), "lost");
    assert.equal(flow.click([t("ready", "tab-2")]), waiting, `${kind}: готов звук другой вкладки`);
  }
});

test("форма повтора музыки не меняет id заказа, который бережём; своя неудача — новый заказ (MA_FIX5 V4 W3, MA_FIX6)", () => {
  const X = "a".repeat(32);
  const prompt = "спокойное пианино";
  const sig = a.musicSignature(prompt, 15);
  const mark = { project: X, sig, id: "req-1" };
  const own = track({ id: "q".repeat(32), kind: "music", status: "failed", prompt, error_code: "audio_failed", request_id: "req-1" });
  const older = track({ id: "o".repeat(32), kind: "music", status: "failed", prompt: "бодрый поп", request_id: "req-0" });
  const olderSame = { ...older, prompt };
  // Своя неудача: метку сняли — подстановка разрешена, слепок тот же, а id новый (не 200 той же неудачной).
  assert.equal(a.retryVerdict(mark, X, [own], "music", false), "drop");
  assert.equal(a.prefillKeepsRetry(null, X, own, 15), true);
  const filled = a.prefillStep(null, own, "").prompt;
  assert.equal(a.musicSignature(filled, 15), sig);
  assert.equal(a.requestIdFor(null, X, a.musicSignature(filled, 15), () => "req-2"), "req-2");
  // Метку бережём (прежняя неудачная на экране): описание другого заказа не подставляем — нажатие ушло бы
  // с новым id; то же описание — подставляем, id прежний.
  assert.equal(a.retryVerdict(mark, X, [older], "music", false), "keep");
  assert.equal(a.prefillKeepsRetry(mark, X, older, 15), false);
  assert.equal(a.prefillKeepsRetry(mark, X, olderSame, 15), true);
  assert.equal(a.requestIdFor(mark, X, a.musicSignature(a.prefillStep(null, olderSame, "").prompt, 15)), "req-1");
  assert.equal(a.prefillKeepsRetry(mark, X, olderSame, 16), false, "склейка стала длиннее — другой слепок");
  // Метка другой склейки или её нет — форма заполняется как раньше.
  assert.equal(a.prefillKeepsRetry(mark, "b".repeat(32), older, 15), true);
  assert.equal(a.prefillKeepsRetry(null, X, older, 15), true);
  // Повтор всё же ушёл (неудача случилась между опросами): 200 с неудачной дорожкой — отказ, а не «создаётся».
  const pending = track({ id: "p".repeat(32), kind: "music", status: "pending", prompt });
  const ready = track({ id: "r".repeat(32), kind: "music", status: "ready", prompt: "старая" });
  assert.equal(a.replayedFailure(own), true);
  assert.equal(a.replayedFailure(pending), false);
  assert.equal(a.replayedFailure(ready), false);
  assert.equal(a.replayedFailure(undefined), false);
  assert.deepEqual(a.trackErrorText(own), { key: "merge.err.audio_failed", ru: MERGE_ERROR_RU.audio_failed, params: {} });
});

const refusal = (status, code) => ({ status, code, message: "", data: {} });

test("сбой заказа: метку снимает только 502 сервера с кодом провайдера на сам заказ (MA_V6 B1)", () => {
  for (const code of ["audio_failed", "audio_unavailable", "audio_overloaded"]) {
    assert.equal(a.orderFailedHere(refusal(502, code)), true, code);
  }
  // Страница Cloudflare 502 (без нашего кода), отказы до заказа и отказы, которые решаются раньше ключа.
  assert.equal(a.orderFailedHere(refusal(502, "server_error")), false, "502 без нашего кода — обрыв");
  assert.equal(a.orderFailedHere(refusal(503, "audio_not_configured")), false, "503 бывает и до поиска ключа");
  assert.equal(a.orderFailedHere(refusal(429, "throttled")), false);
  assert.equal(a.orderFailedHere(refusal(429, "music_busy")), false);
  assert.equal(a.orderFailedHere(refusal(400, "audio_too_long")), false);
  assert.equal(a.orderFailedHere(refusal(402, "insufficient_balance")), false);
  assert.equal(a.orderFailedHere(refusal(409, "audio_busy")), false);
  assert.equal(a.orderFailedHere(refusal(0, "network")), false);
});

test("отказ не снимает request_id заказа, ответ на который не дошёл: 429, свой трек, music_busy (MA_V6 B1, F1–F4)", () => {
  const X = "a".repeat(32);
  for (const kind of ["voice", "music"]) {
    const sig = kind === "voice" ? a.voiceSignature("Привет", "v1") : a.musicSignature("пианино", 15);
    const t = (status, request_id) => track({ id: `${kind}-${status}-${request_id}`, kind, status, url: null, request_id });

    // F1: ответ и перечитывание потеряны, повтор получил 429 throttled (до поиска ключа) — тот же id.
    let flow = retryFlow(kind, X, sig);
    const first = flow.click([]);
    assert.equal(flow.lost(null), "no-reload");
    flow.refused(refusal(429, "throttled"), { order: first });
    assert.equal(flow.click([]), first, `${kind}: 429 throttled`);

    // F2: свой трек отклонён 400 (перечитывания нет) — метка заказа не его, тот же id.
    flow = retryFlow(kind, X, sig);
    const f2 = flow.click([]);
    flow.lost(null);
    flow.refused(refusal(400, "audio_too_long"), { upload: true });
    assert.equal(flow.click([]), f2, `${kind}: отказ своего трека`);

    // F3: свой трек — 409 audio_busy, перечитывание показало заказ «делается», потом он готов —
    // метку снимает его готовая дорожка (форма закроется, если в ней тот же заказ).
    flow = retryFlow(kind, X, sig);
    const f3 = flow.click([t("ready", "m0")]);
    flow.lost(null);
    flow.refused(refusal(409, "audio_busy"), { upload: true }, [t("ready", "m0"), t("pending", f3)]);
    assert.equal(flow.mark?.id, f3, `${kind}: 409 своего трека`);
    flow.poll([t("ready", f3)]);
    assert.equal(flow.mark, null, `${kind}: заказ готов — метка снята`);

    // F4: повтор обогнал сам заказ и получил music_busy (или 402, 409) — тот же id.
    for (const [status, code] of [[429, "music_busy"], [402, "insufficient_balance"], [409, "audio_price_changed"], [409, "audio_busy"]]) {
      flow = retryFlow(kind, X, sig);
      const id = flow.click([]);
      flow.lost(null);
      flow.refused(refusal(status, code), { order: id }, []);
      assert.equal(flow.click([]), id, `${kind}: ${code}`);
    }
    // ✕ прежней неудачной отклонён — его отказ метку заказа не трогает.
    flow = retryFlow(kind, X, sig);
    const kept = flow.click([t("failed", "old")]);
    flow.lost(null);
    flow.refused(refusal(409, "render_in_progress"), {}, [t("failed", "old")]);
    assert.equal(flow.click([t("failed", "old")]), kept, `${kind}: отказ удаления дорожки`);

    // Своя неудача снимает: 502 провайдера на сам заказ (и перечитывание не дошло) — следующее нажатие новое.
    flow = retryFlow(kind, X, sig);
    const k7 = flow.click([]);
    flow.refused(refusal(502, "audio_failed"), { order: k7 });
    assert.equal(flow.mark, null, `${kind}: сбой провайдера на сам заказ`);
    assert.notEqual(flow.click([]), k7);
    // …но не чужой: 502 пришёл на заказ с другим id — метку не трогаем.
    flow = retryFlow(kind, X, sig);
    const mine = flow.click([]);
    flow.refused(refusal(502, "audio_failed"), { order: "other" });
    assert.equal(flow.mark?.id, mine, kind);
    // Страница 502 без нашего кода — обрыв, не отказ: метку бережём.
    assert.equal(flow.lost(null), "no-reload");
    assert.equal(flow.click([]), mine, `${kind}: 502 Cloudflare`);
    // Отказ, после которого перечитывание показало свою неудачу, — снимаем; свой успех — тоже.
    flow = retryFlow(kind, X, sig);
    const own = flow.click([]);
    flow.refused(refusal(409, "audio_busy"), { upload: true }, [t("failed", own)]);
    assert.equal(flow.mark, null, `${kind}: своя неудача после отказа`);
    flow = retryFlow(kind, X, sig);
    const made = flow.click([]);
    flow.refused(refusal(404, "audio_not_found"), {}, [t("ready", made)]);
    assert.equal(flow.mark, null, `${kind}: свой успех после отказа`);
  }
});

test("голос едет за своим роликом и после потерянного ответа: слепок без начала, повтор двигает его (MA_V6 B2)", () => {
  const X = "a".repeat(32);
  const text = "Привет! Это голос за кадром.";
  // H1: начало со 2-го ролика, ответ потерян; первый ролик убрали — начало поехало на 0 (тот же ролик).
  const before = 1;
  const after = a.followStart(before, 1, { kind: "remove", index: 0 });
  assert.equal(after, 0);
  const flow = retryFlow("voice", X, a.voiceSignature(text, "v1"));
  const id = flow.click([]);
  flow.lost(null);
  assert.equal(flow.click([], a.voiceSignature(text, "v1")), id, "тот же текст и голос — тот же заказ");
  // Сервер ответил 200 той же дорожкой с прежним номером — двигаем к выбранному ролику (PATCH, бесплатно).
  const replayed = track({ id: "r".repeat(32), start_fragment: before, start_fragment_effective: 0, request_id: id });
  assert.equal(a.voiceMoveAfterReplay(replayed, [replayed], after), 0);
  assert.equal(a.voiceMoveAfterReplay(replayed, [replayed], before), null, "уже там");
  // Двигать нечего: дорожку заменили (её нет в звуке склейки), она не вышла, это музыка, ответа нет.
  assert.equal(a.voiceMoveAfterReplay(replayed, [], after), null);
  assert.equal(a.voiceMoveAfterReplay({ ...replayed, status: "failed" }, [replayed], after), null);
  assert.equal(a.voiceMoveAfterReplay({ ...replayed, kind: "music", start_fragment: null }, [replayed], after), null);
  assert.equal(a.voiceMoveAfterReplay(undefined, [replayed], after), null);
  // Делается — двигаем тоже (PATCH сервера двигает и строку в работе).
  assert.equal(a.voiceMoveAfterReplay({ ...replayed, status: "pending" }, [replayed], 2), 2);
});

test("панель «Звук» при смене склейки: закрыли на время удаления — вернулась как была (MA_FIX5)", () => {
  const X = "a".repeat(32);
  const Y = "b".repeat(32);
  // Обычные переходы — как раньше.
  assert.equal(a.soundStep(X, X, null, null), "same");
  assert.equal(a.soundStep(X, Y, null, null), "reset", "другая склейка");
  assert.equal(a.soundStep(X, null, null, null), "reset", "«Новая склейка»");
  assert.equal(a.soundStep(null, X, null, null), "keep", "первое сохранение новой — та же склейка");
  // Удаление открытой: закрыли на время запроса — отложить.
  assert.equal(a.soundStep(X, null, X, null), "park");
  assert.equal(a.soundStep(null, null, X, X), "same", "пока идёт запрос");
  // Сервер отказал, она снова открыта — вернуть.
  assert.equal(a.soundStep(null, X, null, X), "restore");
  // Удалилась (или начали новую) — отложенное забыть.
  assert.equal(a.soundStep(null, null, null, X), "drop");
  // За время запроса открыли другую — не её состояние.
  assert.equal(a.soundStep(null, Y, null, X), "keep");
  // Позже снова открыли X обычным путём — отложенного уже нет, ничего не всплывает.
  assert.equal(a.soundStep(null, X, null, null), "keep");
});

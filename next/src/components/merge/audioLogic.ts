/**
 * «Склейка»: звук — голос за кадром, музыка, звук роликов (CONTRACT_M.md §10).
 * Чистые функции без React и запросов — их проверяет audioLogic.test.mjs.
 *
 * Цена на кнопке и счётчик символов считаются так же, как на сервере: человек
 * видит ровно то, что спишется. Сервер всё равно сверяет цену (price в
 * запросе) и при расхождении отвечает audio_price_changed.
 */
import { refusalText, waitMinutes, type TextSpec } from "./mergeLogic";
import { MERGE_ERROR_RU } from "./mergeText";
import { fileExtension } from "./uploadLogic";
import type {
  MergeAudioLimits,
  MergeAudioPrices,
  MergeAudioState,
  MergeAudioSummary,
  MergeClipSound,
  MergeTrack,
  MergeTrackKind,
} from "./mergeTypes";

const MB = 1024 * 1024;

/** Цены мультстудии по умолчанию: 20 кр за 1000 символов (не меньше 5), 30 кр за минуту музыки. */
export const DEFAULT_AUDIO_PRICES: MergeAudioPrices = { voice_per_1k: 20, voice_min: 5, music_per_min: 30 };

/** Расширения своего трека — список мультстудии (сервер узнаёт формат ещё и по первым байтам). */
const AUDIO_EXTENSIONS = [
  "mp3", "m4a", "aac", "wav", "ogg", "oga", "opus", "webm", "mp4", "mov", "amr", "awb",
  "3gp", "3gpp", "3ga", "3g2", "flac", "aif", "aiff", "aifc", "caf", "wma", "mka",
];

export const CLIP_SOUNDS: readonly MergeClipSound[] = ["keep", "quiet", "off"];

/** Пределы по умолчанию — те же, что отдаёт сервер (CONTRACT_M.md §10.2): пока ответа нет, экран не пустой. */
export const DEFAULT_AUDIO_LIMITS: MergeAudioLimits = {
  voice_chars: 2000,
  prompt_min_chars: 3,
  prompt_chars: 400,
  music_min_s: 3,
  music_max_s: 300,
  upload_max_bytes: 20 * MB,
  upload_max_mb: 20,
  upload_max_s: 300,
  extensions: AUDIO_EXTENSIONS,
  accept: `audio/*,${AUDIO_EXTENSIONS.map((e) => `.${e}`).join(",")}`,
  music_volume_max: 1,
  voice_volume_max: 2,
  clip_sounds: [...CLIP_SOUNDS],
  clip_volumes: { keep: 1, quiet: 0.3, off: 0 },
  retention_days: 30,
};

export const DEFAULT_MUSIC_VOLUME = 0.35;
export const DEFAULT_VOICE_VOLUME = 1;

export function isClipSound(v: unknown): v is MergeClipSound {
  return typeof v === "string" && (CLIP_SOUNDS as readonly string[]).includes(v);
}

/* ------------------------------------------------------------------ */
/* Текст и цены                                                        */
/* ------------------------------------------------------------------ */

/**
 * Пробелы так, как их видит сервер (str.split() в Python), а не \s: у JS в \s
 * есть U+FEFF, но нет U+001C–U+001F и U+0085. Иначе у границы цены (каждые
 * 50 символов) счётчик и цена расходились бы с сервером на 1 кр, и каждое
 * нажатие получало бы audio_price_changed.
 */
const SPACES = /[\t\n\v\f\r \x1c-\x1f\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/;

/** Текст так, как его сохранит сервер: пробелы, табуляции и переводы строк — один пробел. */
export function cleanText(text: string | null | undefined): string {
  return String(text ?? "")
    .split(SPACES)
    .filter(Boolean)
    .join(" ");
}

/** Символов для счётчика и цены — кодовые точки (как len() у сервера): смайлик — один символ. */
export function textChars(text: string | null | undefined): number {
  return [...cleanText(text)].length;
}

/** Цена голоса за кадром: max(минимум, ⌈символы × цена за 1000 / 1000⌉). */
export function voicePrice(text: string | null | undefined, prices: MergeAudioPrices = DEFAULT_AUDIO_PRICES): number {
  return Math.max(prices.voice_min, Math.ceil((textChars(text) * prices.voice_per_1k) / 1000));
}

/**
 * Длиннее этого голос делается уже не секунды: подсказки ожидания у «Озвучить» и у голоса,
 * который делается, говорят «до минуты» (2000 символов — две-три минуты речи).
 */
export const VOICE_LONG_CHARS = 600;

/** Сколько ждать голос по его тексту: short — обычно несколько секунд, long — может занять до минуты. */
export function voiceWait(text: string | null | undefined): "short" | "long" {
  return textChars(text) > VOICE_LONG_CHARS ? "long" : "short";
}

const positive = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) && v > 0 ? v : 0);

/** Длина склейки так, как её считает сервер: сумма длин фрагментов до тысячных. */
export function mergeTotal(items: readonly { duration_s: number | null }[]): number {
  return Math.round(items.reduce((sum, i) => sum + positive(i.duration_s), 0) * 1000) / 1000;
}

/**
 * Сколько секунд музыки закажет «Создать»: длина склейки, ⌈…⌉, от 3 до 300 с;
 * 0 — фрагментов нет. Округление то же, что у сервера.
 */
export function musicSeconds(
  items: readonly { duration_s: number | null }[],
  limits: Pick<MergeAudioLimits, "music_min_s" | "music_max_s"> = DEFAULT_AUDIO_LIMITS,
): number {
  const total = mergeTotal(items);
  if (!(total > 0)) return 0;
  return Math.min(limits.music_max_s, Math.max(limits.music_min_s, Math.ceil(total - 0.001)));
}

/** Цена музыки: max(1, ⌈секунды × цена минуты / 60⌉); 0 секунд — 0. */
export function musicPrice(seconds: number, prices: MergeAudioPrices = DEFAULT_AUDIO_PRICES): number {
  return seconds > 0 ? Math.max(1, Math.ceil((seconds * prices.music_per_min) / 60)) : 0;
}

/**
 * Цена «Создать» под склейку, какой она сейчас на экране. Фрагменты те же, что
 * у сервера, — его расчёт (и цены, и округления — его), иначе (фрагменты только
 * что поменяли, сохранение ещё не дошло) — по той же формуле.
 */
export function musicQuote(
  state: Pick<MergeAudioState, "music_quote" | "prices" | "limits" | "total_duration_s"> | null,
  items: readonly { duration_s: number | null }[],
): { seconds: number; credits: number } | null {
  if (state && Math.abs(state.total_duration_s - mergeTotal(items)) < 0.0005) return state.music_quote;
  const seconds = musicSeconds(items, state?.limits ?? DEFAULT_AUDIO_LIMITS);
  if (!seconds) return null;
  return { seconds, credits: musicPrice(seconds, state?.prices ?? DEFAULT_AUDIO_PRICES) };
}

/* ------------------------------------------------------------------ */
/* С какого фрагмента голос                                             */
/* ------------------------------------------------------------------ */

/** С какой секунды готового ролика начинается каждый фрагмент. */
export function fragmentStarts(items: readonly { duration_s: number | null }[]): number[] {
  let at = 0;
  return items.map((i) => {
    const start = Math.round(at * 1000) / 1000;
    at += positive(i.duration_s);
    return start;
  });
}

/** Где голос начнётся на самом деле: фрагментов стало меньше — с последнего (как у сервера). */
export function effectiveStart(start: number | null | undefined, count: number): number {
  const wanted = typeof start === "number" && Number.isFinite(start) ? Math.floor(start) : 0;
  if (count <= 0) return 0;
  return Math.max(0, Math.min(wanted, count - 1));
}

/** Правка списка фрагментов, после которой номер голоса мог уехать. */
export type FragmentChange =
  | { kind: "move"; from: number; to: number }
  | { kind: "remove"; index: number }
  | { kind: "insert"; index: number };

/**
 * Голос пишут под конкретный ролик, а сервер хранит номер фрагмента: после
 * перестановки, удаления или вставки перед ним — номер, под которым его ролик
 * стоит теперь. Убрали сам ролик голоса — прежний номер (на нём теперь
 * следующий ролик; был последним — новый последний). count — фрагментов до правки.
 */
export function followStart(start: number | null | undefined, count: number, change: FragmentChange): number {
  const s = effectiveStart(start, count);
  if (count <= 0) return s;
  if (change.kind === "move") {
    if (change.from < 0 || change.from >= count) return s;
    const to = Math.max(0, Math.min(count - 1, change.to));
    if (change.from === s) return to;
    if (change.from < s && to >= s) return s - 1;
    if (change.from > s && to <= s) return s + 1;
    return s;
  }
  if (change.kind === "remove") {
    if (change.index < 0 || change.index >= count) return s;
    return change.index < s ? s - 1 : Math.max(0, Math.min(s, count - 2));
  }
  return change.index <= s ? s + 1 : s;
}

/** Меньше этого обрезку голоса не замечают — и не пугаем. */
const VOICE_CUT_MIN_S = 0.5;

/**
 * Сколько секунд голоса не прозвучит: он длиннее, чем осталось ролика с его
 * фрагмента, а сведение режет звук по концу картинки. 0 — помещается.
 */
export function voiceCutS(
  duration: number | null | undefined,
  start: number | null | undefined,
  items: readonly { duration_s: number | null }[],
): number {
  if (!(typeof duration === "number" && Number.isFinite(duration) && duration > 0) || items.length === 0) return 0;
  const at = fragmentStarts(items)[effectiveStart(start, items.length)];
  const cut = duration - (mergeTotal(items) - at);
  return cut >= VOICE_CUT_MIN_S ? Math.round(cut * 10) / 10 : 0;
}

export type StartOption = { index: number; n: number; at: number; title: string };

/** Пункты «Начать с фрагмента»: номер с единицы, секунда начала и название. */
export function startOptions(items: readonly { title: string; duration_s: number | null }[]): StartOption[] {
  const starts = fragmentStarts(items);
  return items.map((it, index) => ({ index, n: index + 1, at: starts[index], title: it.title.trim() }));
}

/* ------------------------------------------------------------------ */
/* Дорожки                                                             */
/* ------------------------------------------------------------------ */

/** Голос или музыка склейки: та, что сведётся, та, что делается, и последняя неудачная. */
export type TrackSlot = { ready: MergeTrack | null; pending: MergeTrack | null; failed: MergeTrack | null };

export function trackSlot(tracks: readonly MergeTrack[] | null | undefined, kind: MergeTrackKind): TrackSlot {
  const slot: TrackSlot = { ready: null, pending: null, failed: null };
  // Сервер отдаёт старые раньше новых: последний подходящий — самый свежий.
  for (const t of tracks ?? []) {
    if (t.kind !== kind) continue;
    if (t.status === "ready") slot.ready = t;
    else if (t.status === "pending") slot.pending = t;
    else if (t.status === "failed") slot.failed = t;
  }
  return slot;
}

export function hasPending(state: Pick<MergeAudioState, "tracks"> | null | undefined): boolean {
  return Boolean(state?.tracks.some((t) => t.status === "pending"));
}

/** Дорожки, которые делались и уже закончились (готовы или не вышли): было pending — стало иначе. */
export function settledTracks(prev: readonly MergeTrack[], next: readonly MergeTrack[]): MergeTrack[] {
  const out: MergeTrack[] = [];
  for (const old of prev) {
    if (old.status !== "pending") continue;
    const now = next.find((t) => t.id === old.id);
    if (!now) continue;
    if (now.status !== "pending") out.push(now);
  }
  return out;
}

/**
 * Что сейчас со звуком склейки — для «Звук» в доке, подтверждения и итога.
 * music: generated — по описанию, upload — свой трек, unknown — известно лишь,
 * что музыка есть (коротко из ProjectJSON.audio).
 */
export type SoundInfo = {
  voice: boolean;
  music: "generated" | "upload" | "unknown" | null;
  clip: MergeClipSound;
  pending: boolean;
};

export function soundInfo(
  state: Pick<MergeAudioState, "tracks" | "clip_sound"> | null | undefined,
  summary?: MergeAudioSummary | null,
): SoundInfo {
  if (state) {
    const music = trackSlot(state.tracks, "music").ready;
    return {
      voice: Boolean(trackSlot(state.tracks, "voice").ready),
      music: music ? music.source : null,
      clip: isClipSound(state.clip_sound) ? state.clip_sound : "keep",
      pending: hasPending(state),
    };
  }
  if (summary) {
    return {
      voice: Boolean(summary.voice),
      music: summary.music ? "unknown" : null,
      clip: isClipSound(summary.clip_sound) ? summary.clip_sound : "keep",
      pending: Boolean(summary.pending),
    };
  }
  return { voice: false, music: null, clip: "keep", pending: false };
}

/** Звук что-то меняет в ролике: есть дорожка или звук роликов не «как есть». */
export function hasSound(info: SoundInfo): boolean {
  return info.voice || info.music !== null || info.clip !== "keep";
}

/** Части подписи «голос, музыка, ролики тише» — по порядку; тексты — у компонента. */
export type SoundPart = "voice" | "music" | "own" | "quiet" | "off";

export function soundParts(info: SoundInfo): SoundPart[] {
  const parts: SoundPart[] = [];
  if (info.voice) parts.push("voice");
  if (info.music === "upload") parts.push("own");
  else if (info.music) parts.push("music");
  if (info.clip === "quiet") parts.push("quiet");
  if (info.clip === "off") parts.push("off");
  return parts;
}

/**
 * Что из звука уже оплачено — «Склеить» второй раз за это не спишет. Голос
 * всегда платный (копия оплачена в прежней склейке), музыка — если не свой трек.
 */
export function paidSound(info: SoundInfo): "voice" | "music" | "both" | null {
  const music = info.music === "generated";
  if (info.voice && music) return "both";
  if (info.voice) return "voice";
  if (music) return "music";
  return null;
}

/* ------------------------------------------------------------------ */
/* Проверки до запроса                                                 */
/* ------------------------------------------------------------------ */

const spec = (key: string, params: Record<string, string | number> = {}): TextSpec => ({
  key: `merge.err.${key}`,
  ru: MERGE_ERROR_RU[key],
  params,
});

/** Почему «Озвучить» сейчас нельзя — тем же текстом, что ответил бы сервер; null — можно. */
export function voiceRefusal(
  text: string,
  voiceId: string,
  limits: Pick<MergeAudioLimits, "voice_chars"> = DEFAULT_AUDIO_LIMITS,
): TextSpec | null {
  const chars = textChars(text);
  if (!chars) return spec("audio_text_empty");
  if (chars > limits.voice_chars) return spec("voice_too_long", { max: limits.voice_chars });
  if (!voiceId) return spec("audio_voice_id");
  return null;
}

/** Почему «Создать» сейчас нельзя; seconds — длина музыки под склейку (0 — фрагментов нет). */
export function musicRefusal(
  prompt: string,
  seconds: number,
  limits: Pick<MergeAudioLimits, "prompt_min_chars" | "prompt_chars"> = DEFAULT_AUDIO_LIMITS,
): TextSpec | null {
  const chars = textChars(prompt);
  if (chars < limits.prompt_min_chars) return spec("audio_prompt_short");
  if (chars > limits.prompt_chars) return spec("audio_prompt_long", { max: limits.prompt_chars });
  if (!(seconds > 0)) return spec("audio_no_fragments");
  return null;
}

/** Расширение по типу файла, когда в имени его нет (так отдают некоторые галереи и диктофоны). */
const AUDIO_MIME_EXT: Record<string, string> = {
  "audio/mpeg": "mp3",
  "audio/mp3": "mp3",
  "audio/mp4": "m4a",
  "audio/x-m4a": "m4a",
  "audio/aac": "aac",
  "audio/wav": "wav",
  "audio/wave": "wav",
  "audio/x-wav": "wav",
  "audio/ogg": "ogg",
  "audio/opus": "opus",
  "audio/webm": "webm",
  "audio/flac": "flac",
  "audio/x-flac": "flac",
  "audio/aiff": "aiff",
  "audio/x-aiff": "aiff",
  "audio/amr": "amr",
  "audio/3gpp": "3gp",
  "audio/x-ms-wma": "wma",
  "audio/x-matroska": "mka",
  "video/mp4": "mp4",
  "video/quicktime": "mov",
  "video/webm": "webm",
};

/** Имя для сервера: он сначала смотрит на расширение. Нет его и тип незнаком — null. */
export function audioUploadName(
  file: { name: string; type: string },
  limits: Pick<MergeAudioLimits, "extensions"> = DEFAULT_AUDIO_LIMITS,
): string | null {
  const name = file.name || "";
  if (limits.extensions.includes(fileExtension(name))) return name;
  const ext = AUDIO_MIME_EXT[(file.type || "").toLowerCase()];
  if (!ext || !limits.extensions.includes(ext)) return null;
  return `${name || "music"}.${ext}`;
}

export type AudioPrecheck = "audio_too_big" | "audio_bad_type" | "audio_unreadable";

/** Свой трек до загрузки: размер, расширение, пустой файл — в порядке проверок сервера. */
export function precheckAudio(
  file: { name: string; size: number; type: string },
  limits: Pick<MergeAudioLimits, "upload_max_bytes" | "extensions"> = DEFAULT_AUDIO_LIMITS,
): AudioPrecheck | null {
  if (file.size > limits.upload_max_bytes) return "audio_too_big";
  if (audioUploadName(file, limits) == null) return "audio_bad_type";
  if (!(file.size > 0)) return "audio_unreadable";
  return null;
}

/* ------------------------------------------------------------------ */
/* Отказы                                                              */
/* ------------------------------------------------------------------ */

type ErrLike = { code: string; message: string; data: Record<string, unknown> };

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/**
 * Ответ не дошёл (связь, 5xx без нашего кода, пустое тело): запрос мог
 * выполниться — сверяемся с сервером, а повтор шлём с тем же request_id.
 */
export function isTransportError(err: Pick<ErrLike, "code">): boolean {
  return err.code === "network" || err.code === "server_error" || err.code === "bad_response" || err.code === "unknown";
}

/** Сбой провайдера: сервер шлёт его только на заказ, заведённый этим запросом (merge audio._failure). */
const ORDER_FAILED_CODES = new Set(["audio_failed", "audio_unavailable", "audio_overloaded"]);

/**
 * Отказ на сам заказ доказывает, что заказ с этим request_id не вышел, только в одном случае:
 * 502 сервера с кодом сбоя провайдера. Его сервер шлёт, лишь заведя строку с этим ключом, — она
 * уже failed, и повтор тем же id вернул бы ту же неудачу (200). Любой другой отказ этого не
 * доказывает (MA_V6 B1): 429 throttled решается до того, как сервер посмотрел на ключ; music_busy
 * может ответить повтору, обогнавшему сам заказ; 400/402/409 — проверки до заказа, а заказ с этим
 * id мог уже сделаться и списаться. Отказы других запросов (свой трек, ✕) к заказу не относятся.
 */
export function orderFailedHere(err: { code: string; status: number }): boolean {
  return err.status === 502 && ORDER_FAILED_CODES.has(err.code);
}

/**
 * Отказ запроса звука → текст. bad_request различается полем (свои ключи
 * audio_*), числа — из ответа, а нет их — из пределов. Остальное — общий
 * разбор склейки: известный код или русский текст сервера.
 */
export function audioErrorText(
  err: ErrLike,
  limits: Pick<MergeAudioLimits, "voice_chars" | "upload_max_mb"> = DEFAULT_AUDIO_LIMITS,
  opts: { upload?: boolean } = {},
): TextSpec {
  const { code, data, message } = err;
  if (code === "bad_request") {
    const field = typeof data.field === "string" ? data.field : "";
    if (field === "text") return spec("audio_text_empty");
    if (field === "voice_id") return spec("audio_voice_id");
    if (field === "start_fragment") return spec("audio_start_fragment");
    // Одно поле — два отказа: голоса ещё нет или такого фрагмента нет; различает только текст сервера.
    if (field === "voice_start_fragment") return /^Голоса за кадром пока нет/.test(message) ? spec("audio_no_voice") : spec("audio_start_fragment");
    if (field === "prompt") {
      const max = num(data.max);
      return max != null ? spec("audio_prompt_long", { max }) : spec("audio_prompt_short");
    }
    if (field === "file") return spec("audio_file");
    return spec("audio_settings");
  }
  if (code === "voice_too_long") return spec("voice_too_long", { max: num(data.max) ?? limits.voice_chars });
  if (code === "audio_too_big") return spec("audio_too_big", { max: num(data.max_mb) ?? limits.upload_max_mb });
  if (code === "insufficient_balance") return spec("audio_balance");
  if (code === "audio_price_changed" && num(data.credits) == null) {
    return message ? { key: "", ru: message, params: {} } : spec("audio_failed");
  }
  // Своих треков — 20 в час: «подождите немного» было бы неправдой, говорим минуты.
  if (opts.upload && code === "throttled" && waitMinutes(data.wait) != null) return refusalText("upload_throttled", data);
  return refusalText(code, data, message);
}

/** Почему дорожка не сделалась (status failed): известный код — наш текст, иначе — текст сервера. */
export function trackErrorText(track: Pick<MergeTrack, "error_code" | "error">): TextSpec {
  const code = track.error_code || "";
  const ru = code ? MERGE_ERROR_RU[code] : undefined;
  if (ru && !ru.includes("{{")) return spec(code);
  if (track.error) return { key: "", ru: track.error, params: {} };
  return spec("audio_failed");
}

/**
 * После music_busy (места музыки на сайте заняты) «Создать» молчит столько: места
 * освобождаются минутами, а частые нажатия тратят лимит заказов звука (10 в минуту,
 * общий с голосом) — и «Озвучить» отказал бы тоже. Минута — как в тексте отказа
 * сервера («попробуйте через минуту»): плашка и отсчёт под кнопкой говорят одно.
 */
export const MUSIC_BUSY_COOLDOWN_MS = 60_000;

/**
 * До какого момента (мс) «Создать» ждёт после ответа на заказ музыки: music_busy —
 * ещё MUSIC_BUSY_COOLDOWN_MS от now, другой ответ ожидание не меняет.
 */
export function musicCooldownUntil(err: Pick<ErrLike, "code"> | null, now: number, until = 0): number {
  return err?.code === "music_busy" ? Math.max(until, now + MUSIC_BUSY_COOLDOWN_MS) : until;
}

/** Сколько целых секунд ещё ждать; 0 — можно нажимать. */
export function cooldownLeft(until: number, now: number): number {
  return until > now ? Math.ceil((until - now) / 1000) : 0;
}

/**
 * Музыка не сделалась — форма повтора с её описанием: после заказа поле очищено, и
 * человек набирал бы описание заново. Уже набранное не трогаем.
 */
export function retryPrompt(current: string, failed: Pick<MergeTrack, "source" | "prompt"> | null | undefined): string {
  if (cleanText(current) || !failed || failed.source !== "generated" || !cleanText(failed.prompt)) return current;
  return failed.prompt;
}

/**
 * Форма повтора по ответу сервера: mark — какой неудачной музыкой поле уже заполняли (её
 * id). Новая неудачная — её описание в пустое поле; та же — второй раз не заполняем, иначе
 * стёртое руками вернулось бы. Сменили склейку — mark забыт (null), и после возврата форма
 * снова с описанием.
 */
export function prefillStep(
  mark: string | null,
  failed: Pick<MergeTrack, "id" | "source" | "prompt"> | null | undefined,
  current: string,
): { mark: string | null; prompt: string } {
  if (!failed || failed.id === mark) return { mark, prompt: current };
  return { mark: failed.id, prompt: retryPrompt(current, failed) };
}

/* ------------------------------------------------------------------ */
/* Повторы, опрос, громкость                                           */
/* ------------------------------------------------------------------ */

/** Один на нажатие: повтор того же нажатия после обрыва связи не спишет второй раз. */
export function newRequestId(rand: () => number = Math.random): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  let out = "";
  for (let i = 0; i < 32; i++) out += Math.floor(rand() * 16).toString(16);
  return out;
}

export function isRequestId(v: unknown): v is string {
  return typeof v === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(v);
}

/** Последний заказ, ответ на который не дошёл: та же склейка и тот же слепок — тот же request_id. */
export type RetryMark = { project: string; sig: string; id: string };

export function requestIdFor(
  last: RetryMark | null,
  project: string,
  sig: string,
  make: () => string = newRequestId,
): string {
  return retryMarkFor(last, project, sig, make).id;
}

/** Метка нажатия: повтор того же заказа — прежняя метка (тот же id), новый заказ — новый id. */
export function retryMarkFor(
  last: RetryMark | null,
  project: string,
  sig: string,
  make: () => string = newRequestId,
): RetryMark {
  if (last && last.project === project && last.sig === sig) return last;
  return { project, sig, id: make() };
}

/**
 * Ответ на заказ не дошёл — что видно на сервере. requestId — ключ заказа: его дорожка готова —
 * заказ выполнен, делается — ещё идёт, иначе — не дошёл (чужой готовый или делающийся звук —
 * другая вкладка, не он). Без ключа (свой трек) — по готовой дорожке: сменилась — выполнен.
 */
export function afterLostAnswer(
  beforeReadyId: string | null,
  slot: TrackSlot,
  requestId: string | null = null,
): "done" | "pending" | "lost" {
  if (requestId) {
    if (slot.ready?.request_id === requestId) return "done";
    if (slot.pending?.request_id === requestId) return "pending";
    return "lost";
  }
  if (slot.ready && slot.ready.id !== beforeReadyId) return "done";
  if (slot.pending) return "pending";
  return "lost";
}

/**
 * Что сервер знает о заказе, чей request_id бережём (ответ не дошёл): его дорожка — того же
 * вида с тем же request_id (сервер хранит ключ у строки заказа и отдаёт его в дорожке).
 *   drop — не вышел именно он (его дорожка failed): повтор с тем же id сервер отдал бы той же
 *          неудачной (200) — «создаётся» без заказа; следующее нажатие — новый заказ;
 *   done — сделан и списан (его дорожка ready): метка больше не нужна;
 *   keep — всё остальное: делается, его дорожки ещё нет (запрос не дошёл или ещё идёт), на
 *          экране чужая неудачная — прежняя попытка или из другой вкладки, перечитывание не
 *          дошло. Сервер мог сделать и списать этот заказ, а новый id заказал бы звук второй
 *          раз; повтор тем же id сервер отдаст той же дорожкой (200) без второго списания.
 * Метка другой склейки — не здесь; пока заказ в пути (inFlight), его id не трогаем.
 */
export type RetryVerdict = "keep" | "drop" | "done";

export function retryVerdict(
  mark: RetryMark | null,
  project: string,
  tracks: readonly Pick<MergeTrack, "kind" | "status" | "request_id">[] | null | undefined,
  kind: MergeTrackKind,
  inFlight: boolean,
): RetryVerdict {
  if (!mark || mark.project !== project || inFlight) return "keep";
  const own = (tracks ?? []).find((t) => t.kind === kind && t.request_id === mark.id);
  if (own?.status === "failed") return "drop";
  if (own?.status === "ready") return "done";
  return "keep";
}

/**
 * Описание неудачной музыки можно подставить в пустую форму повтора, только если подстановка не
 * сменит id заказа, чей request_id бережём (held): с ним нажатие уйдёт тем же слепком. Иначе
 * форма предложила бы другой заказ с новым id, а тот мог сделаться и списаться.
 */
export function prefillKeepsRetry(
  held: RetryMark | null,
  project: string,
  failed: Pick<MergeTrack, "prompt">,
  seconds: number,
): boolean {
  return !held || held.project !== project || musicSignature(failed.prompt, seconds) === held.sig;
}

/**
 * Ответ на заказ голоса — его дорожка (повтор того же нажатия или он сделан, хотя ответ не дошёл),
 * а начало у неё прежнее: с тех пор фрагменты переставили, убрали или выбрали другое начало. Куда
 * её подвинуть (PATCH voice_start_fragment — бесплатно) или null. Дорожки уже нет среди звука
 * склейки (её заменили) или она не вышла — двигать нечего.
 */
export function voiceMoveAfterReplay(
  track: Pick<MergeTrack, "id" | "kind" | "status" | "start_fragment"> | null | undefined,
  tracks: readonly Pick<MergeTrack, "id">[],
  start: number,
): number | null {
  if (!track || track.kind !== "voice" || track.status === "failed") return null;
  if (!tracks.some((t) => t.id === track.id)) return null;
  return track.start_fragment === start ? null : start;
}

/**
 * Ответ на заказ — прежняя неудачная попытка (тот же request_id, 200): нового заказа не было,
 * и «готово»/«создаётся» было бы неправдой — это отказ с её текстом.
 */
export function replayedFailure(track: Pick<MergeTrack, "status"> | null | undefined): boolean {
  return track?.status === "failed";
}

/**
 * Панель «Звук» и её черновики при смене открытой склейки. owner — чья склейка была на
 * экране, openId — чья теперь, parked — склейка, закрытая только на время её удаления,
 * kept — чьё состояние отложено.
 *   park    — закрыли на время удаления: состояние откладываем, пустой редактор — без него;
 *   restore — сервер отказал, та же склейка снова открыта: отложенное — обратно;
 *   reset   — другая склейка: прежнее не нужно;
 *   keep    — из «новой» в только что заведённую (первое сохранение) — та же склейка;
 *   drop    — удаление кончилось без возврата: отложенное больше не нужно;
 *   same    — ничего не поменялось.
 */
export type SoundStep = "same" | "park" | "restore" | "reset" | "keep" | "drop";

export function soundStep(owner: string | null, openId: string | null, parked: string | null, kept: string | null): SoundStep {
  if (owner === openId) return kept !== null && openId === null && parked !== kept ? "drop" : "same";
  if (openId === null && owner !== null && parked === owner) return "park";
  if (owner === null && openId !== null && kept === openId) return "restore";
  return owner === null ? "keep" : "reset";
}

/** Значения, которые человек двигал, пока правка шла на сервер. */
export type LocalSound = { clip?: MergeClipSound; music?: number; voice?: number; start?: number };

/**
 * Правка ушла и вернулась (или отказ): своё значение снимаем — дальше верно то,
 * что прислал сервер. Если человек успел поменять его ещё раз, остаётся новое.
 */
export function settleLocal(
  local: LocalSound,
  sent: { clip_sound?: MergeClipSound; music_volume?: number; voice_volume?: number; voice_start_fragment?: number },
): LocalSound {
  return {
    ...local,
    clip: sent.clip_sound !== undefined && local.clip === sent.clip_sound ? undefined : local.clip,
    music: sent.music_volume !== undefined && local.music === sent.music_volume ? undefined : local.music,
    voice: sent.voice_volume !== undefined && local.voice === sent.voice_volume ? undefined : local.voice,
    start: sent.voice_start_fragment !== undefined && local.start === sent.voice_start_fragment ? undefined : local.start,
  };
}

/** Таймеры очереди: в браузере window.setTimeout, в тестах свои. */
export type QueueTimers = { set: (fn: () => void, ms: number) => unknown; clear: (handle: unknown) => void };

export type SettingsQueue<B> = {
  /** Правка — в очередь сейчас. */
  send: (body: B) => void;
  /**
   * Правка — когда палец остановился: следующая в том же слоте заменяет её.
   * body() зовётся в момент отправки (null — отправлять уже нечего).
   */
  later: (slot: string, body: () => B | null, ms: number) => void;
  /**
   * Перед «Склеить»: отложенное уходит сразу, ждём всю очередь. false — сервер
   * не принял правку, которая была в пути: на экране было не то, что сведётся.
   */
  flush: () => Promise<boolean>;
  /** Отложенное — забыть (ушли со страницы). */
  cancel: () => void;
};

/**
 * Очередь правок звука (PATCH audio/): по одной и по порядку — ответ на старую
 * не затирает новую. run — отправка; true — сервер принял.
 */
export function settingsQueue<B>(run: (body: B) => Promise<boolean>, timers: QueueTimers): SettingsQueue<B> {
  let chain: Promise<void> = Promise.resolve();
  let refused = 0;
  const waiting = new Map<string, { handle: unknown; body: () => B | null }>();
  const send = (body: B) => {
    const step = async () => {
      let ok = false;
      try {
        ok = await run(body);
      } catch {
        ok = false;
      }
      if (!ok) refused += 1;
    };
    chain = chain.then(step, step);
  };
  const fire = (slot: string) => {
    const w = waiting.get(slot);
    if (!w) return;
    waiting.delete(slot);
    timers.clear(w.handle);
    const body = w.body();
    if (body !== null) send(body);
  };
  return {
    send,
    later: (slot, body, ms) => {
      const w = waiting.get(slot);
      if (w) timers.clear(w.handle);
      waiting.set(slot, { body, handle: timers.set(() => fire(slot), ms) });
    },
    flush: async () => {
      const before = refused;
      for (const slot of [...waiting.keys()]) fire(slot);
      await chain;
      return refused === before;
    },
    cancel: () => {
      for (const w of waiting.values()) timers.clear(w.handle);
      waiting.clear();
    },
  };
}

/**
 * Слепок заказа голоса: тот же — значит, это повтор того же нажатия. Без номера фрагмента
 * (MA_V6 B2): фрагменты переставили или убрали — номер голоса поехал за его роликом, а заказ тот
 * же; новый id заказал бы и списал тот же текст второй раз. Начало голоса меняется бесплатно —
 * после повтора хук двигает его PATCH-ем (voice_start_fragment).
 */
export function voiceSignature(text: string, voiceId: string): string {
  return `${voiceId}|${cleanText(text)}`;
}

export function musicSignature(prompt: string, seconds: number): string {
  return `${seconds}|${cleanText(prompt)}`;
}

/** Опрос, пока музыка делается: 3 с, после двух минут — 10 с (минута музыки делается около минуты). */
export const AUDIO_POLL_MS = 3_000;
export const AUDIO_POLL_SLOW_MS = 10_000;
export const AUDIO_POLL_SLOW_AFTER_MS = 120_000;

export function audioPollDelay(elapsedMs: number): number {
  return elapsedMs > AUDIO_POLL_SLOW_AFTER_MS ? AUDIO_POLL_SLOW_MS : AUDIO_POLL_MS;
}

/** Громкость в пределах; не число — значение по умолчанию. */
export function clampVolume(v: unknown, max: number, fallback: number): number {
  const n = typeof v === "number" && Number.isFinite(v) ? v : fallback;
  return Math.round(Math.max(0, Math.min(max, n)) * 100) / 100;
}

export function volumePercent(v: number): number {
  return Math.round((Number.isFinite(v) ? v : 0) * 100);
}

/* ------------------------------------------------------------------ */
/* Голоса (общий список мультстудии)                                   */
/* ------------------------------------------------------------------ */

/** «Bella - Professional, Bright, Warm» → «Bella». */
export function voiceShortName(v: { name: string }): string {
  return (v.name || "").split(" - ")[0].trim() || v.name || "";
}

/** Ключ готового описания голоса мультстудии: studio_ui.voice_n_<имя>. */
export function voiceNameKey(v: { name: string }): string {
  return voiceShortName(v).toLowerCase().replace(/[^a-z]+/g, "");
}

/** Слова характера голоса из названия («Professional, Bright») или описания — для перевода по словарю мультстудии. */
export function voiceTailWords(v: { name: string; description: string }): string[] {
  const tail = (v.name || "").split(" - ")[1] || v.description || "";
  return tail
    .split(/,| and /)
    .map((w) => w.trim())
    .filter(Boolean);
}

/** Ключ слова в словаре мультстудии: studio_ui.voice_w_<слово>. */
export function voiceWordKey(word: string): string {
  return word.toLowerCase().replace(/[^a-z_]+/g, "_");
}

/** Какой голос выбрать: тот, что уже выбран, запомненный или первый в списке. */
export function pickVoice(list: readonly { id: string }[], ...wanted: (string | null | undefined)[]): string {
  for (const id of wanted) if (id && list.some((v) => v.id === id)) return id;
  return list[0]?.id ?? "";
}

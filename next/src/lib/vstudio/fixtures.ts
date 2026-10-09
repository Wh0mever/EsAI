/**
 * Видеостудия: фикстуры и мок-сервер /api/vstudio/.
 *
 * Зачем: фронт (FE-1…FE-5) пишется параллельно с бэкендом. В режиме фикстур
 * (см. fixturesEnabled в api.ts) все вызовы api.ts уходят сюда, и студию можно
 * пройти целиком: модели и цены, загрузка фото с прогрессом, @-референсы,
 * quote с ошибками и предупреждениями компилятора, запуск со всеми статусами
 * дубля, пэйволл, лимит открытых генераций, «Сжать с ИИ», библиотека, история.
 *
 * Правила мок-сервера повторяют §4–§8 спецификации упрощённо: это не второй
 * компилятор, а тренажёр для интерфейса. Цена считается как на сервере
 * (таблица модели + фото-референсы), деньги — резерв при запуске, списание
 * только за готовый результат.
 *
 * Сценарии по тексту промпта: «#fail» — дубль упадёт (с фото из загрузок у
 * Seedance — image_real_person с подсветкой фото), «#lost» — «не удалось
 * подтвердить запуск», «#lost_save» — «ролик снят, но не сохранён»,
 * «#condense_fail» — «Сжать с ИИ» не справится.
 *
 * Настройки мока в браузере: localStorage["vstudio:fixtures:opts"] =
 * '{"guest":false,"staff":true,"mode":"on","balance":1200,"latencyMs":250}'.
 */
import { ERROR_RU, TAKE_ERROR_RU, WARNING_RU, fillRu, issueRu, type RawResponse } from "./errors";
import { linkDocTags } from "./promptDoc";
import { OPEN_TAKE_STATUSES } from "./types";
import type {
  ActiveTake,
  AssetJSON,
  AssetSource,
  BalanceJSON,
  CompilerIssue,
  CondenseBody,
  DroppedInput,
  EffectiveParams,
  IssueFix,
  ModelJSON,
  ModelsResponse,
  PriceLine,
  PriceTable,
  ProjectJSON,
  ProjectSettings,
  PromptDoc,
  PromptNode,
  QuoteBody,
  QuoteJSON,
  RunShotBody,
  RunShotResponse,
  ShotInputBody,
  ShotInputJSON,
  ShotJSON,
  ShotOrigin,
  ShotParams,
  TakeJSON,
  TakeLite,
  TakeMode,
  TakeStatus,
  Uid,
  UploadPhase,
  VsKind,
  VsMode,
} from "./types";

/* ------------------------------------------------------------------ */
/* Идентификаторы и картинки-заглушки                                  */
/* ------------------------------------------------------------------ */

/** Детерминированный uid фикстуры: первая буква — «семейство» (a…f), дальше счётчик. */
export function fixtureUid(family: "a" | "b" | "c" | "d" | "e" | "f", n: number): Uid {
  return family + n.toString(16).padStart(31, "0");
}

const escapeXml = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/** Цветная SVG-заглушка как data-URL: без сети и без файлов в public/. */
export function placeholderImage(label: string, hue: number, width = 1024, height = 1024): string {
  const fs = Math.max(12, Math.round(Math.min(width, height) / 10));
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">` +
    `<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">` +
    `<stop offset="0" stop-color="hsl(${hue % 360},70%,58%)"/>` +
    `<stop offset="1" stop-color="hsl(${(hue + 60) % 360},65%,28%)"/></linearGradient></defs>` +
    `<rect width="100%" height="100%" fill="url(#g)"/>` +
    `<text x="50%" y="50%" fill="#fff" font-family="sans-serif" font-size="${fs}" ` +
    `text-anchor="middle" dominant-baseline="middle">${escapeXml(label)}</text></svg>`;
  return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
}

/** Настоящий ролик из public/ — чтобы плеер в ленте реально играл. */
export const FIXTURE_VIDEO_URL = "/video/wirtebot-video.mp4";

/* ------------------------------------------------------------------ */
/* Модели и цены                                                       */
/* ------------------------------------------------------------------ */

const RES_MUL: Record<string, number> = { "480p": 0.45, "720p": 1, "1080p": 2.5 };

function priceTable(rate720: number, durations: number[], resolutions: string[]): PriceTable {
  const out: PriceTable = {};
  for (const r of resolutions) {
    out[r] = {};
    for (const d of durations) out[r][String(d)] = Math.max(1, Math.round(rate720 * (RES_MUL[r] ?? 1) * d));
  }
  return out;
}

const minPrice = (t: PriceTable) => Math.min(...Object.values(t).flatMap((row) => Object.values(row)));

const SEEDANCE_DURATIONS = [4, 5, 6, 8, 10, 12, 15];
const SEEDANCE_ASPECTS = ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"];
const IMAGE_ASPECTS = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "4:5"];

function seedance(id: string, name: string, rate: number, resolutions: string[], eta: number): ModelJSON {
  const table = priceTable(rate, SEEDANCE_DURATIONS, resolutions);
  return {
    id,
    name,
    badge: "Фото-референсы до 9",
    locked: false,
    eta_s: eta,
    price_from: minPrice(table),
    caps: {
      durations: SEEDANCE_DURATIONS,
      resolutions,
      aspect_ratios: SEEDANCE_ASPECTS,
      audio: true,
      seed: true,
      negative: false,
      frames: ["first_frame", "last_frame"],
      refs: { image: 9 },
      frames_with_refs: "soft_pin",
      ref_forces_duration: null,
      prompt: { soft_words: 150, hard_chars: 6000, lang: "en" },
      rejects_real_faces: true,
      min_ref_px: 300,
    },
    defaults: { duration: 5, resolution: "720p", aspect_ratio: "16:9" },
    // 21:9 у Seedance дороже на треть: больше пикселей в кадре.
    price: { table, by_aspect: { "21:9": priceTable(rate * 1.33, SEEDANCE_DURATIONS, resolutions) } },
  };
}

function buildModels(): { video: ModelJSON[]; image: ModelJSON[] } {
  const veoTable = priceTable(12, [4, 6, 8], ["720p", "1080p"]);
  const klingTable = priceTable(10, [5, 10, 15], ["720p"]);
  const imageCaps = (refs: number): ModelJSON["caps"] => ({
    durations: [],
    resolutions: [],
    aspect_ratios: IMAGE_ASPECTS,
    audio: false,
    seed: false,
    negative: false,
    frames: [],
    refs: { image: refs },
    frames_with_refs: "none",
    ref_forces_duration: null,
    prompt: { soft_words: null, hard_chars: 8000, lang: "any" },
    rejects_real_faces: false,
    min_ref_px: 0,
  });
  return {
    video: [
      seedance("bytedance/seedance-2.0", "Seedance 2.0", 15, ["480p", "720p", "1080p"], 150),
      seedance("bytedance/seedance-2.0-fast", "Seedance 2.0 Fast", 9, ["480p", "720p"], 90),
      {
        id: "google/veo-3.1-fast",
        name: "Veo 3.1 Fast",
        badge: "Кадры, звук",
        locked: false,
        eta_s: 90,
        price_from: minPrice(veoTable),
        caps: {
          durations: [4, 6, 8],
          resolutions: ["720p", "1080p"],
          aspect_ratios: ["16:9", "9:16"],
          audio: true,
          seed: true,
          negative: true,
          frames: ["first_frame", "last_frame"],
          // Референсы Veo через OpenRouter не проверены живой пробой — выключены.
          refs: { image: 0 },
          frames_with_refs: "block",
          ref_forces_duration: 8,
          prompt: { soft_words: 120, hard_chars: 2500, lang: "en" },
          rejects_real_faces: false,
          min_ref_px: 0,
        },
        defaults: { duration: 8, resolution: "720p", aspect_ratio: "16:9" },
        price: { table: veoTable },
      },
      {
        id: "kwaivgi/kling-v3.0-std",
        name: "Kling v3 Standard",
        badge: "Кадры",
        // Премиум: у бесплатного тарифа запуск ведёт в пэйволл.
        locked: true,
        eta_s: 180,
        price_from: minPrice(klingTable),
        caps: {
          durations: [5, 10, 15],
          resolutions: ["720p"],
          aspect_ratios: ["16:9", "9:16", "1:1"],
          audio: true,
          seed: false,
          negative: true,
          frames: ["first_frame", "last_frame"],
          refs: { image: 0 },
          frames_with_refs: "none",
          ref_forces_duration: null,
          prompt: { soft_words: 150, hard_chars: 2500, lang: "any" },
          rejects_real_faces: false,
          min_ref_px: 0,
        },
        defaults: { duration: 5, resolution: "720p", aspect_ratio: "16:9" },
        price: { table: klingTable },
      },
    ],
    image: [
      {
        id: "google/gemini-2.5-flash-image",
        name: "Nano Banana",
        badge: "До 3 фото",
        locked: false,
        eta_s: 20,
        price_from: 6,
        caps: imageCaps(3),
        defaults: { aspect_ratio: "1:1" },
        per_image: 6,
      },
      {
        id: "black-forest-labs/flux.2-flex",
        name: "FLUX.2 Flex",
        badge: "До 8 фото",
        locked: false,
        eta_s: 30,
        price_from: 12,
        caps: imageCaps(8),
        defaults: { aspect_ratio: "1:1" },
        per_image: 12,
      },
    ],
  };
}

/** GET models/ для вошедшего при VSTUDIO_MODE=on. */
export const FIXTURE_MODELS: ModelsResponse = { mode: "on", available: true, ...buildModels() };

/** Цена одного отправляемого фото (кадра или референса) — у видео. */
const PER_REF_CREDITS = 7;

/* ------------------------------------------------------------------ */
/* Тексты и мелкие помощники                                           */
/* ------------------------------------------------------------------ */

function issue(
  code: string,
  params: Record<string, unknown>,
  which: "errors" | "warnings",
  fix?: IssueFix | null,
  fixes?: IssueFix[],
): CompilerIssue {
  const out: CompilerIssue = { code, params, message: issueRu(code, params, which), fix: fix ?? null };
  if (fixes) out.fixes = fixes;
  return out;
}

function errorBody(code: string, extra: Record<string, unknown> = {}): Record<string, unknown> {
  return { error: fillRu(ERROR_RU[code] || ERROR_RU.unknown, extra), error_code: code, ...extra };
}

const words = (s: string) => (s.match(/\S+/g) || []).length;

function docFromText(text: string): PromptDoc {
  const blocks = text.split("\n").map((line): PromptNode[] => (line ? [{ t: "text", v: line }] : []));
  return { v: 1, blocks: blocks.length ? blocks : [[]] };
}

function plainText(doc: PromptDoc): string {
  return doc.blocks.map((b) => b.map((n) => (n.t === "text" ? n.v : "")).join("")).join("\n");
}

function refUids(doc: PromptDoc): Uid[] {
  return doc.blocks.flatMap((b) => b.flatMap((n) => (n.t === "ref" ? [n.asset] : [])));
}

/** Как считает счётчик под полем: ссылка — одно слово «@Image N». */
function docStats(doc: PromptDoc): { chars: number; words: number } {
  const s = doc.blocks.map((b) => b.map((n) => (n.t === "text" ? n.v : "@Image 1")).join("")).join("\n");
  return { chars: s.length, words: words(s) };
}

const SCRIPT_SIGNS = [
  /(^|\n)\s*(сцена|scene|кадр)\s*\d/i,
  /\d{1,2}:\d{2}/,
  /(^|\n)\s*\d+[.)]\s/,
  /(^|[\s,.;:!?])(затем|потом|после этого|then)(?=[\s,.;:!?]|$)/i,
];

function cyrillicShare(s: string): number {
  const letters = s.match(/[A-Za-zА-Яа-яЁё]/g) || [];
  if (!letters.length) return 0;
  return (s.match(/[А-Яа-яЁё]/g) || []).length / letters.length;
}

/* ------------------------------------------------------------------ */
/* Компилятор фикстур: quote/ и тело запроса                           */
/* ------------------------------------------------------------------ */

export type FixtureAssetLookup = (uid: Uid) => (AssetJSON & { deleted?: boolean }) | undefined;

export type FixtureCompiled = {
  quote: QuoteJSON;
  /** Тело submit без ключей — «Что ушло модели». */
  body: Record<string, unknown>;
  /** Сколько фото уйдёт модели (оплачиваются). */
  billable: number;
};

function modelById(models: { video: ModelJSON[]; image: ModelJSON[] }, kind: VsKind, id: string): ModelJSON | undefined {
  return models[kind].find((m) => m.id === id);
}

function mentionFor(model: ModelJSON, n: number, role: string): string {
  if (!model.caps.durations.length) return `image ${n}`;
  if (model.id.includes("veo")) return role ? `${role} (reference image ${n})` : `the subject of reference image ${n}`;
  return `Image ${n}`;
}

function headerFor(model: ModelJSON, n: number, role: string): string {
  if (!model.caps.durations.length) return `Image ${n}: ${role}.`;
  if (model.id.includes("veo")) return "";
  return `Image ${n} is ${role}.`;
}

export function fixtureCompile(
  models: { video: ModelJSON[]; image: ModelJSON[] },
  body: QuoteBody,
  lookup: FixtureAssetLookup,
  balance: { balance: number; reserved: number } | null,
  opts: { allowDeleted?: boolean } = {},
): FixtureCompiled {
  const errors: CompilerIssue[] = [];
  const warnings: CompilerIssue[] = [];
  // Как сервер (compiler → prompt_doc.link_tags): теги, оставшиеся текстом,
  // привязываются к фото по номеру; без фото — tag_unknown, «@Видео N» — ошибка.
  const linked = linkDocTags(body.prompt_doc ?? docFromText(body.prompt_text ?? ""), body.inputs || []);
  const doc: PromptDoc = linked.doc;
  const model = modelById(models, body.kind, body.model);

  const emptyMeter = { chars: 0, words: 0, soft_words: null, hard_chars: 20000, level: "ok" as const };
  if (!model) {
    errors.push(issue("model_unavailable", {}, "errors", null));
    return {
      quote: {
        credits: null,
        breakdown: [],
        balance: balance && { ...balance, available: Math.max(0, balance.balance - balance.reserved), after: null },
        mode: null,
        effective: {},
        labels: {},
        serialized_prompt: "",
        errors,
        warnings,
        meter: emptyMeter,
        dropped: [],
        eta_s: 0,
      },
      body: {},
      billable: 0,
    };
  }

  const caps = model.caps;
  const mname = model.name;
  const isVideo = body.kind === "video";
  const inputs = [...(body.inputs || [])];
  errors.push(...linked.errors);
  warnings.push(...linked.warnings);
  if (inputs.length > 16) errors.push(issue("too_many_inputs", { max: 16 }, "errors"));

  const refsAll = inputs.filter((i) => i.slot === "reference").sort((a, b) => a.position - b.position);
  const refsIn = refsAll.filter((i) => i.included);
  const firstIn = isVideo ? inputs.find((i) => i.slot === "first_frame" && i.included) : undefined;
  const lastIn = isVideo ? inputs.find((i) => i.slot === "last_frame" && i.included) : undefined;
  const dropped: DroppedInput[] = inputs
    .filter((i) => !i.included)
    .map((i) => ({ asset: i.asset, slot: i.slot, reason: "excluded_by_user" }));

  // Номера — позиции среди включённых референсов, с единицы (§4.2).
  const labels: Record<Uid, string> = {};
  const numberOf = new Map<Uid, number>();
  refsIn.forEach((inp, idx) => {
    labels[inp.asset] = `Image ${idx + 1}`;
    numberOf.set(inp.asset, idx + 1);
  });
  if (firstIn) labels[firstIn.asset] = "first_frame";
  if (lastIn) labels[lastIn.asset] = "last_frame";

  // Параметры входа — как у бэкенда: {asset, slot, n}; n только у включённого референса.
  const at = (inp: ShotInputBody) => ({ asset: inp.asset, slot: inp.slot, n: numberOf.get(inp.asset) ?? null });
  for (const inp of inputs.filter((i) => !i.included)) {
    warnings.push(issue("input_excluded", at(inp), "warnings"));
  }

  // Материалы: есть ли, готовы ли, подходят ли.
  for (const inp of inputs.filter((i) => i.included)) {
    const a = lookup(inp.asset);
    const drop: IssueFix = { action: "exclude_inputs", assets: [inp.asset] };
    if (!a || (a.deleted && !opts.allowDeleted)) errors.push(issue("asset_not_found", at(inp), "errors", drop));
    else if (a.kind !== "image") errors.push(issue("video_refs_unsupported", {}, "errors"));
    else if (a.status === "pending") errors.push(issue("asset_not_ready", at(inp), "errors"));
    else if (a.status === "failed") errors.push(issue("asset_failed", at(inp), "errors", drop));
    else if (caps.min_ref_px && a.width && a.height && Math.min(a.width, a.height) < caps.min_ref_px) {
      errors.push(issue("ref_too_small", { ...at(inp), model: mname, min: caps.min_ref_px }, "errors", drop));
    }
  }

  // Упоминания: ссылка на то, чего нет во входах, — красный чип.
  const inputUids = new Set(inputs.map((i) => i.asset));
  const mentioned = refUids(doc);
  // По записи на каждый чужой чип: params.asset — какой чип красить красным.
  for (const uid of new Set(mentioned.filter((u) => !inputUids.has(u)))) {
    errors.push(issue("mention_not_attached", { asset: uid }, "errors"));
  }
  for (const inp of refsIn) {
    if (!mentioned.includes(inp.asset)) warnings.push(issue("ref_unmentioned", at(inp), "warnings"));
  }

  // Режим.
  let mode: TakeMode | null;
  let pinK = 0;
  if (isVideo) {
    if (firstIn && !caps.frames.includes("first_frame")) errors.push(issue("frames_not_supported", { model: mname }, "errors"));
    if (lastIn && !caps.frames.includes("last_frame")) {
      errors.push(issue("last_frame_not_supported", { model: mname }, "errors"));
    }
    if (refsIn.length) {
      if (caps.refs.image <= 0) {
        const canFrame = caps.frames.includes("first_frame") && !firstIn;
        errors.push(
          issue(
            "refs_not_supported",
            { model: mname },
            "errors",
            canFrame ? { action: "move_to_first_frame", asset: refsIn[0].asset } : { action: "pick_model", model: "bytedance/seedance-2.0" },
          ),
        );
      } else if (refsIn.length > caps.refs.image) {
        errors.push(
          issue("too_many_refs", { max: caps.refs.image, n: refsIn.length, model: mname }, "errors", {
            action: "exclude_inputs",
            assets: refsIn.slice(caps.refs.image).map((i) => i.asset),
          }),
        );
      }
    }
    if ((firstIn || lastIn) && refsIn.length) {
      if (caps.frames_with_refs === "soft_pin") {
        if (lastIn) errors.push(issue("last_frame_with_refs", { model: mname }, "errors"));
        pinK = refsIn.length + 1;
        warnings.push(issue("frame_soft_pin", { k: pinK }, "warnings"));
        mode = "r2v_pin";
      } else {
        // Как у бэкенда: fix — основной вариант, fixes — оба; assets — что выключить.
        const choices: IssueFix[] = [
          { action: "use_frames_only", assets: refsIn.map((i) => i.asset) },
          { action: "use_refs_only", assets: [firstIn, lastIn].flatMap((i) => (i ? [i.asset] : [])) },
        ];
        errors.push(issue("frames_refs_conflict", { model: mname }, "errors", choices[0], choices));
        mode = null;
      }
    } else if (refsIn.length) mode = "r2v";
    else if (firstIn && lastIn) mode = "flf2v";
    else if (firstIn || lastIn) mode = lastIn ? "flf2v" : "i2v";
    else mode = "t2v";
  } else {
    if (refsIn.length > caps.refs.image) {
      errors.push(
        issue("too_many_refs", { max: caps.refs.image, n: refsIn.length, model: mname }, "errors", {
          action: "exclude_inputs",
          assets: refsIn.slice(caps.refs.image).map((i) => i.asset),
        }),
      );
    }
    mode = refsIn.length ? "i2i" : "t2i";
  }

  // Параметры: только из списков модели, молча не подгоняем.
  const p: ShotParams = { ...model.defaults, ...(body.params || {}) };
  const effective: EffectiveParams = {};
  let priceable = true;
  const badParam = (field: keyof ShotParams, value: unknown, allowed: unknown[]) => {
    priceable = false;
    errors.push(
      issue("invalid_param", { model: mname, field, value: String(value), allowed }, "errors", {
        action: "set_param",
        field,
        value: (allowed[0] as string | number | undefined) ?? null,
      }),
    );
  };
  if (isVideo) {
    let duration = Number(p.duration);
    if (!caps.durations.includes(duration)) badParam("duration", p.duration, caps.durations);
    if (refsIn.length && caps.ref_forces_duration && duration !== caps.ref_forces_duration) {
      duration = caps.ref_forces_duration;
      warnings.push(issue("duration_forced", { model: mname, value: duration }, "warnings"));
    }
    const resolution = String(p.resolution || "");
    if (!caps.resolutions.includes(resolution)) badParam("resolution", p.resolution, caps.resolutions);
    effective.duration = duration;
    effective.resolution = resolution;
    if (caps.audio) effective.generate_audio = p.generate_audio !== false;
  }
  const aspect = p.aspect_ratio || "auto";
  if (aspect !== "auto") {
    if (!caps.aspect_ratios.includes(aspect)) badParam("aspect_ratio", aspect, caps.aspect_ratios);
    effective.aspect_ratio = aspect;
  }

  // Сериализация под модель.
  const roleOf = new Map(inputs.map((i) => [i.asset, (i.role || "").trim()]));
  const headers = refsIn
    .filter((i) => roleOf.get(i.asset))
    .map((i) => headerFor(model, numberOf.get(i.asset) || 0, roleOf.get(i.asset) || ""))
    .filter(Boolean);
  const text = doc.blocks
    .map((b) =>
      b
        .map((n) => {
          if (n.t === "text") return n.v;
          if (firstIn && n.asset === firstIn.asset) return pinK ? `Image ${pinK}` : "the first frame";
          if (lastIn && n.asset === lastIn.asset) return "the last frame";
          const num = numberOf.get(n.asset);
          return num ? mentionFor(model, num, roleOf.get(n.asset) || "") : "";
        })
        .join(""),
    )
    .join("\n");
  const pinLine = pinK ? `Image ${pinK} is the first frame of the video.` : "";
  const serialized = [pinLine, ...headers, text].filter(Boolean).join("\n");

  // Длина: обрезки нет нигде.
  const plain = plainText(doc);
  if (!plain.trim() && !mentioned.length) errors.push(issue("prompt_empty", {}, "errors"));
  const chars = serialized.length;
  const wc = words(serialized);
  const soft = caps.prompt.soft_words;
  const hard = caps.prompt.hard_chars;
  const level = chars > hard ? "hard" : soft && wc > soft ? "soft" : "ok";
  if (level === "hard") {
    errors.push(issue("prompt_too_long", { model: mname, chars, hard }, "errors", { action: "condense" }));
  } else if (level === "soft") {
    warnings.push(issue("prompt_long", { model: mname, soft, words: wc }, "warnings", { action: "condense" }));
  }
  if (chars > 1500 && SCRIPT_SIGNS.filter((re) => re.test(plain)).length >= 2) {
    warnings.push(issue("looks_like_script", {}, "warnings"));
  }
  if (caps.prompt.lang === "en" && cyrillicShare(plain) > 0.3) warnings.push(issue("lang_hint", { model: mname }, "warnings"));
  const inText = plain.match(/\b(21:9|16:9|9:16|4:3|3:4|1:1)\b/);
  if (inText && inText[1] !== aspect && caps.aspect_ratios.includes(inText[1])) {
    warnings.push(
      issue("aspect_in_text", { value: inText[1], current: aspect }, "warnings", {
        action: "set_param",
        field: "aspect_ratio",
        value: inText[1],
      }),
    );
  }
  if (caps.rejects_real_faces) {
    const sent = [...refsIn, ...(firstIn ? [firstIn] : []), ...(lastIn ? [lastIn] : [])];
    if (sent.some((i) => lookup(i.asset)?.source === "upload")) {
      warnings.push(issue("faces_risk", { model: mname }, "warnings"));
    }
  }

  // Цена: тариф модели + отправляемые фото. Выключенное не оплачивается.
  const billable = isVideo ? refsIn.length + (firstIn ? 1 : 0) + (lastIn && !pinK ? 1 : 0) : refsIn.length;
  const breakdown: PriceLine[] = [];
  let credits: number | null = null;
  if (priceable) {
    if (isVideo && model.price) {
      const res = effective.resolution || "";
      const ar = effective.aspect_ratio || model.defaults.aspect_ratio || "16:9";
      const table = model.price.by_aspect?.[ar] || model.price.table;
      const base = Number(table[res]?.[String(effective.duration)] || 0);
      breakdown.push({ key: "price.video", params: { s: effective.duration || 0, res, ar }, credits: base });
      const refs = billable * PER_REF_CREDITS;
      if (refs > 0) breakdown.push({ key: "price.refs", params: { n: billable }, credits: refs });
      credits = base + refs;
    } else {
      credits = model.per_image || 1;
      breakdown.push({ key: "price.image", params: { n: 1 }, credits });
    }
  }

  let bal: BalanceJSON | null = null;
  if (balance) {
    const available = Math.max(0, balance.balance - balance.reserved);
    bal = { ...balance, available, after: credits == null ? null : available - credits };
  }

  // Тело запроса: кадры и референсы никогда не уходят вместе.
  const url = (uid: Uid) => lookup(uid)?.url || "";
  const reqBody: Record<string, unknown> = { model: model.id, prompt: serialized };
  if (isVideo) {
    reqBody.duration = effective.duration;
    reqBody.resolution = effective.resolution;
    if (effective.aspect_ratio) reqBody.aspect_ratio = effective.aspect_ratio;
    if (caps.audio) reqBody.generate_audio = effective.generate_audio;
    if (caps.seed && p.seed != null) reqBody.seed = p.seed;
    if (mode === "r2v" || mode === "r2v_pin") {
      const refs = refsIn.map((i) => ({ type: "image_url", image_url: { url: url(i.asset) } }));
      if (mode === "r2v_pin" && firstIn) refs.push({ type: "image_url", image_url: { url: url(firstIn.asset) } });
      reqBody.input_references = refs;
    } else if (firstIn || lastIn) {
      reqBody.frame_images = [firstIn, lastIn]
        .filter((i): i is ShotInputBody => Boolean(i))
        .map((i) => ({ type: "image_url", image_url: { url: url(i.asset) }, frame_type: i.slot }));
    }
  } else {
    if (effective.aspect_ratio) reqBody.aspect_ratio = effective.aspect_ratio;
    if (refsIn.length) reqBody.input_references = refsIn.map((i) => ({ type: "image_url", image_url: { url: url(i.asset) } }));
  }

  return {
    quote: {
      credits,
      breakdown,
      balance: bal,
      mode,
      effective,
      labels,
      serialized_prompt: serialized,
      errors,
      warnings,
      meter: { chars, words: wc, soft_words: soft, hard_chars: hard, level },
      dropped,
      eta_s: model.eta_s,
    },
    body: reqBody,
    billable,
  };
}

/* ------------------------------------------------------------------ */
/* Мок-сервер                                                          */
/* ------------------------------------------------------------------ */

export type MockTimings = {
  queuedMs: number;
  submittingMs: number;
  runningVideoMs: number;
  runningImageMs: number;
  savingMs: number;
};

export type MockOptions = {
  /** Гость: auth-эндпоинты отвечают 401, в quote нет баланса. */
  guest?: boolean;
  staff?: boolean;
  mode?: VsMode;
  balance?: number;
  /** Задержка каждого ответа, мс (скелетоны должны успеть показаться). */
  latencyMs?: number;
  /** Часы для тестов. */
  now?: () => number;
  /** false — пустая студия без истории и материалов. */
  seed?: boolean;
  timings?: Partial<MockTimings>;
};

export type MockUploadOptions = {
  project: Uid | null;
  onProgress?: (pct: number, phase: UploadPhase) => void;
  signal?: AbortSignal;
};

export type MockBackend = {
  fetch: (endpoint: string, method: string, body?: unknown) => Promise<RawResponse>;
  upload: (file: Blob, opts: MockUploadOptions) => Promise<RawResponse>;
  /** Для тестов и отладки. */
  inspect: () => { balance: number; reserved: number; takes: number; assets: number; projects: number };
};

type Outcome = "done" | "failed" | "lost";

type StoredAsset = AssetJSON & { deleted: boolean; dedupeKey?: string };

type StoredShot = {
  uid: Uid;
  project: Uid;
  kind: VsKind;
  origin: ShotOrigin;
  model: { id: string; name: string } | null;
  prompt_doc: PromptDoc;
  prompt_text: string;
  params: ShotParams;
  inputs: ShotInputBody[];
  labels: Record<Uid, string>;
  forked_from: Uid | null;
  created_at: string;
};

type StoredTake = {
  lite: TakeLite;
  project: Uid;
  startedAt: number;
  outcome: Outcome;
  failCode: string;
  /** Причина lost: у него их несколько, и текст в ленте выбирается по коду. */
  lostCode: string;
  failInput: Uid | null;
  serialized_prompt: string;
  request_body: Record<string, unknown>;
};

const DEFAULT_TIMINGS: MockTimings = {
  queuedMs: 1500,
  submittingMs: 2000,
  runningVideoMs: 9000,
  runningImageMs: 4000,
  savingMs: 1500,
};

const MAX_OPEN: Record<VsKind, number> = { video: 2, image: 4 };
const MAX_UPLOAD_BYTES = 15 * 1024 * 1024;
const IMAGE_EXT = /\.(jpe?g|jfif|jpe|png|webp|gif|heic|heif|bmp|tiff?)$/i;

const isOpen = (s: TakeStatus) => OPEN_TAKE_STATUSES.includes(s);

function reply(status: number, data: unknown, url = ""): RawResponse & { url: string } {
  return { ok: status >= 200 && status < 300, status, data, url };
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export function createMockBackend(options: MockOptions = {}): MockBackend {
  const now = options.now || (() => Date.now());
  const T: MockTimings = { ...DEFAULT_TIMINGS, ...(options.timings || {}) };
  const latency = options.latencyMs ?? 0;
  const mode: VsMode = options.mode || "on";
  const guest = Boolean(options.guest);
  const staff = options.staff ?? true;
  const models = buildModels();

  let balance = options.balance ?? 1200;
  const counters: Record<string, number> = {};
  const nextUid = (family: "a" | "b" | "c" | "d" | "e" | "f") => {
    counters[family] = (counters[family] || 0) + 1;
    // Старшие разряды — «соль» мока, чтобы uid не совпадали с uid-фикстурами тестов.
    return fixtureUid(family, 0x100000 + counters[family]);
  };
  // Время создания строго растёт: сортировки ленты и истории устойчивы.
  let lastStamp = 0;
  const stamp = () => {
    const t = Math.max(now(), lastStamp + 1);
    lastStamp = t;
    return new Date(t).toISOString();
  };

  const projects = new Map<Uid, ProjectJSON>();
  const shots = new Map<Uid, StoredShot>();
  const takes = new Map<Uid, StoredTake>();
  const assets = new Map<Uid, StoredAsset>();
  const idem = new Map<string, { project: Uid; shot: Uid; take: Uid; asset: Uid | null }>();

  const lookup: FixtureAssetLookup = (uid) => assets.get(uid);

  /* ---------- ассеты ---------- */

  function addAsset(
    source: AssetSource,
    label: string,
    hue: number,
    w: number,
    h: number,
    extra: Partial<StoredAsset> = {},
  ): StoredAsset {
    const uid = nextUid("a");
    const img = placeholderImage(label, hue, w, h);
    const a: StoredAsset = {
      uid,
      kind: "image",
      source,
      status: "ready",
      url: img,
      thumb_url: img,
      width: w,
      height: h,
      duration_s: null,
      label: "",
      flags: Math.min(w, h) < 300 ? { too_small: true } : {},
      error_code: null,
      created_at: stamp(),
      deleted: false,
      ...extra,
    };
    assets.set(uid, a);
    return a;
  }

  const publicAsset = (a: StoredAsset): AssetJSON => {
    const { deleted: _d, dedupeKey: _k, ...rest } = a;
    void _d;
    void _k;
    return rest;
  };

  /* ---------- дубли: время двигает статусы ---------- */

  function reservedTotal(): number {
    let sum = 0;
    for (const t of takes.values()) if (t.lite.charge_state === "reserved") sum += t.lite.credits.reserved;
    return sum;
  }

  function close(t: StoredTake, status: "done" | "failed" | "lost", at: number) {
    const L = t.lite;
    L.status = status;
    L.stage = "";
    L.finished_at = new Date(at).toISOString();
    L.queue_position = null;
    if (status === "done") {
      // Списание ровно один раз — за готовый результат.
      const charge = Math.min(L.credits.reserved, balance);
      balance -= charge;
      L.credits.charged = charge;
      L.charge_state = "charged";
      if (L.kind === "image") {
        const pending = L.result ? assets.get(L.result.uid) : undefined;
        if (pending) {
          const img = placeholderImage("Картинка", (at / 1000) % 360, 1024, 1024);
          Object.assign(pending, { status: "ready", url: img, thumb_url: img, width: 1024, height: 1024 });
          L.result = publicAsset(pending);
        }
      } else {
        const poster = placeholderImage("Видео", (at / 997) % 360, 1280, 720);
        const a = addAsset("generated_video", "Видео", 200, 1280, 720, {
          kind: "video",
          url: FIXTURE_VIDEO_URL,
          thumb_url: poster,
          duration_s: L.effective.duration ?? 5,
        });
        L.result = publicAsset(a);
      }
    } else {
      L.charge_state = "released";
      L.credits.charged = 0;
      const code = status === "lost" ? t.lostCode : t.failCode;
      L.error = { code, message: TAKE_ERROR_RU[code] || ERROR_RU.unknown, input: status === "lost" ? null : t.failInput };
      if (L.kind === "image" && L.result) {
        const pending = assets.get(L.result.uid);
        if (pending) {
          Object.assign(pending, { status: "failed", error_code: code });
          L.result = publicAsset(pending);
        }
      }
    }
    const p = projects.get(t.project);
    if (p) p.last_activity_at = new Date(at).toISOString();
  }

  function advance(t: StoredTake) {
    const L = t.lite;
    if (!isOpen(L.status)) return;
    const age = now() - t.startedAt;
    L.elapsed_s = Math.max(0, Math.floor(age / 1000));
    const q = T.queuedMs;
    if (L.kind === "image") {
      const end = q + T.runningImageMs;
      if (age < q) L.status = "queued";
      else if (age < end) {
        L.status = "running";
        L.stage = "in_progress";
        L.submitted_at ||= new Date(t.startedAt + q).toISOString();
      } else close(t, t.outcome, t.startedAt + end);
      return;
    }
    const sub = q + T.submittingMs;
    const run = sub + T.runningVideoMs;
    const save = run + T.savingMs;
    if (age < q) L.status = "queued";
    else if (age < sub) L.status = "submitting";
    else if (t.outcome === "lost") close(t, "lost", t.startedAt + sub);
    else {
      L.submitted_at ||= new Date(t.startedAt + sub).toISOString();
      if (age < run) {
        L.status = "running";
        L.stage = age - sub < 2000 ? "pending" : "in_progress";
      } else if (t.outcome === "failed") close(t, "failed", t.startedAt + run);
      else if (age < save) {
        L.status = "saving";
        L.stage = "";
      } else close(t, "done", t.startedAt + save);
    }
  }

  function advanceAll() {
    for (const t of takes.values()) advance(t);
    // Честная очередь: номер среди ещё не отправленных, по времени запуска.
    const queued = [...takes.values()].filter((t) => t.lite.status === "queued").sort((a, b) => a.startedAt - b.startedAt);
    queued.forEach((t, i) => (t.lite.queue_position = i));
  }

  /* ---------- сериализация ---------- */

  const projectJSON = (p: ProjectJSON): ProjectJSON => {
    let open = 0;
    let thumb: string | null = null;
    let thumbAt = "";
    for (const t of takes.values()) {
      if (t.project !== p.uid) continue;
      if (isOpen(t.lite.status)) open++;
      const r = t.lite.result;
      if (r && r.status === "ready" && (t.lite.finished_at || "") > thumbAt) {
        thumb = r.thumb_url;
        thumbAt = t.lite.finished_at || "";
      }
    }
    return { ...p, open_takes: open, thumb_url: thumb };
  };

  const takeLite = (t: StoredTake): TakeLite => JSON.parse(JSON.stringify(t.lite)) as TakeLite;

  function shotJSON(s: StoredShot): ShotJSON {
    const inputs: ShotInputJSON[] = s.inputs.flatMap((i) => {
      const a = assets.get(i.asset);
      if (!a) return [];
      return [
        {
          asset: publicAsset(a),
          slot: i.slot,
          position: i.position,
          role: i.role || "",
          included: i.included,
          label: s.labels[i.asset] ?? null,
        },
      ];
    });
    const shotTakes = [...takes.values()]
      .filter((t) => t.lite.shot === s.uid)
      .sort((a, b) => a.startedAt - b.startedAt)
      .map(takeLite);
    return {
      uid: s.uid,
      project: s.project,
      kind: s.kind,
      origin: s.origin,
      model: s.model,
      prompt_doc: s.prompt_doc,
      prompt_text: s.prompt_text,
      params: s.params,
      inputs,
      forked_from: s.forked_from,
      created_at: s.created_at,
      takes: shotTakes,
    };
  }

  function renderPromptText(doc: PromptDoc, labels: Record<Uid, string>): string {
    const chip = (uid: Uid) => {
      const l = labels[uid];
      if (!l) return "@—";
      if (l === "first_frame") return "@Первый кадр";
      if (l === "last_frame") return "@Последний кадр";
      return `@${l}`;
    };
    return doc.blocks.map((b) => b.map((n) => (n.t === "text" ? n.v : chip(n.asset))).join("")).join("\n");
  }

  /* ---------- создание кадра и дубля ---------- */

  function outcomeFor(text: string): Outcome {
    if (text.includes("#lost")) return "lost";
    if (text.includes("#fail")) return "failed";
    return "done";
  }

  function newTake(
    shot: StoredShot,
    compiled: FixtureCompiled,
    credits: number,
    opts: { closed?: { status: "done" | "failed"; code?: string; input?: Uid | null; at: number } } = {},
  ): StoredTake {
    const model = modelById(models, shot.kind, shot.model?.id || "");
    const plain = plainText(shot.prompt_doc);
    const outcome = outcomeFor(plain);
    const uploadInput = shot.inputs.find((i) => i.included && assets.get(i.asset)?.source === "upload");
    const faces = Boolean(model?.caps.rejects_real_faces && uploadInput);
    const created = stamp();
    const startedAt = Date.parse(created);
    let result: AssetJSON | null = null;
    if (shot.kind === "image") {
      // Картинка: ассет в pending появляется сразу — чип в лотке «создаётся».
      const pending = addAsset("generated_image", "…", 40, 1024, 1024, {
        status: "pending",
        url: null,
        thumb_url: null,
        width: null,
        height: null,
      });
      result = publicAsset(pending);
    }
    const t: StoredTake = {
      lite: {
        uid: nextUid("d"),
        shot: shot.uid,
        kind: shot.kind,
        status: "queued",
        stage: "",
        mode: compiled.quote.mode || (shot.kind === "image" ? "t2i" : "t2v"),
        charge_state: "reserved",
        credits: { quoted: credits, reserved: credits, charged: 0 },
        effective: compiled.quote.effective,
        warnings: compiled.quote.warnings,
        dropped: compiled.quote.dropped,
        result,
        error: null,
        eta_s: model?.eta_s ?? 60,
        elapsed_s: 0,
        queue_position: 0,
        created_at: created,
        submitted_at: null,
        finished_at: null,
      },
      project: shot.project,
      startedAt,
      outcome,
      failCode: faces ? "image_real_person" : "prompt_rejected",
      lostCode: plain.includes("#lost_save") ? "save_failed" : "submit_unknown",
      failInput: faces && uploadInput ? uploadInput.asset : null,
      serialized_prompt: compiled.quote.serialized_prompt,
      request_body: compiled.body,
    };
    takes.set(t.lite.uid, t);
    if (opts.closed) {
      t.outcome = opts.closed.status;
      if (opts.closed.code) t.failCode = opts.closed.code;
      if (opts.closed.input !== undefined) t.failInput = opts.closed.input;
      close(t, opts.closed.status, opts.closed.at);
    }
    return t;
  }

  function newShot(body: QuoteBody, compiled: FixtureCompiled, project: Uid, origin: ShotOrigin): StoredShot {
    const model = modelById(models, body.kind, body.model);
    // Сервер хранит документ уже с привязанными тегами (compiler → link_tags).
    const doc = linkDocTags(body.prompt_doc ?? docFromText(body.prompt_text ?? ""), body.inputs || []).doc;
    const s: StoredShot = {
      uid: nextUid("c"),
      project,
      kind: body.kind,
      origin,
      model: model ? { id: model.id, name: model.name } : null,
      prompt_doc: doc,
      prompt_text: renderPromptText(doc, compiled.quote.labels),
      params: { ...(body.params || {}) },
      inputs: (body.inputs || []).map((i) => ({ ...i })),
      labels: compiled.quote.labels,
      forked_from: null,
      created_at: stamp(),
    };
    shots.set(s.uid, s);
    return s;
  }

  function newProject(title: string, settings: ProjectSettings = {}, at: string = stamp()): ProjectJSON {
    const p: ProjectJSON = {
      uid: nextUid("b"),
      title,
      kind: "playground",
      settings,
      is_archived: false,
      last_activity_at: at,
      thumb_url: null,
      open_takes: 0,
    };
    projects.set(p.uid, p);
    return p;
  }

  const balanceNow = () => ({ balance, reserved: reservedTotal() });

  /* ---------- стартовые данные ---------- */

  function seed() {
    const ago = (ms: number) => new Date(now() - ms).toISOString();
    const yard = addAsset("upload", "Двор", 30, 1280, 853);
    const hero = addAsset("upload", "Героиня", 300, 853, 1280);
    const cat = addAsset("generated_image", "Кот", 190, 1024, 1024);
    addAsset("frame", "Кадр", 120, 1280, 720);
    addAsset("upload", "Мало", 90, 240, 240);

    const archived = newProject("Старый тест", {}, ago(3 * 86400_000));
    archived.is_archived = true;

    const p2 = newProject(
      "Закат над Бишкеком",
      { kind: "image", model: "google/gemini-2.5-flash-image", params: { aspect_ratio: "16:9" } },
      ago(26 * 3600_000),
    );
    const b3: QuoteBody = {
      project: p2.uid,
      kind: "image",
      model: "google/gemini-2.5-flash-image",
      prompt_doc: docFromText("Закат над горами Ала-Тоо, акварель"),
      inputs: [],
      params: { aspect_ratio: "16:9" },
    };
    const c3 = fixtureCompile(models, b3, lookup, null);
    const s3 = newShot(b3, c3, p2.uid, "composer");
    const t3 = newTake(s3, c3, c3.quote.credits || 6);
    t3.startedAt = now() - 26 * 3600_000;
    // Картинка готова: подставляем «кота» как результат, баланс не трогаем (история).
    const pending = t3.lite.result ? assets.get(t3.lite.result.uid) : undefined;
    if (pending) assets.delete(pending.uid);
    Object.assign(t3.lite, {
      created_at: new Date(t3.startedAt).toISOString(),
      status: "done",
      charge_state: "charged",
      credits: { ...t3.lite.credits, charged: t3.lite.credits.reserved },
      result: publicAsset(cat),
      queue_position: null,
      submitted_at: new Date(t3.startedAt + 1000).toISOString(),
      finished_at: new Date(t3.startedAt + 15000).toISOString(),
      elapsed_s: 15,
    });

    const p1 = newProject(
      "Кошка на крыше",
      {
        kind: "video",
        model: "bytedance/seedance-2.0",
        params: { duration: 10, resolution: "720p", aspect_ratio: "9:16", generate_audio: true },
      },
      ago(5 * 60_000),
    );
    const b1: QuoteBody = {
      project: p1.uid,
      kind: "video",
      model: "bytedance/seedance-2.0",
      prompt_doc: {
        v: 1,
        blocks: [
          [
            { t: "ref", asset: hero.uid },
            { t: "text", v: " медленно идёт по старому двору " },
            { t: "ref", asset: yard.uid },
            { t: "text", v: ", камера плавно наезжает, тёплый закатный свет" },
          ],
        ],
      },
      inputs: [
        { asset: hero.uid, slot: "reference", position: 0, role: "героиня", included: true },
        { asset: yard.uid, slot: "reference", position: 1, role: "", included: true },
      ],
      params: { duration: 10, resolution: "720p", aspect_ratio: "9:16", generate_audio: true },
    };
    const c1 = fixtureCompile(models, b1, lookup, null);
    const s1 = newShot(b1, c1, p1.uid, "composer");
    const t1 = newTake(s1, c1, c1.quote.credits || 0);
    const doneAt = now() - 20 * 60_000;
    t1.startedAt = doneAt - 140_000;
    const poster = placeholderImage("Кошка", 20, 720, 1280);
    const video = addAsset("generated_video", "Кошка", 20, 720, 1280, {
      kind: "video",
      url: FIXTURE_VIDEO_URL,
      thumb_url: poster,
      duration_s: 10,
    });
    Object.assign(t1.lite, {
      created_at: new Date(t1.startedAt).toISOString(),
      status: "done",
      charge_state: "charged",
      credits: { ...t1.lite.credits, charged: t1.lite.credits.reserved },
      result: publicAsset(video),
      queue_position: null,
      submitted_at: new Date(t1.startedAt + 3000).toISOString(),
      finished_at: new Date(doneAt).toISOString(),
      elapsed_s: 140,
    });

    const b2: QuoteBody = {
      project: p1.uid,
      kind: "video",
      model: "bytedance/seedance-2.0",
      prompt_doc: {
        v: 1,
        blocks: [[{ t: "ref", asset: hero.uid }, { t: "text", v: " танцует под дождём на крыше" }]],
      },
      inputs: [{ asset: hero.uid, slot: "reference", position: 0, role: "героиня", included: true }],
      params: { duration: 5, resolution: "720p", aspect_ratio: "9:16", generate_audio: true },
    };
    const c2 = fixtureCompile(models, b2, lookup, null);
    const s2 = newShot(b2, c2, p1.uid, "composer");
    newTake(s2, c2, c2.quote.credits || 0, {
      closed: { status: "failed", code: "image_real_person", input: hero.uid, at: now() - 10 * 60_000 },
    });
    p1.last_activity_at = ago(5 * 60_000);
  }

  if (options.seed !== false) seed();

  /* ---------- ворота: флаг, вход ---------- */

  function gate(needAuth: boolean): RawResponse | null {
    if (mode === "off" || (mode === "staff" && (guest || !staff))) {
      return reply(403, errorBody("vstudio_disabled"));
    }
    if (needAuth && guest) {
      return reply(401, { detail: "Учетные данные не были предоставлены." });
    }
    return null;
  }

  /* ---------- маршруты ---------- */

  function listProjects(q: URLSearchParams): RawResponse {
    const archived = q.get("archived") === "1";
    const needle = (q.get("q") || "").trim().toLowerCase();
    const before = q.get("before");
    const limit = Math.max(1, Math.min(100, Number(q.get("limit")) || 30));
    let items = [...projects.values()].filter((p) => p.is_archived === archived);
    if (needle) items = items.filter((p) => p.title.toLowerCase().includes(needle));
    items.sort((a, b) => (a.last_activity_at < b.last_activity_at ? 1 : -1));
    if (before) items = items.filter((p) => p.last_activity_at < before);
    const page = items.slice(0, limit);
    const next = items.length > limit ? page[page.length - 1].last_activity_at : null;
    return reply(200, { items: page.map(projectJSON), next });
  }

  function listShots(projectUid: Uid, q: URLSearchParams): RawResponse {
    if (!projects.has(projectUid)) return reply(404, errorBody("project_not_found"));
    const limit = Math.max(1, Math.min(50, Number(q.get("limit")) || 20));
    let all = [...shots.values()].filter((s) => s.project === projectUid).sort((a, b) => (a.created_at < b.created_at ? -1 : 1));
    const before = q.get("before");
    if (before) {
      const idx = all.findIndex((s) => s.uid === before);
      all = idx >= 0 ? all.slice(0, idx) : [];
    }
    const page = all.slice(Math.max(0, all.length - limit));
    const next = all.length > limit ? page[0].uid : null;
    return reply(200, { items: page.map(shotJSON), next });
  }

  function listAssets(q: URLSearchParams): RawResponse {
    const kind = q.get("kind") || "image";
    const source = q.get("source") || "";
    const before = q.get("before");
    const limit = Math.max(1, Math.min(100, Number(q.get("limit")) || 60));
    let items = [...assets.values()].filter((a) => !a.deleted && a.kind === kind);
    if (source) items = items.filter((a) => a.source === source);
    items.sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
    if (before) items = items.filter((a) => a.created_at < before);
    const page = items.slice(0, limit);
    const next = items.length > limit ? page[page.length - 1].created_at : null;
    return reply(200, { items: page.map(publicAsset), next });
  }

  function quoteRoute(body: unknown): RawResponse {
    const b = (body || {}) as Partial<QuoteBody> & { shot?: Uid };
    let qb: QuoteBody;
    let allowDeleted = false;
    if (typeof b.shot === "string") {
      if (guest) return reply(401, { detail: "Учетные данные не были предоставлены." });
      const s = shots.get(b.shot);
      if (!s) return reply(404, errorBody("shot_not_found"));
      qb = bodyOfShot(s);
      allowDeleted = true;
    } else {
      if (!b.kind || !b.model) return reply(400, errorBody("bad_request"));
      // Гость может спросить цену только без материалов.
      if (guest && (b.inputs || []).length) return reply(401, { detail: "Учетные данные не были предоставлены." });
      qb = b as QuoteBody;
    }
    const compiled = fixtureCompile(models, qb, lookup, guest ? null : balanceNow(), { allowDeleted });
    return reply(200, compiled.quote);
  }

  function bodyOfShot(s: StoredShot): QuoteBody {
    return {
      project: s.project,
      kind: s.kind,
      model: s.model?.id || "",
      prompt_doc: s.prompt_doc,
      inputs: s.inputs.map((i) => ({ ...i })),
      params: { ...s.params },
    };
  }

  /** Общая часть POST shots/ и retry/: модель, компилятор, цена, лимиты, баланс. */
  function admit(
    qb: QuoteBody,
    quoted: number,
    allowDeleted: boolean,
  ): { error: RawResponse } | { compiled: FixtureCompiled; credits: number } {
    const model = modelById(models, qb.kind, qb.model);
    if (model?.locked) return { error: reply(403, errorBody("premium_locked")) };
    const compiled = fixtureCompile(models, qb, lookup, balanceNow(), { allowDeleted });
    const q = compiled.quote;
    if (q.errors.length || q.credits == null) {
      return { error: reply(422, { ...errorBody("blocked"), errors: q.errors, warnings: q.warnings }) };
    }
    if (Number(quoted) !== q.credits) {
      return { error: reply(409, errorBody("price_changed", { credits: q.credits, breakdown: q.breakdown })) };
    }
    const open = [...takes.values()].filter((t) => t.lite.kind === qb.kind && isOpen(t.lite.status)).length;
    if (open >= MAX_OPEN[qb.kind]) {
      return { error: reply(409, errorBody("too_many_open", { limit: MAX_OPEN[qb.kind], kind: qb.kind })) };
    }
    const { balance: bal, reserved } = balanceNow();
    const available = Math.max(0, bal - reserved);
    if (available < q.credits) {
      const extra: Record<string, unknown> = { balance_tokens: available, required_estimate: q.credits };
      if (reserved > 0) extra.reserved_credits = reserved;
      return { error: reply(402, errorBody("insufficient_balance", extra)) };
    }
    return { compiled, credits: q.credits };
  }

  const balanceJSON = (): BalanceJSON => {
    const { balance: b, reserved } = balanceNow();
    return { balance: b, reserved, available: Math.max(0, b - reserved) };
  };

  function runResponse(ids: { project: Uid; shot: Uid; take: Uid; asset: Uid | null }): RunShotResponse {
    const p = projects.get(ids.project) as ProjectJSON;
    const s = shots.get(ids.shot) as StoredShot;
    const t = takes.get(ids.take) as StoredTake;
    const a = ids.asset ? assets.get(ids.asset) : undefined;
    return {
      project: projectJSON(p),
      shot: shotJSON(s),
      take: takeLite(t),
      asset: a ? publicAsset(a) : null,
      balance: balanceJSON(),
    };
  }

  function runRoute(body: unknown): RawResponse {
    const b = (body || {}) as Partial<RunShotBody>;
    const crid = String(b.client_request_id || "");
    if (!crid || crid.length > 64 || !b.kind || !b.model) return reply(400, errorBody("bad_request"));
    const seen = idem.get(crid);
    if (seen) return reply(200, runResponse(seen));
    if (b.project && !projects.has(b.project)) return reply(404, errorBody("project_not_found"));
    const qb = b as RunShotBody;
    const res = admit(qb, Number(b.quoted_credits), false);
    if ("error" in res) return res.error;
    const doc = qb.prompt_doc ?? docFromText(qb.prompt_text ?? "");
    const project =
      (qb.project && projects.get(qb.project)) ||
      newProject(plainText(doc).trim().slice(0, 60) || "Без названия", {
        kind: qb.kind,
        model: qb.model,
        params: qb.params,
      });
    const shot = newShot({ ...qb, project: project.uid }, res.compiled, project.uid, qb.origin || "composer");
    const take = newTake(shot, res.compiled, res.credits);
    project.last_activity_at = stamp();
    const ids = { project: project.uid, shot: shot.uid, take: take.lite.uid, asset: take.lite.result?.uid || null };
    idem.set(crid, ids);
    return reply(202, runResponse(ids));
  }

  function retryRoute(shotUid: Uid, body: unknown): RawResponse {
    const s = shots.get(shotUid);
    if (!s) return reply(404, errorBody("shot_not_found"));
    const b = (body || {}) as { quoted_credits?: number; client_request_id?: string };
    const crid = String(b.client_request_id || "");
    if (!crid || crid.length > 64) return reply(400, errorBody("bad_request"));
    const seen = idem.get(crid);
    if (seen) return reply(200, { take: takeLite(takes.get(seen.take) as StoredTake), balance: balanceJSON() });
    const res = admit(bodyOfShot(s), Number(b.quoted_credits), true);
    if ("error" in res) return res.error;
    const take = newTake(s, res.compiled, res.credits);
    idem.set(crid, { project: s.project, shot: s.uid, take: take.lite.uid, asset: take.lite.result?.uid || null });
    const p = projects.get(s.project);
    if (p) p.last_activity_at = stamp();
    return reply(202, { take: takeLite(take), balance: balanceJSON() });
  }

  function condenseRoute(body: unknown): RawResponse {
    const b = (body || {}) as Partial<CondenseBody>;
    const doc = b.prompt_doc;
    if (!doc || doc.v !== 1 || !Array.isArray(doc.blocks)) return reply(422, errorBody("prompt_doc_invalid"));
    if (plainText(doc).includes("#condense_fail")) return reply(422, errorBody("condense_failed"));
    const model = [...models.video, ...models.image].find((m) => m.id === b.model);
    const budget = model?.caps.prompt.soft_words || 60;
    let left = budget;
    // Каждая ссылка остаётся ровно один раз; текст режется по словам.
    const blocks = doc.blocks
      .map((block) =>
        block.flatMap((n): PromptNode[] => {
          if (n.t === "ref") {
            // Чип в счётчике — «@Image N», два слова (как у сервера после сериализации).
            left -= 2;
            return [n];
          }
          const parts = n.v.split(/(\s+)/);
          let out = "";
          for (const part of parts) {
            if (!part) continue;
            if (/^\s+$/.test(part)) {
              if (out) out += " ";
              continue;
            }
            if (left <= 0) break;
            out += part;
            left -= 1;
          }
          // Пробелы по краям сохраняем: иначе текст прилипнет к соседнему чипу.
          const lead = out && /^\s/.test(n.v) ? " " : "";
          const trail = out && /\s$/.test(n.v) ? " " : "";
          return out ? [{ t: "text", v: lead + out + trail }] : [];
        }),
      )
      .filter((b) => b.length);
    const result: PromptDoc = { v: 1, blocks: blocks.length ? blocks : [[]] };
    return reply(200, { prompt_doc: result, before: docStats(doc), after: docStats(result) });
  }

  function fromTakeRoute(body: unknown): RawResponse {
    const b = (body || {}) as { take?: Uid; at?: string };
    const t = b.take ? takes.get(b.take) : undefined;
    if (!t || t.lite.kind !== "video" || t.lite.status !== "done") return reply(404, errorBody("take_not_found"));
    const a = addAsset("frame", "Последний кадр", 120, 1280, 720);
    return reply(201, publicAsset(a));
  }

  async function handle(endpoint: string, method: string, body?: unknown): Promise<RawResponse> {
    advanceAll();
    const [path, query = ""] = endpoint.split("?");
    const q = new URLSearchParams(query);
    const seg = path.split("/").filter(Boolean);
    const M = method.toUpperCase();

    if (seg[0] === "ai" && seg[1] === "video" && seg[2] === "share" && M === "POST") {
      if (guest) return reply(401, { detail: "Учетные данные не были предоставлены." });
      return reply(201, { share_url: `https://esai.kg/v/fixture${Date.now().toString(36)}` });
    }
    if (seg[0] !== "vstudio") return reply(404, { detail: "Не найдено." });
    const [, a, b, c] = seg;

    if (a === "models" && !b && M === "GET") {
      return reply(200, {
        mode,
        available: mode === "on" || (mode === "staff" && staff && !guest),
        video: models.video,
        image: models.image,
      } satisfies ModelsResponse);
    }
    if (a === "quote" && !b && M === "POST") return gate(false) || quoteRoute(body);

    const denied = gate(true);
    if (denied) return denied;

    if (a === "projects") {
      if (!b) {
        if (M === "GET") return listProjects(q);
        if (M === "POST") {
          const title = String((body as { title?: string } | undefined)?.title || "").slice(0, 140);
          return reply(201, projectJSON(newProject(title)));
        }
      } else {
        const p = projects.get(b);
        if (!p) return reply(404, errorBody("project_not_found"));
        if (c === "shots" && M === "GET") return listShots(b, q);
        if (!c) {
          if (M === "GET") return reply(200, projectJSON(p));
          if (M === "PATCH") {
            const patch = (body || {}) as Partial<ProjectJSON>;
            if (typeof patch.title === "string") p.title = patch.title.slice(0, 140);
            if (patch.settings && typeof patch.settings === "object") p.settings = { ...patch.settings };
            if (typeof patch.is_archived === "boolean") p.is_archived = patch.is_archived;
            return reply(200, projectJSON(p));
          }
          if (M === "DELETE") {
            p.is_archived = true;
            return reply(204, null);
          }
        }
      }
    }
    if (a === "assets") {
      if (!b && M === "GET") return listAssets(q);
      if (b === "from-take" && M === "POST") return fromTakeRoute(body);
      if (b && !c && M === "DELETE") {
        const asset = assets.get(b);
        if (!asset || asset.deleted) return reply(404, errorBody("asset_not_found"));
        asset.deleted = true;
        return reply(204, null);
      }
    }
    if (a === "shots") {
      if (!b && M === "POST") return runRoute(body);
      if (b && c === "retry" && M === "POST") return retryRoute(b, body);
    }
    if (a === "takes") {
      if (!b && M === "GET") {
        const ids = (q.get("ids") || "").split(",").filter(Boolean).slice(0, 30);
        const items = ids.flatMap((id) => {
          const t = takes.get(id);
          return t ? [takeLite(t)] : [];
        });
        return reply(200, { items });
      }
      if (b === "active" && M === "GET") {
        const items: ActiveTake[] = [...takes.values()]
          .filter((t) => isOpen(t.lite.status))
          .map((t) => ({ ...takeLite(t), project_uid: t.project }));
        return reply(200, { items });
      }
      if (b && b !== "active") {
        const t = takes.get(b);
        if (!t) return reply(404, errorBody("take_not_found"));
        if (!c && M === "GET") {
          const full: TakeJSON = { ...takeLite(t), serialized_prompt: t.serialized_prompt, request_body: t.request_body };
          return reply(200, full);
        }
        if (c === "cancel" && M === "POST") {
          if (t.lite.status !== "queued") return reply(409, errorBody("already_submitted"));
          Object.assign(t.lite, {
            status: "canceled",
            charge_state: "released",
            queue_position: null,
            finished_at: new Date(now()).toISOString(),
          });
          if (t.lite.kind === "image" && t.lite.result) {
            const pending = assets.get(t.lite.result.uid);
            if (pending) {
              Object.assign(pending, { status: "failed", error_code: "canceled" });
              t.lite.result = publicAsset(pending);
            }
          }
          return reply(200, takeLite(t));
        }
      }
    }
    if (a === "assist" && b === "condense" && M === "POST") return condenseRoute(body);
    return reply(404, { detail: "Не найдено." });
  }

  async function upload(file: Blob, opts: MockUploadOptions): Promise<RawResponse> {
    const denied = gate(true);
    if (denied) return denied;
    const aborted = (): RawResponse => ({ ok: false, status: 0, data: { error_code: "aborted" } });
    const name = typeof File !== "undefined" && file instanceof File ? file.name : "";
    const type = (file.type || "").toLowerCase();

    // Прогресс «по сети»: четыре шага за время задержки.
    for (const pct of [0, 25, 50, 75]) {
      if (opts.signal?.aborted) return aborted();
      opts.onProgress?.(pct, "upload");
      if (latency) await sleep(latency / 4);
    }
    if (opts.signal?.aborted) return aborted();
    opts.onProgress?.(100, "processing");
    if (latency) await sleep(latency);
    if (opts.signal?.aborted) return aborted();

    if (file.size > MAX_UPLOAD_BYTES) return reply(413, errorBody("file_too_large"));
    if (type.startsWith("video/") || type.startsWith("audio/")) return reply(422, errorBody("video_refs_unsupported"));
    const isImage = (type.startsWith("image/") && type !== "image/svg+xml") || (!type && IMAGE_EXT.test(name));
    if (!isImage) return reply(422, errorBody("unsupported_type"));

    const key = `${name}|${file.size}|${type}`;
    for (const a of assets.values()) {
      if (!a.deleted && a.dedupeKey === key) return reply(200, publicAsset(a));
    }

    let w = 1024;
    let h = 1024;
    try {
      if (typeof createImageBitmap === "function") {
        const bmp = await createImageBitmap(file);
        w = bmp.width;
        h = bmp.height;
        bmp.close?.();
      }
    } catch {
      /* HEIC и прочее, что браузер не декодирует: оставляем 1024 */
    }
    let url: string | null = null;
    try {
      if (typeof URL !== "undefined" && typeof URL.createObjectURL === "function") url = URL.createObjectURL(file);
    } catch {
      url = null;
    }
    const a = addAsset("upload", name || "Фото", (file.size % 360) + 1, w, h, { dedupeKey: key });
    if (url) {
      a.url = url;
      a.thumb_url = url;
    }
    if (/\.hei[cf]$/i.test(name) || type.includes("heic") || type.includes("heif")) a.flags = { ...a.flags, heic: true };
    return reply(201, publicAsset(a));
  }

  return {
    async fetch(endpoint, method, body) {
      if (latency) await sleep(latency);
      // Копия тела: мок не должен держать ссылки на объекты стора фронта.
      const copy = body === undefined ? undefined : JSON.parse(JSON.stringify(body));
      return handle(endpoint, method, copy);
    },
    upload,
    inspect() {
      advanceAll();
      return {
        balance,
        reserved: reservedTotal(),
        takes: takes.size,
        assets: [...assets.values()].filter((a) => !a.deleted).length,
        projects: projects.size,
      };
    },
  };
}

/* ------------------------------------------------------------------ */
/* Один мок на вкладку                                                 */
/* ------------------------------------------------------------------ */

let singleton: MockBackend | null = null;

function optionsFromStorage(): MockOptions {
  try {
    if (typeof window === "undefined") return {};
    const raw = window.localStorage.getItem("vstudio:fixtures:opts");
    const parsed = raw ? (JSON.parse(raw) as unknown) : null;
    if (!parsed || typeof parsed !== "object") return { latencyMs: 250 };
    const o = parsed as Record<string, unknown>;
    return {
      guest: o.guest === true,
      staff: o.staff !== false,
      mode: o.mode === "off" || o.mode === "staff" || o.mode === "on" ? o.mode : "on",
      balance: typeof o.balance === "number" ? o.balance : undefined,
      latencyMs: typeof o.latencyMs === "number" ? o.latencyMs : 250,
    };
  } catch {
    return { latencyMs: 250 };
  }
}

export function getMockBackend(): MockBackend {
  if (!singleton) singleton = createMockBackend(optionsFromStorage());
  return singleton;
}

/** Для тестов: новый мок с заданными настройками (null — сбросить к настройкам по умолчанию). */
export function resetMockBackend(options: MockOptions | null = null): MockBackend | null {
  singleton = options ? createMockBackend(options) : null;
  return singleton;
}

/* ------------------------------------------------------------------ */
/* Готовые объекты для вёрстки и тестов                                 */
/* ------------------------------------------------------------------ */

export function fixtureAsset(overrides: Partial<AssetJSON> = {}): AssetJSON {
  const img = placeholderImage("Фото", 210, 1024, 768);
  return {
    uid: fixtureUid("a", 1),
    kind: "image",
    source: "upload",
    status: "ready",
    url: img,
    thumb_url: img,
    width: 1024,
    height: 768,
    duration_s: null,
    label: "",
    flags: {},
    error_code: null,
    created_at: "2026-09-24T10:00:00.000Z",
    ...overrides,
  };
}

/** Дубль в любом статусе — вёрстка TakeStatus без сервера. */
export function fixtureTake(status: TakeStatus, overrides: Partial<TakeLite> = {}): TakeLite {
  const closed = !isOpen(status);
  const done = status === "done";
  const failed = status === "failed" || status === "lost";
  return {
    uid: fixtureUid("d", 1),
    shot: fixtureUid("c", 1),
    kind: "video",
    status,
    stage: status === "running" ? "in_progress" : "",
    mode: "r2v",
    charge_state: closed ? (done ? "charged" : "released") : "reserved",
    credits: { quoted: 164, reserved: 164, charged: done ? 164 : 0 },
    effective: { duration: 10, resolution: "720p", aspect_ratio: "9:16", generate_audio: true },
    warnings: [],
    dropped: [],
    result: done
      ? fixtureAsset({
          uid: fixtureUid("a", 2),
          kind: "video",
          source: "generated_video",
          url: FIXTURE_VIDEO_URL,
          thumb_url: placeholderImage("Видео", 20, 720, 1280),
          width: 720,
          height: 1280,
          duration_s: 10,
        })
      : null,
    error: failed
      ? {
          code: status === "lost" ? "submit_unknown" : "image_real_person",
          message: TAKE_ERROR_RU[status === "lost" ? "submit_unknown" : "image_real_person"],
          input: status === "lost" ? null : fixtureUid("a", 1),
        }
      : null,
    eta_s: 150,
    elapsed_s: status === "queued" ? 3 : 84,
    queue_position: status === "queued" ? 1 : null,
    created_at: "2026-09-24T10:00:00.000Z",
    submitted_at: status === "queued" ? null : "2026-09-24T10:00:04.000Z",
    finished_at: closed ? "2026-09-24T10:02:30.000Z" : null,
    ...overrides,
  };
}

/** Пример QuoteJSON из §8.3 (Seedance 2.0, два фото, длинный промпт). */
export const FIXTURE_QUOTE: QuoteJSON = {
  credits: 164,
  breakdown: [
    { key: "price.video", params: { s: 10, res: "720p", ar: "9:16" }, credits: 150 },
    { key: "price.refs", params: { n: 2 }, credits: 14 },
  ],
  balance: { balance: 1200, reserved: 120, available: 1080, after: 916 },
  mode: "r2v",
  effective: { duration: 10, resolution: "720p", aspect_ratio: "9:16", generate_audio: true },
  labels: { [fixtureUid("a", 1)]: "Image 1", [fixtureUid("a", 2)]: "Image 2" },
  serialized_prompt:
    "Image 1 is героиня.\nImage 1 медленно идёт по старому двору Image 2, камера плавно наезжает, тёплый закатный свет",
  errors: [],
  warnings: [
    {
      code: "prompt_long",
      params: { words: 480, soft: 150, model: "Seedance 2.0" },
      message: fillRu(WARNING_RU.prompt_long, { words: 480, soft: 150, model: "Seedance 2.0" }),
      fix: { action: "condense" },
    },
  ],
  meter: { chars: 2940, words: 480, soft_words: 150, hard_chars: 6000, level: "soft" },
  dropped: [],
  eta_s: 150,
};

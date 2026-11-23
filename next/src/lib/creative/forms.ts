/**
 * Формы 15 инструментов Creative Studio: какие поля показать и как.
 *
 * Имена полей, пределы и значения по умолчанию повторяют серверный реестр
 * (core/creative/registry.py, SPEC_B §2): сервер всё равно проверит каждое
 * поле, здесь — только чтобы человек не ждал отказа. Подписи — ключи
 * пространства `creative` (form.*), русский текст — в CREATIVE_TEXT_RU (text.ts).
 *
 * Поставщика и его модели здесь не называем: файл уходит в браузер.
 */
import type { CatalogKind } from "./api";

/** Ключ подписи в creative.json (русский текст — в text.ts). */
export type TextKey = string;

type Base = {
  name: string;
  label: TextKey;
  hint?: TextKey;
  /** поле в свёрнутом блоке «Дополнительно» */
  advanced?: boolean;
};

export type TextField = Base & { type: "text"; required?: boolean; max: number; rows?: number; placeholder?: TextKey };
/** enum: «авто» без значения по умолчанию не отправляется вовсе (auto = поле не слать). */
export type EnumField = Base & {
  type: "enum";
  choices: readonly string[];
  default?: string;
  /** группа подписей значений: opt.<group>.<value>; без неё значение показывается как есть */
  opt?: string;
  ui: "chips" | "select";
};
export type IntField = Base & { type: "int"; default: number; choices?: readonly number[]; min?: number; max?: number; ui: "chips" | "range"; unit?: TextKey };
export type BoolField = Base & { type: "bool"; default: boolean };
export type ImageField = Base & { type: "image"; required?: boolean };
export type ImagesField = Base & { type: "images"; min: number; max: number };
export type VideoField = Base & { type: "video"; required?: boolean; minFrame?: boolean };
export type CatalogField = Base & { type: "catalog"; catalog: Exclude<CatalogKind, "influencer">; required?: boolean };
export type CharacterField = Base & { type: "character" };
export type OptionsField = Base & { type: "options" };

export type FieldSpec =
  | TextField
  | EnumField
  | IntField
  | BoolField
  | ImageField
  | ImagesField
  | VideoField
  | CatalogField
  | CharacterField
  | OptionsField;

export type ToolForm = {
  fields: FieldSpec[];
  /** галочка «У меня есть права на изображение человека» (поле consent сервера) */
  consent: boolean;
};

/* ------------------------------------------------------------------ */
/* Общие наборы                                                        */
/* ------------------------------------------------------------------ */

const RES_VIDEO = ["480p", "720p", "1080p"] as const;
const IMAGE_ASPECTS = ["1:1", "3:4", "4:3", "9:16", "16:9", "2:3", "3:2"] as const;
const AD_ASPECTS = ["auto", "1:1", "3:2", "2:3", "4:3", "3:4", "16:9", "9:16"] as const;

const resolutionVideo: EnumField = { name: "resolution", type: "enum", label: "form.label.resolution", choices: RES_VIDEO, default: "480p", ui: "chips" };

/** 1, 2, 4, 5: видео-исходник + фото + подсказка + разрешение. */
function videoWithPhoto(kind: "motion" | "swap"): ToolForm {
  return {
    consent: true,
    fields: [
      kind === "motion"
        ? { name: "video", type: "video", required: true, label: "form.label.video_motion", hint: "form.hint.video" }
        : { name: "video", type: "video", required: true, minFrame: true, label: "form.label.video", hint: "form.hint.video_frame" },
      kind === "motion"
        ? { name: "image", type: "image", required: true, label: "form.label.character_photo", hint: "form.hint.character_photo" }
        : { name: "image", type: "image", required: true, label: "form.label.object_photo", hint: "form.hint.object_photo" },
      kind === "motion"
        ? { name: "prompt", type: "text", max: 1000, rows: 2, label: "form.label.prompt_optional", placeholder: "form.ph.motion" }
        : { name: "prompt", type: "text", required: true, max: 1000, rows: 2, label: "form.label.swap_prompt", placeholder: "form.ph.swap" },
      resolutionVideo,
    ],
  };
}

/** 12, 13, 14: описание, фото товара, пресет, качество, разрешение, формат. */
function marketing(): ToolForm {
  return {
    consent: false,
    fields: [
      { name: "prompt", type: "text", required: true, max: 2000, rows: 4, label: "form.label.prompt", placeholder: "form.ph.marketing" },
      { name: "product_images", type: "images", min: 0, max: 8, label: "form.label.product_photos", hint: "form.hint.product_preset" },
      { name: "preset", type: "catalog", catalog: "ms-presets", label: "form.label.preset" },
      { name: "quality", type: "enum", label: "form.label.quality", choices: ["low", "medium", "high"], default: "medium", opt: "quality", ui: "chips" },
      { name: "resolution", type: "enum", label: "form.label.resolution", choices: ["1k", "2k"], default: "1k", opt: "resolution", ui: "chips" },
      { name: "aspect", type: "enum", label: "form.label.aspect", choices: AD_ASPECTS, default: "auto", opt: "aspect", ui: "chips" },
    ],
  };
}

/* ------------------------------------------------------------------ */
/* Реестр форм (id — как в tools.ts и на сервере)                      */
/* ------------------------------------------------------------------ */

export const TOOL_FORMS: Record<string, ToolForm> = {
  "motion-transfer": videoWithPhoto("motion"),
  "object-swap": videoWithPhoto("swap"),
  restyle: {
    consent: true,
    fields: [
      { name: "video", type: "video", required: true, label: "form.label.video", hint: "form.hint.video" },
      { name: "style", type: "catalog", catalog: "restyle", required: true, label: "form.label.style" },
      { name: "images", type: "images", min: 0, max: 5, label: "form.label.people_photos", hint: "form.hint.people_photos" },
      { name: "prompt", type: "text", max: 1000, rows: 2, label: "form.label.prompt_optional", placeholder: "form.ph.restyle" },
      resolutionVideo,
    ],
  },
  "character-motion": videoWithPhoto("motion"),
  "item-swap": videoWithPhoto("swap"),
  "ad-creative": {
    consent: false,
    fields: [
      { name: "prompt", type: "text", required: true, max: 2000, rows: 4, label: "form.label.brief", placeholder: "form.ph.brief" },
      { name: "product_images", type: "images", min: 0, max: 4, label: "form.label.product_photos", hint: "form.hint.image" },
      { name: "count", type: "int", label: "form.label.count", default: 1, choices: [1, 2, 3, 4], ui: "chips" },
      { name: "aspect", type: "enum", label: "form.label.aspect", choices: ["1:1", "4:5", "9:16", "16:9", "3:4", "4:3"], default: "1:1", ui: "chips" },
      { name: "language", type: "enum", label: "form.label.language", choices: ["ru", "en", "ky"], default: "ru", opt: "language", ui: "chips" },
      { name: "niche", type: "text", max: 200, rows: 1, label: "form.label.niche", placeholder: "form.ph.niche", advanced: true },
      { name: "audience", type: "text", max: 300, rows: 1, label: "form.label.audience", placeholder: "form.ph.audience", advanced: true },
    ],
  },
  "photo-restyle": {
    consent: true,
    fields: [
      { name: "image", type: "image", required: true, label: "form.label.photo", hint: "form.hint.image" },
      { name: "prompt", type: "text", required: true, max: 2000, rows: 3, label: "form.label.photo_prompt", placeholder: "form.ph.photo" },
      { name: "quality", type: "enum", label: "form.label.quality", choices: ["low", "medium"], default: "medium", opt: "quality", ui: "chips" },
      { name: "resolution", type: "enum", label: "form.label.resolution", choices: ["1k", "2k"], default: "1k", opt: "resolution", ui: "chips" },
      { name: "aspect", type: "enum", label: "form.label.aspect", choices: ["auto", "1:1", "3:4", "4:3", "9:16", "16:9"], default: "auto", opt: "aspect", ui: "chips" },
    ],
  },
  "text-to-image": {
    consent: false,
    fields: [
      { name: "prompt", type: "text", required: true, max: 1500, rows: 4, label: "form.label.prompt", placeholder: "form.ph.image" },
      { name: "character", type: "character", label: "form.label.character", hint: "form.hint.character" },
      { name: "style", type: "catalog", catalog: "styles-v2", label: "form.label.style" },
      { name: "aspect", type: "enum", label: "form.label.aspect", choices: IMAGE_ASPECTS, default: "1:1", ui: "chips" },
      { name: "resolution", type: "enum", label: "form.label.resolution", choices: ["720p", "1080p"], default: "720p", ui: "chips" },
      { name: "count", type: "int", label: "form.label.count", default: 1, choices: [1, 4], ui: "chips" },
    ],
  },
  "virtual-blogger": {
    consent: false,
    fields: [
      { name: "options", type: "options", label: "form.label.options", hint: "form.hint.options" },
      { name: "brief", type: "text", max: 1000, rows: 3, label: "form.label.blogger_brief", placeholder: "form.ph.blogger" },
    ],
  },
  "consistent-character": {
    consent: true,
    fields: [
      { name: "name", type: "text", required: true, max: 60, rows: 1, label: "form.label.character_name", placeholder: "form.ph.character_name" },
      { name: "photos", type: "images", min: 3, max: 20, label: "form.label.character_photos", hint: "form.hint.character_photos" },
    ],
  },
  portrait: {
    consent: false,
    fields: [
      { name: "prompt", type: "text", required: true, max: 1500, rows: 4, label: "form.label.prompt", placeholder: "form.ph.portrait" },
      { name: "style", type: "catalog", catalog: "styles-v1", label: "form.label.style" },
      { name: "aspect", type: "enum", label: "form.label.aspect", choices: IMAGE_ASPECTS, default: "3:4", ui: "chips" },
      { name: "resolution", type: "enum", label: "form.label.resolution", choices: ["720p", "1080p"], default: "720p", ui: "chips" },
      { name: "count", type: "int", label: "form.label.count", default: 1, choices: [1, 4], ui: "chips" },
    ],
  },
  "ad-campaign": marketing(),
  "ad-poster": marketing(),
  "product-ad": marketing(),
  "script-to-video": {
    consent: false,
    fields: [
      { name: "prompt", type: "text", required: true, max: 2000, rows: 5, label: "form.label.script", placeholder: "form.ph.script" },
      { name: "duration", type: "int", label: "form.label.duration", default: 5, min: 4, max: 15, ui: "range", unit: "form.unit.seconds" },
      { name: "resolution", type: "enum", label: "form.label.resolution", choices: ["480p", "720p"], default: "720p", ui: "chips" },
      { name: "aspect", type: "enum", label: "form.label.aspect", choices: ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"], default: "16:9", ui: "chips" },
      { name: "audio", type: "bool", label: "form.label.audio", hint: "form.hint.audio", default: true },
      { name: "images", type: "images", min: 0, max: 4, label: "form.label.refs", hint: "form.hint.refs", advanced: true },
      { name: "genre", type: "enum", label: "form.label.genre", choices: ["auto", "epic", "drama", "noir", "comedy", "horror", "action"], opt: "genre", ui: "select", advanced: true },
      { name: "era", type: "enum", label: "form.label.era", choices: ["auto", "1960s", "1980s", "1990s", "2000s", "2020s"], opt: "era", ui: "select", advanced: true },
      { name: "light", type: "enum", label: "form.label.light", choices: ["auto", "silhouette", "practicals", "window", "overhead-fall", "contre-jour", "soft-cross"], opt: "light", ui: "select", advanced: true },
      { name: "pacing", type: "enum", label: "form.label.pacing", choices: ["auto", "chaotic", "dynamic", "calm", "single-shot"], opt: "pacing", ui: "select", advanced: true },
      {
        name: "camera_movement",
        type: "enum",
        label: "form.label.camera",
        opt: "camera",
        ui: "select",
        advanced: true,
        choices: [
          "auto", "static-shot", "handheld", "tracking", "side-tracking", "dolly-in", "dolly-out", "dolly-zoom",
          "slow-zoom-in", "slow-zoom-out", "crush-zoom", "pan-left", "pan-right", "whip-pan", "tilt-up", "tilt-down",
          "truck-left", "truck-right", "slider-left", "slider-right", "arc-left", "arc-right", "crane-up", "crane-down",
          "pedestal-up", "pedestal-down", "drone-orbit", "aerial-pullback", "helicopter-shot", "pov", "snorricam",
          "robot-arm", "rack-focus", "bullet-time",
        ],
      },
    ],
  },
};

export const formFor = (toolId: string): ToolForm | undefined => TOOL_FORMS[toolId];

/** Инструменты с пресетом и фото товара: с пресетом нужно 1–2 фото (registry.MS_PRESET_IMAGES). */
export const PRESET_IMAGE_TOOLS = ["ad-campaign", "ad-poster", "product-ad"];
export const PRESET_IMAGES = { min: 1, max: 2 } as const;

/* ------------------------------------------------------------------ */
/* Значения формы                                                      */
/* ------------------------------------------------------------------ */

/** Что держит форма: загрузки — uid, influencer — {категория: [ключи]}. */
export type FormValue = string | number | boolean | string[] | Record<string, string[]> | null;
export type FormValues = Record<string, FormValue>;

/** Язык текста на рекламных картинках по языку сайта (kg → ky). */
export function siteAdLanguage(lang: string | null | undefined): string {
  const code = String(lang || "ru").toLowerCase().slice(0, 2);
  if (code === "en") return "en";
  if (code === "kg" || code === "ky") return "ky";
  return "ru";
}

export function initialValues(form: ToolForm, lang?: string): FormValues {
  const out: FormValues = {};
  for (const f of form.fields) {
    if (f.type === "enum") out[f.name] = f.name === "language" ? siteAdLanguage(lang) : (f.default ?? "auto");
    else if (f.type === "int") out[f.name] = f.default;
    else if (f.type === "bool") out[f.name] = f.default;
    else if (f.type === "images") out[f.name] = [];
    else if (f.type === "options") out[f.name] = {};
    else out[f.name] = "";
  }
  if (form.consent) out.consent = false;
  return out;
}

/**
 * Тело params для quote/run: пустое не шлём, «авто» без значения по умолчанию —
 * тоже (сервер сам выберет), лишних полей не бывает.
 */
export function buildParams(form: ToolForm, values: FormValues): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of form.fields) {
    const v = values[f.name];
    switch (f.type) {
      case "text":
        if (typeof v === "string" && v.trim()) out[f.name] = v.trim();
        break;
      case "enum":
        if (typeof v === "string" && v && !(v === "auto" && f.default === undefined)) out[f.name] = v;
        break;
      case "int":
        if (typeof v === "number" && Number.isFinite(v)) out[f.name] = v;
        break;
      case "bool":
        out[f.name] = v === true;
        break;
      case "images":
        if (Array.isArray(v) && v.length) out[f.name] = v;
        break;
      case "options":
        if (v && typeof v === "object" && !Array.isArray(v)) {
          const sel: Record<string, string[]> = {};
          for (const [k, list] of Object.entries(v)) if (Array.isArray(list) && list.length) sel[k] = list;
          if (Object.keys(sel).length) out[f.name] = sel;
        }
        break;
      default:
        if (typeof v === "string" && v) out[f.name] = v;
    }
  }
  if (form.consent) out.consent = values.consent === true;
  return out;
}

/** Каких обязательных полей не хватает (до запроса цены). Имена полей. */
export function missingFields(toolId: string, form: ToolForm, values: FormValues): string[] {
  const miss: string[] = [];
  for (const f of form.fields) {
    const v = values[f.name];
    if ((f.type === "text" || f.type === "image" || f.type === "video" || f.type === "catalog") && f.required) {
      if (typeof v !== "string" || !v.trim()) miss.push(f.name);
    } else if (f.type === "images") {
      const n = Array.isArray(v) ? v.length : 0;
      let min = f.min;
      if (PRESET_IMAGE_TOOLS.includes(toolId) && f.name === "product_images" && values.preset) min = PRESET_IMAGES.min;
      if (n < min) miss.push(f.name);
    }
  }
  if (form.consent && values.consent !== true) miss.push("consent");
  return miss;
}

/** Сколько фото можно в поле images сейчас (с пресетом — не больше двух). */
export function imagesMax(toolId: string, f: ImagesField, values: FormValues): number {
  if (PRESET_IMAGE_TOOLS.includes(toolId) && f.name === "product_images" && values.preset) return PRESET_IMAGES.max;
  return f.max;
}

/** Стабильный ключ тела: цена годна для запуска, только если ключ совпал. */
export function paramsKey(params: Record<string, unknown>): string {
  const sort = (v: unknown): unknown => {
    if (Array.isArray(v)) return v.map(sort);
    if (v && typeof v === "object") {
      return Object.fromEntries(Object.keys(v as Record<string, unknown>).sort().map((k) => [k, sort((v as Record<string, unknown>)[k])]));
    }
    return v;
  };
  return JSON.stringify(sort(params));
}

/**
 * Значения из params_public прошлой работы → форма («Повторить» из «Моих работ»).
 * Загрузки не переносим: превью у формы нет, а файлы живут неделю — человек
 * выберет их заново.
 */
export function valuesFromParams(form: ToolForm, params: Record<string, unknown>, lang?: string): FormValues {
  const out = initialValues(form, lang);
  for (const f of form.fields) {
    const v = params[f.name];
    if (v === undefined || v === null) continue;
    if (f.type === "image" || f.type === "images" || f.type === "video") continue;
    if (f.type === "options" && typeof v === "object" && !Array.isArray(v)) out[f.name] = v as Record<string, string[]>;
    else if (f.type === "int" && typeof v === "number") out[f.name] = v;
    else if (f.type === "bool" && typeof v === "boolean") out[f.name] = v;
    else if (typeof v === "string") out[f.name] = v;
  }
  return out;
}

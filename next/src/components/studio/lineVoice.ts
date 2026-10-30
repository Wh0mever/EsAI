/**
 * Голос героя на карточке сцены: чистая логика без React и сети.
 *
 * Сколько стоит голос, чем он звучит и можно ли озвучить — решает сервер
 * (core/cartoon/views_audio.SceneLineView). Здесь только то, что показать человеку:
 * какое из состояний карточки сейчас, что нажимается в окне голоса и какой текст отказа.
 * Контракт: vstudio2-notes/scratch/F30/contract_voice.md.
 *
 * Модуль чистый: его проверяет node-тест lineVoice.test.mjs.
 */

/** Голос, закреплённый за героем на весь мультфильм (project.hero_voices). */
export type HeroVoice = { voice_id: string; voice_name: string };
/** Ключ — id героя строкой. */
export type HeroVoices = Record<string, HeroVoice>;

/** Чей голос звучит в сцене вместо голоса модели (scene.line_voice). */
export type LineVoice = {
  voice_id: string;
  voice_name: string;
  track_id: number;
  credits: number;
  start_sec: number;
  /** Какие слова озвучены. */
  text?: string;
  /** Реплику поправили после озвучки: звучат прежние слова. */
  stale?: boolean;
};

type LineScene = {
  status: string;
  dialogue?: string;
  dialogue_is_speech?: boolean;
  line_voice?: LineVoice | null;
  line_voice_price?: number | null;
  character?: { id: number } | null;
};

export type LineVoiceView =
  | { kind: "none" }
  /** Режиссёр решил «описание»: спокойная подсказка, денег и кнопок нет. */
  | { kind: "description" }
  | {
      kind: "voice";
      /** Голос в строке «Голос: Имя ▶»; null — ещё не выбран, подберём сами. */
      voice: { id: string; name: string } | null;
      /** Есть «Сменить» (или «Выбрать», пока голоса нет). */
      canChange: boolean;
      /** Цена кнопки «Озвучить голосом героя»; null — кнопки нет. */
      dubPrice: number | null;
      /** Есть «Вернуть голос модели». */
      canRestore: boolean;
      /** Слова поправили или убрали, а звучит прежняя озвучка. */
      stale: boolean;
    };

/** «Bella - Professional, Bright, Warm» → «Bella». */
export function shortVoiceName(name: string | null | undefined): string {
  const full = String(name ?? "");
  return full.split(" - ")[0].trim() || full.trim();
}

/** Голос героя этой сцены из project.hero_voices. */
export function heroVoiceOf(voices: HeroVoices | null | undefined, scene: Pick<LineScene, "character">): HeroVoice | null {
  const hero = scene.character?.id;
  return (hero != null && voices?.[String(hero)]) || null;
}

/**
 * Что показать под полем реплики. Порядок проверок — из контракта: дорожку смотрим
 * раньше dialogue_is_speech, потому что возможны оба сразу (озвучили вручную, а при
 * пересъёмке режиссёр решил «описание»). Озвучка и смена голоса — только у готовой
 * сцены: иначе сервер ответит scene_not_ready.
 */
export function lineVoiceView(scene: LineScene, heroVoices?: HeroVoices | null): LineVoiceView {
  const dialogue = (scene.dialogue || "").trim();
  const ready = scene.status === "ready";
  const price = typeof scene.line_voice_price === "number" ? scene.line_voice_price : null;
  const line = scene.line_voice ?? null;

  if (line) {
    // Реплику стёрли, а дорожка осталась: в ролике всё ещё звучат прежние слова — поэтому
    // это тоже «устарело», а не «ничего»: иначе убрать голос можно было бы только из окна звука.
    if (line.stale || !dialogue) {
      return { kind: "voice", voice: null, canChange: false, dubPrice: ready && dialogue ? price : null, canRestore: true, stale: true };
    }
    return {
      kind: "voice",
      voice: { id: line.voice_id, name: shortVoiceName(line.voice_name) },
      canChange: ready && price != null,
      dubPrice: null,
      canRestore: true,
      stale: false,
    };
  }

  if (!dialogue) return { kind: "none" };
  if (scene.dialogue_is_speech === false) return { kind: "description" };
  // Цены нет — режим выключен, не для этого человека или нет ключа: ничего нового.
  if (price == null) return { kind: "none" };

  const hero = heroVoiceOf(heroVoices, scene);
  const voice = hero ? { id: hero.voice_id, name: shortVoiceName(hero.voice_name) } : null;
  const canChange = Boolean(scene.character);
  if (ready) return { kind: "voice", voice, canChange, dubPrice: price, canRestore: false, stale: false };
  // До съёмки: голос можно выбрать заранее и бесплатно. Снимается сцена — поля реплики нет.
  if (scene.status === "draft" || scene.status === "failed") {
    return canChange
      ? { kind: "voice", voice, canChange, dubPrice: null, canRestore: false, stale: false }
      : { kind: "none" };
  }
  return { kind: "none" };
}

/**
 * Что делает окно голоса: у готовой сцены — озвучивает её за деньги (и голос закрепляется
 * за героем), до съёмки — только закрепляет голос за героем, бесплатно.
 */
export function voiceDialogMode(scene: Pick<LineScene, "status">): "dub" | "pin" {
  return scene.status === "ready" ? "dub" : "pin";
}

/** Какой голос отмечен при открытии окна: тот, что звучит, иначе голос героя, иначе ничего. */
export function pickedVoice(scene: LineScene, heroVoices?: HeroVoices | null): string {
  return scene.line_voice?.voice_id || heroVoiceOf(heroVoices, scene)?.voice_id || "";
}

/** Выбор что-то меняет: тот же голос кнопкой не применяем (за него и платить нечего). */
export function voiceChoiceIsNew(scene: LineScene, heroVoices: HeroVoices | null | undefined, voiceId: string): boolean {
  if (!voiceId) return false;
  if (voiceDialogMode(scene) === "dub") {
    const line = scene.line_voice;
    return !line || Boolean(line.stale) || line.voice_id !== voiceId;
  }
  return heroVoiceOf(heroVoices, scene)?.voice_id !== voiceId;
}

type VoicePrices = { voice_per_1k: number; voice_min: number };

/** Цена озвучки текста: та же формула, что audio.voice_price на сервере. Пустой текст — 0. */
export function linePrice(text: string | null | undefined, prices: VoicePrices | null | undefined): number {
  const length = (text || "").trim().length;
  if (!length || !prices) return 0;
  return Math.max(prices.voice_min, Math.ceil((length * prices.voice_per_1k) / 1000));
}

/**
 * Сколько голоса в цене строки гостя. У вошедшего голос уже внутри render_credits,
 * а цены гостя считает клиент, и без этого после входа цена выросла бы молча.
 */
export function guestLineCredits(
  dialogue: string | null | undefined,
  config: { line_voice?: boolean; prices: VoicePrices } | null | undefined,
): number {
  return config?.line_voice ? linePrice(dialogue, config.prices) : 0;
}

export type LineTextKey =
  | "studio_ui.line_err"
  | "studio_ui.line_err_no_dialogue"
  | "studio_ui.line_err_not_speech"
  | "studio_ui.line_err_not_ready"
  | "studio_ui.line_err_off"
  | "studio_ui.line_err_busy"
  | "studio_ui.line_err_voices"
  | "studio_ui.scene_err_busy";

/**
 * Отказ озвучки на языке человека. Тексты сервера только русские (контракт), поэтому
 * по-русски — его текст, для en/kg — свой, по error_code, а у отказов без кода — по статусу.
 */
export function lineRefusal(lang: string, status: number, body: unknown): { key: LineTextKey; detail?: string } {
  const b = body && typeof body === "object" ? (body as { detail?: unknown; error_code?: unknown }) : {};
  const detail = typeof b.detail === "string" ? b.detail.trim() : "";
  const key = lineRefusalKey(status, b.error_code);
  return detail && String(lang || "").toLowerCase().startsWith("ru") ? { key, detail } : { key };
}

function lineRefusalKey(status: number, code: unknown): LineTextKey {
  switch (code) {
    case "no_dialogue":
      return "studio_ui.line_err_no_dialogue";
    case "not_speech":
      return "studio_ui.line_err_not_speech";
    case "scene_not_ready":
      return "studio_ui.line_err_not_ready";
    case "line_voice_off":
      return "studio_ui.line_err_off";
    case "scene_busy":
      return "studio_ui.scene_err_busy";
  }
  if (status === 429) return "studio_ui.line_err_busy";
  if (status === 503) return "studio_ui.line_err_voices";
  return "studio_ui.line_err";
}

/** Перевод отказа плана озвучки: у сервера текст только русский, код — у всех. */
export function emptyPlanKey(code: unknown): string {
  return ["unshot", "working", "descriptions", "voiced"].includes(String(code))
    ? `studio_ui.voiceall_nothing_${code}`
    : "studio_ui.voiceall_nothing";
}

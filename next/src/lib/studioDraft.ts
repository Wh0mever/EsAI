"use client";

/**
 * Лента гостя в студии.
 *
 * Клиент: человек без регистрации выбирает героя и набирает сцены, а
 * регистрацию мы просим, когда он уже увидел результат. У гостя нет аккаунта,
 * поэтому лента живёт в браузере — в базе не появляются тысячи брошенных
 * проектов от случайных посетителей. После входа она уезжает на сервер одним
 * запросом (cartoon/projects/import/) и становится настоящим проектом.
 *
 * Здесь же — память о последнем открытом мультфильме: после оплаты и входа
 * человек должен вернуться именно в него, а не в «какой-нибудь последний».
 */

export type DraftScene = {
  /** Свой ключ сцены: у черновика нет id из базы, а сцены можно двигать. */
  key: string;
  /** 0 — своя сцена по описанию (custom_text). */
  preset_id: number;
  /** Свой герой сцены; null — герой всего мультфильма. */
  character_id: number | null;
  /** Своя сцена: что делает герой, словами человека. */
  custom_text?: string;
  /** Что герой говорит в сцене. */
  dialogue?: string;
  /** Своя длительность сцены, секунды; нет — как у мультфильма. */
  duration?: number;
};

export type StudioDraft = {
  /** Ключ черновика: сервер по нему не заведёт второй такой же проект. */
  id: string;
  character_id: number | null;
  /** Формат будущего мультфильма: 16:9, 9:16 или 1:1. */
  aspect_ratio?: string;
  /** Док: модель, качество и длительность, если гость их выбрал (иначе — по умолчанию). */
  video_model?: string;
  resolution?: string;
  duration?: number;
  scenes: DraftScene[];
  updated_at: number;
};

const DRAFT_KEY = "esai.studio.draft.v1";
const LAST_PROJECT_KEY = "esai.studio.lastProject";
const FREE_TRY_KEY = "esai.studio.freeTryUsed";

/** Неделю черновик ждёт. Дальше это уже не «вернулся доделать», а мусор. */
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
export const MAX_DRAFT_SCENES = 30;
const ASPECTS = ["16:9", "9:16", "1:1"];
/** Предел длительности на сервере (cartoon/pricing.MAX_DURATION). */
const MAX_SECONDS = 60;

// Черновик лежит в браузере и мог устареть или испортиться: что не похоже на
// настройку — выбрасываем, сервер всё равно проверит перенос (lenient).
function seconds(v: unknown): number | undefined {
  if (typeof v !== "number" && typeof v !== "string") return undefined;
  const n = Number(v);
  return Number.isInteger(n) && n >= 1 && n <= MAX_SECONDS ? n : undefined;
}

function shortText(v: unknown, max: number): string | undefined {
  if (typeof v !== "string") return undefined;
  const s = v.trim();
  return s && s.length <= max ? s : undefined;
}

function uid(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
  }
}

export function newSceneKey(): string {
  return uid();
}

export function emptyDraft(characterId: number | null): StudioDraft {
  return { id: uid(), character_id: characterId, scenes: [], updated_at: Date.now() };
}

export function loadDraft(): StudioDraft | null {
  try {
    const raw = window.localStorage.getItem(DRAFT_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw) as Partial<StudioDraft>;
    if (!data || typeof data.id !== "string" || !Array.isArray(data.scenes)) return null;
    if (Date.now() - Number(data.updated_at || 0) > MAX_AGE_MS) {
      window.localStorage.removeItem(DRAFT_KEY);
      return null;
    }
    const scenes = data.scenes
      .filter((s): s is DraftScene => Boolean(s) && Number.isFinite(Number((s as DraftScene).preset_id)))
      .map((s) => {
        const duration = seconds(s.duration);
        // Реплика тоже едет при переносе: без неё после перезагрузки она пропадала.
        const dialogue = typeof s.dialogue === "string" ? s.dialogue.trim().slice(0, 300) : "";
        return {
          key: typeof s.key === "string" && s.key ? s.key : uid(),
          preset_id: Number(s.preset_id),
          character_id: s.character_id ? Number(s.character_id) : null,
          ...(typeof s.custom_text === "string" && s.custom_text.trim()
            ? { custom_text: s.custom_text.trim().slice(0, 300) }
            : {}),
          ...(dialogue ? { dialogue } : {}),
          ...(duration ? { duration } : {}),
        };
      })
      .filter((s) => s.preset_id > 0 || Boolean(s.custom_text))
      .slice(0, MAX_DRAFT_SCENES);
    const aspect = typeof data.aspect_ratio === "string" && ASPECTS.includes(data.aspect_ratio)
      ? data.aspect_ratio
      : undefined;
    const videoModel = shortText(data.video_model, 128);
    const resolution = shortText(data.resolution, 8);
    const duration = seconds(data.duration);
    return {
      id: data.id,
      character_id: data.character_id ? Number(data.character_id) : null,
      // Формат и настройки дока переживают перезагрузку — гость их выбрал сам.
      ...(aspect ? { aspect_ratio: aspect } : {}),
      ...(videoModel ? { video_model: videoModel } : {}),
      ...(resolution ? { resolution } : {}),
      ...(duration ? { duration } : {}),
      scenes,
      updated_at: Number(data.updated_at || Date.now()),
    };
  } catch {
    return null;
  }
}

export function saveDraft(draft: StudioDraft): StudioDraft {
  const next = { ...draft, scenes: draft.scenes.slice(0, MAX_DRAFT_SCENES), updated_at: Date.now() };
  try {
    window.localStorage.setItem(DRAFT_KEY, JSON.stringify(next));
  } catch {
    // Приватный режим: лента живёт до перезагрузки страницы — это лучше, чем ничего.
  }
  return next;
}

/** Настройки дока, выбранные гостем: только полной тройкой, иначе null (по умолчанию). */
export function draftDock(
  draft: StudioDraft | null | undefined,
): { video_model: string; resolution: string; duration: number } | null {
  if (!draft?.video_model || !draft.resolution || !draft.duration) return null;
  return { video_model: draft.video_model, resolution: draft.resolution, duration: draft.duration };
}

/**
 * Тело переноса ленты после входа (POST cartoon/projects/import/). Настройки
 * дока едут, только если гость их выбрал: иначе мультфильм получит значения
 * по умолчанию, как любой новый. Сервер принимает перенос мягко — устаревшее
 * подгоняет к модели и сообщает (adjusted), ленту не теряет.
 */
export function importBody(draft: StudioDraft): Record<string, unknown> {
  const dock = draftDock(draft);
  return {
    draft_id: draft.id,
    character_id: draft.character_id,
    aspect_ratio: draft.aspect_ratio || "16:9",
    ...(dock ?? {}),
    scenes: draft.scenes.map((s) => ({
      preset_id: s.preset_id,
      character_id: s.character_id,
      // Своя сцена переезжает вместе с описанием, иначе она пропала бы.
      ...(s.custom_text ? { custom_text: s.custom_text } : {}),
      // Реплика героя тоже едет: её человек уже написал.
      ...(s.dialogue ? { dialogue: s.dialogue } : {}),
      ...(s.duration ? { duration: s.duration } : {}),
    })),
  };
}

export function clearDraft(): void {
  try {
    window.localStorage.removeItem(DRAFT_KEY);
  } catch {}
}

export function rememberProject(id: number): void {
  try {
    window.localStorage.setItem(LAST_PROJECT_KEY, String(id));
  } catch {}
}

export function recallProject(): number {
  try {
    return Number(window.localStorage.getItem(LAST_PROJECT_KEY) || 0) || 0;
  } catch {
    return 0;
  }
}

/** Подпись кнопки «Примерить бесплатно». Решает всё равно сервер — это только текст. */
export function markFreeTryUsed(): void {
  try {
    window.localStorage.setItem(FREE_TRY_KEY, "1");
  } catch {}
}

export function isFreeTryUsed(): boolean {
  try {
    return window.localStorage.getItem(FREE_TRY_KEY) === "1";
  } catch {
    return false;
  }
}

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
};

export type StudioDraft = {
  /** Ключ черновика: сервер по нему не заведёт второй такой же проект. */
  id: string;
  character_id: number | null;
  /** Формат будущего мультфильма: 16:9, 9:16 или 1:1. */
  aspect_ratio?: string;
  scenes: DraftScene[];
  updated_at: number;
};

const DRAFT_KEY = "esai.studio.draft.v1";
const LAST_PROJECT_KEY = "esai.studio.lastProject";
const FREE_TRY_KEY = "esai.studio.freeTryUsed";

/** Неделю черновик ждёт. Дальше это уже не «вернулся доделать», а мусор. */
const MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
export const MAX_DRAFT_SCENES = 30;

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
      .map((s) => ({
        key: typeof s.key === "string" && s.key ? s.key : uid(),
        preset_id: Number(s.preset_id),
        character_id: s.character_id ? Number(s.character_id) : null,
        ...(typeof s.custom_text === "string" && s.custom_text.trim()
          ? { custom_text: s.custom_text.trim().slice(0, 300) }
          : {}),
      }))
      .filter((s) => s.preset_id > 0 || Boolean(s.custom_text))
      .slice(0, MAX_DRAFT_SCENES);
    return {
      id: data.id,
      character_id: data.character_id ? Number(data.character_id) : null,
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

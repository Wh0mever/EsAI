/**
 * Чистая логика чата без React: что именно повторяет «Повторить» и какой
 * ролик из истории считать «тем самым» после обрыва связи. Вынесено из
 * ChatWorkspace, чтобы проверять тестом (chatRetry.test.mjs) — ошибки здесь
 * стоят пользователю денег (лишняя платная генерация).
 */
import type { Message } from "@/types/chat";

/** Сообщение + служебные поля (есть только на клиенте, на сервер не уходят). */
export type LiveMessage = Message & {
  _cid?: string;
  imagePending?: boolean;
  videoPending?: boolean;
  /** Ролик, который продлевали этим вопросом: «Повторить» продлит его же. */
  _extend?: string;
  /** Ошибка после начатой платной генерации — «Повторить» не показываем. */
  noRetry?: boolean;
};

export type RetryPlan = {
  /** Сколько сообщений оставить на экране перед повторной отправкой. */
  keep: number;
  content: string;
  attachments: NonNullable<Message["attachments"]>;
  extend: string | null;
  /** Повторяем «Продолжи.», а не исходный вопрос. */
  isContinue: boolean;
};

/**
 * Что повторить. continueFrom — длина переписки в момент «Продолжить» (null —
 * последним был обычный вопрос): «Продолжить» не добавляет пузыря вопроса,
 * поэтому без этого «Повторить» стирал продолжаемый ответ и заново (и платно)
 * генерировал весь исходный вопрос.
 */
export function planRetry(messages: Message[], continueFrom: number | null, continuePrompt: string): RetryPlan | null {
  // После «Продолжить» что-то пришло (ответ или ошибка) — повторяем продолжение
  // и убираем только то, что появилось после продолжаемого ответа.
  if (continueFrom != null && continueFrom >= 0 && messages.length > continueFrom) {
    return { keep: continueFrom, content: continuePrompt, attachments: [], extend: null, isContinue: true };
  }
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i] as LiveMessage;
    if (m?.role !== "user") continue;
    const content = (m.content || "").trim();
    if (!content) return null;
    return {
      keep: i + 1,
      content,
      attachments: Array.isArray(m.attachments) ? m.attachments : [],
      extend: m._extend || null,
      isContinue: false,
    };
  }
  return null;
}

/**
 * Совпадает ли prompt вложения-ролика с вопросом. Сервер хранит message[:2000]
 * (core/ai/generation.py, recovery.py); вложения без prompt не отсекаем.
 */
function samePrompt(prompt: unknown, content: string): boolean {
  const p = typeof prompt === "string" ? prompt : "";
  if (!p) return true;
  if (p.trim() === content) return true;
  return content.length > 2000 && content.startsWith(p);
}

/**
 * Готовый ролик в истории сессии: ответ ассистента с видео ПОСЛЕ последнего
 * вопроса с этим текстом, снятый по этому же тексту и ещё не показанный.
 * knownIds — id сообщений, уже стоящих на экране (проверяется на каждом опросе):
 * иначе заметку «ещё снимается» подменял ответ на СЛЕДУЮЩИЙ вопрос, опрос
 * прекращался, и настоящий ролик так и не появлялся. Дальше следующих вопросов
 * искать нужно: фоновая задача дописывает запоздавший ролик в конец чата.
 */
export function findNewVideo(history: unknown, content: string, knownIds: string[]): Message | null {
  if (!Array.isArray(history)) return null;
  const known = new Set(knownIds.map(String));
  let start = -1;
  for (let i = history.length - 1; i >= 0; i--) {
    const m = history[i] as Message;
    if (m?.role === "user" && (m.content || "").trim() === content) {
      start = i;
      break;
    }
  }
  if (start < 0) return null;
  for (let i = start + 1; i < history.length; i++) {
    const m = history[i] as Message;
    if (m?.role !== "assistant") continue;
    if (m.id != null && known.has(String(m.id))) continue;
    const atts = Array.isArray(m.attachments) ? m.attachments : [];
    const isOurs = atts.some(
      (a: { type?: string; prompt?: unknown } | null) =>
        String(a?.type || "").toLowerCase() === "video" && samePrompt(a?.prompt, content)
    );
    if (isOurs) return m;
  }
  return null;
}

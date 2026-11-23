/**
 * Ошибки Creative Studio → текст человеку (пространство `creative`).
 *
 * Сервер шлёт {error, error_code, …} (core/creative/errors.py); переводим по
 * error_code, русский текст сервера — только запасной, если кода не знаем.
 * Тексты нейтральные: ни имени поставщика, ни его ответов.
 */
import type { VsError } from "@/lib/vstudio/types";
import type { JobJSON } from "./api";
import type { Ct } from "./text";

/** Ответ сервера и сети: errors.<code>. Варианты *_n — с числом из тела ответа. */
export const CREATIVE_ERROR_RU: Record<string, string> = {
  "errors.bad_request": "Некорректный запрос. Обновите страницу и попробуйте снова.",
  "errors.unauthorized": "Войдите, чтобы продолжить.",
  "errors.creative_disabled": "Creative Studio скоро откроется.",
  "errors.tool_disabled": "Этот инструмент временно недоступен.",
  "errors.tool_not_found": "Инструмент не найден.",
  "errors.job_not_found": "Работа не найдена.",
  "errors.character_not_found": "Персонаж не найден.",
  "errors.catalog_not_found": "Список вариантов не найден.",
  "errors.not_found": "Не найдено.",
  "errors.bad_params": "Проверьте поля формы — часть из них заполнена неверно.",
  "errors.price_changed": "Цена изменилась. Проверьте и нажмите «Создать» ещё раз.",
  "errors.price_changed_n": "Цена изменилась: теперь {{credits}} кр. Проверьте и нажмите «Создать» ещё раз.",
  "errors.price_unavailable": "Цена сейчас недоступна, попробуйте позже.",
  "errors.already_submitted": "Работа уже отправлена в генерацию — отменить её нельзя.",
  "errors.provider_unavailable": "Генерация временно недоступна. Попробуйте через несколько минут — кредиты не списаны.",
  "errors.storage_unavailable": "Сохранение результатов временно недоступно. Попробуйте позже — кредиты не списаны.",
  "errors.catalog_unavailable": "Список вариантов сейчас недоступен, попробуйте через минуту.",
  "errors.throttled": "Слишком много запросов. Подождите немного и попробуйте снова.",
  "errors.insufficient_balance": "Не хватает кредитов. Пополните баланс, чтобы создать.",
  "errors.insufficient_tokens": "Не хватает кредитов. Пополните баланс, чтобы создать.",
  "errors.too_many_open": "Слишком много работ одновременно. Дождитесь, пока одна из них закончится.",
  "errors.too_many_open_n": "Одновременно можно запускать не больше {{limit}} работ. Дождитесь, пока одна из них закончится.",
  "errors.bad_type": "Этот формат не подходит.",
  "errors.bad_type_image": "Этот формат не подходит. Нужен JPG, PNG или WebP.",
  "errors.bad_type_video": "Этот формат не подходит. Нужно видео MP4, MOV или WebM.",
  "errors.too_big": "Файл слишком большой.",
  "errors.too_big_n": "Файл слишком большой — можно до {{max_mb}} МБ.",
  "errors.too_short": "Видео слишком короткое.",
  "errors.too_short_n": "Видео слишком короткое — нужно не меньше {{min_s}} с.",
  "errors.too_long": "Видео слишком длинное.",
  "errors.too_long_n": "Видео слишком длинное — можно до {{max_s}} с.",
  "errors.too_small_frame": "Разрешение видео слишком маленькое — нужен кадр не меньше 854×480.",
  "errors.unreadable": "Файл не читается — возможно, он повреждён.",
  "errors.upload_busy": "Сейчас обрабатывается много файлов — попробуйте через несколько секунд.",
  "errors.upload_quota": "Загружено слишком много файлов. Старые загрузки удаляются через неделю — используйте уже загруженные или попробуйте позже.",
  "errors.too_heavy": "Видео не успело обработаться. Укоротите его или уменьшите разрешение и загрузите снова.",
  "errors.server_error": "Что-то пошло не так. Попробуйте ещё раз.",
  "errors.network": "Нет связи с сервером. Проверьте интернет и попробуйте снова.",
  "errors.bad_response": "Сервер ответил непонятно. Попробуйте ещё раз.",
  "errors.unknown": "Что-то пошло не так. Попробуйте ещё раз.",
};

/** Исход работы: job.<code> (по error_code, иначе по статусу). */
export const CREATIVE_JOB_ERROR_RU: Record<string, string> = {
  "job.provider_failed": "Генерация не получилась. Кредиты не списаны — попробуйте ещё раз.",
  "job.upload_failed": "Не удалось передать файлы в генерацию. Кредиты не списаны — попробуйте ещё раз.",
  "job.nsfw": "Запрос отклонила модерация. Кредиты не списаны.",
  "job.canceled": "Работа отменена. Кредиты не списаны.",
  "job.lost": "Не удалось завершить работу. Кредиты не списаны — попробуйте ещё раз.",
  "job.failed": "Генерация не получилась. Кредиты не списаны — попробуйте ещё раз.",
  "job.provider_unavailable": "Генерация временно недоступна. Кредиты не списаны — попробуйте позже.",
  "job.bad_params": "Не удалось запустить генерацию с этими настройками. Кредиты не списаны.",
  "job.queue_timeout": "Генерация слишком долго ждала очереди. Кредиты не списаны — попробуйте ещё раз.",
  "job.submit_unknown": "Не удалось подтвердить запуск. Кредиты не списаны, мы проверим вручную.",
  "job.provider_timeout": "Результат так и не пришёл. Кредиты не списаны, мы проверим вручную.",
  "job.provider_unreachable": "Не удалось забрать результат. Кредиты не списаны, мы проверим вручную.",
  "job.save_failed": "Не удалось сохранить результат. Кредиты не списаны, мы проверим вручную.",
  "job.journal_unavailable": "Не удалось запустить генерацию. Кредиты не списаны — попробуйте ещё раз.",
  "job.storage_unavailable": "Сохранение временно недоступно. Кредиты не списаны — попробуйте позже.",
  "job.internal_error": "Не удалось запустить генерацию. Кредиты не списаны — попробуйте ещё раз.",
};

/** Ошибка поля (422 bad_params → errors:[{field, code, …}]): ferr.<code>. */
export const CREATIVE_FIELD_ERROR_RU: Record<string, string> = {
  "ferr.required": "Заполните это поле.",
  "ferr.consent_required": "Подтвердите, что у вас есть права на изображение.",
  "ferr.bad_type": "Недопустимое значение.",
  "ferr.bad_value": "Недопустимое значение.",
  "ferr.too_long": "Слишком длинный текст.",
  "ferr.too_long_n": "Не больше {{max}} символов.",
  "ferr.too_long_video": "Видео длиннее {{max_s}} с — загрузите покороче.",
  "ferr.too_short_video": "Видео короче {{min_s}} с — загрузите подлиннее.",
  "ferr.too_small_frame": "Кадр видео меньше 854×480 — нужно видео крупнее.",
  "ferr.out_of_range": "Допустимо от {{min}} до {{max}}.",
  "ferr.too_few": "Нужно не меньше {{min}}.",
  "ferr.too_many": "Можно не больше {{max}}.",
  "ferr.not_found": "Файл не найден — загрузите его заново.",
  "ferr.wrong_kind": "Не тот тип файла.",
  "ferr.character_not_ready": "Этот персонаж ещё не готов.",
  "ferr.catalog_unavailable": "Список вариантов сейчас недоступен, попробуйте через минуту.",
};

const n = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const fmt = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1));

/** Ключ и подстановки для ошибки ответа (с учётом того, что прислал сервер). */
export function errorKey(err: Pick<VsError, "code" | "data">, kind?: "image" | "video"): { key: string; params?: Record<string, string | number> } {
  const d = err.data || {};
  switch (err.code) {
    case "price_changed":
      return n(d.credits) != null ? { key: "errors.price_changed_n", params: { credits: n(d.credits)! } } : { key: "errors.price_changed" };
    case "too_many_open":
      return n(d.limit) != null ? { key: "errors.too_many_open_n", params: { limit: n(d.limit)! } } : { key: "errors.too_many_open" };
    case "too_big":
    case "file_too_large":
      return n(d.max_mb) != null ? { key: "errors.too_big_n", params: { max_mb: n(d.max_mb)! } } : { key: "errors.too_big" };
    case "too_short":
      return n(d.min_s) != null ? { key: "errors.too_short_n", params: { min_s: fmt(n(d.min_s)!) } } : { key: "errors.too_short" };
    case "too_long":
      return n(d.max_s) != null ? { key: "errors.too_long_n", params: { max_s: fmt(n(d.max_s)!) } } : { key: "errors.too_long" };
    case "bad_type":
      return { key: kind === "video" ? "errors.bad_type_video" : kind === "image" ? "errors.bad_type_image" : "errors.bad_type" };
    default:
      return { key: `errors.${err.code}` };
  }
}

/** Текст ошибки ответа. Неизвестный код — русский текст сервера или общий. */
export function errorText(ct: Ct, err: Pick<VsError, "code" | "data" | "message">, kind?: "image" | "video"): string {
  const { key, params } = errorKey(err, kind);
  if (key in CREATIVE_ERROR_RU) return ct(key, params);
  return err.message || ct("errors.unknown");
}

/** Текст ошибки поля из 422 bad_params. */
export function fieldErrorText(ct: Ct, e: Record<string, unknown>): string {
  const code = typeof e.code === "string" ? e.code : "bad_value";
  // Персонаж, а не файл: «не найден» — значит скрыт или чужой.
  if (code === "not_found" && e.field === "character") return ct("errors.character_not_found");
  if (code === "too_long") {
    if (n(e.max_s) != null) return ct("ferr.too_long_video", { max_s: fmt(n(e.max_s)!) });
    if (n(e.max) != null) return ct("ferr.too_long_n", { max: n(e.max)! });
    return ct("ferr.too_long");
  }
  if (code === "too_short") return ct("ferr.too_short_video", { min_s: fmt(n(e.min_s) ?? 4) });
  if (code === "out_of_range") return ct("ferr.out_of_range", { min: n(e.min) ?? "", max: n(e.max) ?? "" });
  if (code === "too_few") return ct("ferr.too_few", { min: n(e.min) ?? 1 });
  if (code === "too_many") return ct("ferr.too_many", { max: n(e.max) ?? 1 });
  const key = `ferr.${code}`;
  return key in CREATIVE_FIELD_ERROR_RU ? ct(key) : ct("ferr.bad_value");
}

/** Ошибки полей из тела 422: {имя поля: текст} (первая ошибка на поле). */
export function fieldErrors(ct: Ct, err: Pick<VsError, "code" | "data">): Record<string, string> {
  const out: Record<string, string> = {};
  const list = Array.isArray(err.data?.errors) ? err.data.errors : [];
  for (const e of list) {
    if (!e || typeof e !== "object") continue;
    const rec = e as Record<string, unknown>;
    const field = typeof rec.field === "string" ? rec.field : "";
    if (field && !out[field]) out[field] = fieldErrorText(ct, rec);
  }
  return out;
}

/** Почему работа не получилась. */
export function jobErrorText(ct: Ct, job: Pick<JobJSON, "status" | "error_code">): string {
  const byCode = job.error_code ? `job.${job.error_code}` : "";
  if (byCode && byCode in CREATIVE_JOB_ERROR_RU) return ct(byCode);
  const byStatus = `job.${job.status}`;
  return byStatus in CREATIVE_JOB_ERROR_RU ? ct(byStatus) : ct("job.failed");
}

export const ALL_ERROR_RU: Record<string, string> = { ...CREATIVE_ERROR_RU, ...CREATIVE_JOB_ERROR_RU, ...CREATIVE_FIELD_ERROR_RU };

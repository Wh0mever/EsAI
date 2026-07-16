/**
 * vendorColors — единый источник брендовых цветов AI-вендоров для всего
 * проекта (текстовые wordmark-чипы/точки в HomeHero, PopularModels,
 * pricing/CreditsExplainer, каталог моделей /models и где угодно ещё).
 * Раньше каждый компонент держал свою локальную копию этой карты — из-за
 * этого FLUX/Kling получили разные цвета в разных блоках главной страницы.
 * Теперь один модуль, один цвет на вендора.
 *
 * Расширено для /models (каталог AI-моделей, Этап 4): помимо 7 исходных
 * вендоров (openai/anthropic/google/deepseek/x-ai/perplexity/mistralai)
 * добавлены ещё 11 префиксов openrouter_id, встречающихся среди активных
 * GPTModels (meta-llama/qwen/moonshotai/z-ai/minimax/nvidia/amazon —
 * совпадают с локальным словарём PROVIDERS в chat/ModelSelector.tsx —
 * плюс kwaivgi/black-forest-labs/bytedance/alibaba, которых не было даже
 * там). Без этого расширения ~38% карточек каталога получили бы серый
 * DEFAULT_VENDOR_COLOR вместо брендового цвета.
 *
 * "flux"/"kling" — старые самостоятельные ключи (используются напрямую,
 * не через openrouter_id, в HomeHero/PopularModels чипах, у которых нет
 * соответствующей записи в ai/models/) — оставлены как есть для обратной
 * совместимости. "black-forest-labs"/"kwaivgi" — их openrouter-vendor-эквиваленты
 * с теми же цветами, чтобы vendorColorByOpenRouterId() резолвил их верно.
 */

export const VENDOR_COLORS: Record<string, string> = {
  openai: "#10a37f",
  anthropic: "#d97757",
  google: "#4285f4",
  deepseek: "#4d6bfe",
  "x-ai": "#9ca3af",
  perplexity: "#20b8cd",
  mistralai: "#fa520f",
  "meta-llama": "#0668e1",
  qwen: "#615ced",
  moonshotai: "#1fb6ad",
  "z-ai": "#3859ff",
  minimax: "#f23f5d",
  nvidia: "#76b900",
  amazon: "#ff9900",
  bytedance: "#25f4ee",
  alibaba: "#ff6a00",
  // Не входят в openrouter-каталог ai/models/ (отдельные image/video-провайдеры),
  // поэтому цвета не привязаны к openrouter_id — заведены как самостоятельные ключи.
  flux: "#f97316",
  kling: "#6366f1",
  // openrouter-vendor-эквиваленты FLUX/Kling (совпадают цветом с "flux"/"kling" выше).
  "black-forest-labs": "#f97316",
  kwaivgi: "#6366f1",
};

export const DEFAULT_VENDOR_COLOR = "#9ca3af";

/** Отображаемое имя вендора (для инициала в логотипо-подобных бейджах каталога). */
export const VENDOR_LABELS: Record<string, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  google: "Google",
  deepseek: "DeepSeek",
  "x-ai": "xAI",
  perplexity: "Perplexity",
  mistralai: "Mistral",
  "meta-llama": "Meta",
  qwen: "Qwen",
  moonshotai: "Moonshot",
  "z-ai": "Z.AI",
  minimax: "MiniMax",
  nvidia: "NVIDIA",
  amazon: "Amazon",
  bytedance: "ByteDance",
  alibaba: "Alibaba",
  "black-forest-labs": "FLUX",
  kwaivgi: "Kling",
  flux: "FLUX",
  kling: "Kling",
};

/** Цвет по openrouter_id вида "vendor/model-name" (используется в CreditsExplainer). */
export function vendorColorByOpenRouterId(openrouterId?: string): string {
  const vendor = (openrouterId || "").toLowerCase().split("/")[0];
  return VENDOR_COLORS[vendor] || DEFAULT_VENDOR_COLOR;
}

/** Цвет по прямому ключу вендора (используется в HomeHero/PopularModels чипах). */
export function vendorColor(vendorKey: string): string {
  return VENDOR_COLORS[vendorKey] || DEFAULT_VENDOR_COLOR;
}

/** Имя вендора по openrouter_id; неизвестный префикс — сам префикс с большой буквы. */
export function vendorLabelByOpenRouterId(openrouterId?: string): string {
  const vendor = (openrouterId || "").toLowerCase().split("/")[0];
  if (VENDOR_LABELS[vendor]) return VENDOR_LABELS[vendor];
  return vendor ? vendor.charAt(0).toUpperCase() + vendor.slice(1) : "?";
}

/** Заглавная буква вендора по openrouter_id — инициал для круглого бейджа-логотипа. */
export function vendorInitialByOpenRouterId(openrouterId?: string): string {
  return vendorLabelByOpenRouterId(openrouterId).charAt(0).toUpperCase() || "?";
}

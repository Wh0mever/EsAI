/**
 * Примеры для пустой студии (§9.6): 3–4 карточки, клик кладёт текст в
 * композер. Тексты переводятся ключами `empty.examples.<id>.title|prompt`
 * (ns vstudio), русский здесь — defaultValue.
 *
 * Примеры короткие намеренно: одна сцена, «субъект → действие → место →
 * камера → свет». Это тот же порядок, что просит «Сжать с ИИ», и он же
 * лучше всего понятен Seedance — пусть человек с первого клика видит, как
 * писать, а не вставляет сценарий на 3000 символов.
 */
import type { PromptDoc, ShotParams, VsKind } from "@/lib/vstudio/types";

export type VsExampleId = "rooftop_cat" | "morning_coffee" | "mountain_flight" | "yurt_poster";

export type VsExample = {
  id: VsExampleId;
  kind: VsKind;
  /** Заголовок карточки (ru по умолчанию). */
  title: string;
  /** Текст, который попадёт в композер (ru по умолчанию). */
  prompt: string;
  /** Только пропорции: длительность и качество остаются теми, что выбраны у модели. */
  params: Pick<ShotParams, "aspect_ratio">;
};

export const VS_EXAMPLES: readonly VsExample[] = [
  {
    id: "rooftop_cat",
    kind: "video",
    title: "Кот на крыше",
    prompt:
      "Рыжий кот в круглых очках не спеша идёт по краю крыши на закате. Камера плавно едет рядом, тёплый золотой свет, ветер шевелит шерсть.",
    params: { aspect_ratio: "16:9" },
  },
  {
    id: "morning_coffee",
    kind: "video",
    title: "Утренний кофе",
    prompt:
      "Крупный план: чашка горячего кофе на подоконнике, над ней поднимается пар, за стеклом идёт дождь. Мягкий утренний свет, медленный наезд камеры.",
    params: { aspect_ratio: "9:16" },
  },
  {
    id: "mountain_flight",
    kind: "video",
    title: "Полёт над горами",
    prompt:
      "Дрон медленно пролетает над заснеженными горами Ала-Тоо к бирюзовому озеру на рассвете. Облака внизу, лёгкая дымка, широкий план.",
    params: { aspect_ratio: "16:9" },
  },
  {
    id: "yurt_poster",
    kind: "image",
    title: "Постер акварелью",
    prompt:
      "Акварельный постер: юрта в горах под звёздным небом, из двери льётся тёплый свет, рядом пасётся конь. Мягкие переходы цвета, много воздуха.",
    params: { aspect_ratio: "3:4" },
  },
];

/** Текст → prompt_doc v1: каждая строка — абзац, пустые строки сохраняются. */
export function exampleDoc(text: string): PromptDoc {
  const lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
  return { v: 1, blocks: lines.map((line) => (line ? [{ t: "text" as const, v: line }] : [])) };
}

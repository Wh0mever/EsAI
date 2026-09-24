import type { TFunction } from "i18next";

/**
 * Пропорции кадра: подписи, значок и наглядный прямоугольник.
 *
 * Раньше жили в chat/VideoParamsPanel.tsx; вынесены сюда, чтобы видеостудия
 * (components/vstudio/settings/AspectPicker) не тянула за собой панель чата.
 * VideoParamsPanel реэкспортирует IconAspect, ASPECT_HINT и aspectHint —
 * старые импорты продолжают работать.
 */

/** Подписи к пропорциям — чтобы не гадать, где вертикаль, а где широкий кадр.
 *  Русский текст — defaultValue; перевод по ключу chat.aspect_<w>_<h>. */
export const ASPECT_HINT: Record<string, string> = {
  "16:9": "Горизонтальное — YouTube, презентации",
  "9:16": "Вертикальное — сторис, Reels, TikTok",
  "1:1": "Квадрат — лента, аватар",
  "4:3": "Классическое горизонтальное",
  "3:4": "Классическое вертикальное",
  "3:2": "Как фотография",
  "2:3": "Как фотография, вертикально",
  "4:5": "Вертикальное для ленты",
  "21:9": "Кинематографичное, очень широкое",
  "9:21": "Очень узкое вертикальное",
};

/**
 * Переведённая подпись к пропорции (или сама пропорция, если подписи нет).
 * ns "common" задан явно: ключи chat.aspect_* лежат в common.json, а видеостудия
 * вызывает функцию со своим t из namespace "vstudio".
 */
export function aspectHint(t: TFunction, ratio: string): string {
  const ru = ASPECT_HINT[ratio];
  if (!ru) return ratio;
  return t(`chat.aspect_${ratio.replace(":", "_")}`, { ns: "common", defaultValue: ru });
}

export function IconAspect({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
      strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M8 5v14" />
    </svg>
  );
}

/** «9:16» → 0.5625 (ширина / высота); мусор → null. */
export function aspectValue(ratio: string | null | undefined): number | null {
  const m = /^\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\s*$/.exec(String(ratio ?? ""));
  if (!m) return null;
  const w = Number(m[1]);
  const h = Number(m[2]);
  return w > 0 && h > 0 ? w / h : null;
}

/**
 * Размер прямоугольника пропорции внутри квадрата max×max: длинная сторона
 * занимает весь квадрат. Очень вытянутые (21:9) не сплющиваются в линию —
 * короткая сторона не меньше трети.
 */
export function aspectBox(ratio: string, max = 20): { w: number; h: number } {
  const v = aspectValue(ratio);
  if (!v) return { w: max, h: max };
  const min = Math.max(4, Math.round(max / 3));
  if (v >= 1) return { w: max, h: Math.max(min, Math.round(max / v)) };
  return { w: Math.max(min, Math.round(max * v)), h: max };
}

/**
 * Наглядный прямоугольник пропорции — «▯ 9:16» вместо голых цифр.
 * ratio="auto" — пунктирный квадрат: «модель решит сама».
 */
export function AspectShape({
  ratio,
  size = 20,
  className = "",
}: {
  ratio: string;
  size?: number;
  className?: string;
}) {
  const auto = ratio === "auto";
  const { w, h } = auto ? { w: size - 4, h: size - 4 } : aspectBox(ratio, size);
  const x = (size - w) / 2;
  const y = (size - h) / 2;
  return (
    <svg
      viewBox={`0 0 ${size} ${size}`}
      width={size}
      height={size}
      className={className}
      aria-hidden
    >
      <rect
        x={x + 0.75}
        y={y + 0.75}
        width={Math.max(1, w - 1.5)}
        height={Math.max(1, h - 1.5)}
        rx={2}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeDasharray={auto ? "2.5 2" : undefined}
      />
      {auto && (
        <path
          d={`M${size / 2 - 3} ${size / 2 + 2.5} L${size / 2} ${size / 2 - 3} L${size / 2 + 3} ${size / 2 + 2.5}`}
          fill="none"
          stroke="currentColor"
          strokeWidth={1.4}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      )}
    </svg>
  );
}

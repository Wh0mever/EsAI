"use client";

import { useState } from "react";
import { bankIconSources } from "@/lib/qrpay";

/**
 * Значок банка — как значок приложения на телефоне: человек ищет глазами
 * знакомую картинку, а не читает подпись.
 *
 * Откуда картинка, по порядку: наш файл (public/images/banks) → адрес от
 * сервера (банк, которого у нас ещё нет) → первая буква названия. Каждая
 * ступень — запасная для предыдущей: если файл не загрузился, пробуем
 * следующий источник, и только в конце рисуем букву.
 */
type Props = {
  code: string;
  name?: string;
  /** https-адрес значка от сервера; у банков с нашим файлом не нужен */
  icon?: string;
  /** сторона в пикселях; не задана — значок занимает всю обёртку */
  size?: number;
  /** подпись для экранного диктора; пусто — значок декоративный (название рядом) */
  alt?: string;
  className?: string;
};

export default function BankIcon({ code, name = "", icon = "", size, alt = "", className = "" }: Props) {
  const sources = bankIconSources(code, icon);
  // Сколько источников уже не загрузилось.
  const [failed, setFailed] = useState(0);
  const src = sources[failed];
  const box = size ? { width: size, height: size } : undefined;
  // Скругление долей от стороны — как у значков приложений, на любом размере.
  const shape = `shrink-0 rounded-[24%] ${size ? "" : "h-full w-full"} ${className}`;

  if (src) {
    const local = src.startsWith("/");
    return (
      // Значок — маленький готовый файл (свой или с сервера банков):
      // оптимизатор картинок Next тут ни к чему.
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={src}
        alt={alt}
        title={alt || undefined}
        width={size || 40}
        height={size || 40}
        loading="lazy"
        decoding="async"
        referrerPolicy={local ? undefined : "no-referrer"}
        onError={() => setFailed((n) => n + 1)}
        style={box}
        className={`bg-surface-3 object-cover shadow-[0_0_0_1px_var(--border)] ${shape}`}
      />
    );
  }

  const letter = (name || code || "?").trim().charAt(0).toUpperCase();
  return (
    <span
      role={alt ? "img" : undefined}
      aria-label={alt || undefined}
      aria-hidden={alt ? undefined : "true"}
      title={alt || undefined}
      style={size ? { ...box, fontSize: Math.round(size * 0.44) } : undefined}
      className={`inline-flex items-center justify-center bg-surface-3 font-bold leading-none text-foreground ${shape}`}
    >
      {letter}
    </span>
  );
}

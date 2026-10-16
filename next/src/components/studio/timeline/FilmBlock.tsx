"use client";

import type { CSSProperties, ReactNode } from "react";
import { useInView } from "@/components/vstudio/feed/useInView";
import { vx } from "@/components/vstudio/ui/skin";

/**
 * Заглушка «плёнка проявляется» (vs-film) на месте того, что ещё грузится или
 * собирается. Анимация идёт, только пока блок на экране: склейка длится минуты,
 * а прокрутить от неё можно далеко. «Меньше движения» гасит её в globals.css.
 */
export default function FilmBlock({
  className,
  style,
  children,
}: {
  className?: string;
  style?: CSSProperties;
  children?: ReactNode;
}) {
  const [ref, inView] = useInView<HTMLDivElement>();
  return (
    <div ref={ref} aria-hidden className={vx("vs-film", !inView && "[animation-play-state:paused]", className)} style={style}>
      {children}
    </div>
  );
}

"use client";

import { vx } from "../../ui/skin";
import { GALLERY_GRID } from "./GalleryCard";
import { useOnScreen } from "./useOnScreen";

const TAB_WIDTHS = ["w-14", "w-28", "w-24", "w-20"];

// Полоски-заглушки: «чернила» темы. На светлой сцене те же доли почти не видны, поэтому там они чуть плотнее.
const BAR_TAB = "bg-vs-ink/[0.07] dark:bg-vs-ink/[0.05]";
const BAR_TITLE = "bg-vs-ink/[0.1] dark:bg-vs-ink/[0.07]";
const BAR_SUB = "bg-vs-ink/[0.06] dark:bg-vs-ink/[0.04]";

/**
 * Галерея, пока витрина в пути: те же вкладки и та же сетка, что придут
 * следом, — чтобы секция не меняла высоту, когда появятся карточки. Строки
 * под кадром повторяют высоту настоящих подписей (20 + 20 px).
 */
export default function GallerySkeleton({ count }: { count: number }) {
  const [ref, seen] = useOnScreen<HTMLDivElement>();
  const film = seen ? "vs-film" : "bg-surface-2";

  return (
    <div ref={ref} aria-hidden>
      <div className="mt-5 flex gap-2 overflow-hidden">
        {TAB_WIDTHS.map((width) => (
          <span key={width} className={vx("h-10 shrink-0 rounded-full md:h-9", BAR_TAB, width)} />
        ))}
      </div>
      <div className={vx(GALLERY_GRID, "mt-5")}>
        {Array.from({ length: count }, (_, k) => (
          <div key={k} className="min-w-0">
            <div className={vx("aspect-video rounded-xl", film)} />
            <div className="mt-2.5 flex h-5 items-center">
              <span className={vx("h-3 w-3/4 rounded-full", BAR_TITLE)} />
            </div>
            <div className="mt-0.5 flex h-5 items-center">
              <span className={vx("h-2.5 w-1/2 rounded-full", BAR_SUB)} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

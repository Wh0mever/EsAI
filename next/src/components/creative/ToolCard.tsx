"use client";

import Link from "next/link";
import clsx from "clsx";
import { useTranslation } from "react-i18next";
import { FaChevronRight } from "react-icons/fa6";
import type { CreativeTool } from "@/lib/creative/tools";
import { CREATIVE_PATH } from "@/lib/nav/paths";
import ToolArt from "./ToolArt";

// Карточка инструмента по макету клиента: превью, номер в жёлтом круге,
// название, описание, жёлтая стрелка. Вся карточка — одна ссылка.
// Текст лежит поверх нижней части картинки на затемнении, поэтому карточка
// всегда тёмная (как первый экран), независимо от темы сайта.
export default function ToolCard({ tool, priority = false }: { tool: CreativeTool; priority?: boolean }) {
  const { t } = useTranslation("creative");
  const name = t(`tools.${tool.id}.name`, { defaultValue: tool.name });
  const desc = t(`tools.${tool.id}.desc`, { defaultValue: tool.desc });

  return (
    <Link
      href={`${CREATIVE_PATH}/${tool.id}`}
      className={clsx(
        "group relative flex aspect-[3/4] flex-col overflow-hidden rounded-2xl sm:aspect-[4/3]",
        "border border-white/10 bg-neutral-950 text-white",
        "transition duration-300 hover:-translate-y-0.5 hover:border-[#F5C518]/60 hover:shadow-[0_8px_30px_-12px_rgba(245,197,24,0.45)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F5C518] focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      )}
    >
      <ToolArt tool={tool} priority={priority} />

      <span
        aria-hidden="true"
        className="absolute left-3 top-3 grid size-7 place-items-center rounded-full bg-[#F5C518] text-[13px] font-bold text-black shadow"
      >
        {tool.n}
      </span>
      {tool.state === "soon" && (
        <span className="absolute right-3 top-3 rounded-full bg-black/60 px-2.5 py-1 text-[11px] font-medium text-white/85 backdrop-blur">
          {t("page.soon", { defaultValue: "Скоро" })}
        </span>
      )}

      <span className="relative mt-auto flex items-end gap-2 bg-gradient-to-t from-black via-black/85 to-transparent px-3 pb-3 pt-10 sm:px-3.5">
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold leading-tight sm:text-base">{name}</span>
          <span className="mt-1 line-clamp-2 block text-xs leading-snug text-white/70 sm:text-[13px]">{desc}</span>
        </span>
        <span
          aria-hidden="true"
          className="grid size-7 shrink-0 place-items-center rounded-full bg-[#F5C518] text-black transition-transform duration-300 group-hover:translate-x-0.5"
        >
          <FaChevronRight className="size-3" />
        </span>
      </span>
    </Link>
  );
}

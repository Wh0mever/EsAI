"use client";

import Link from "next/link";
import clsx from "clsx";
import { useTranslation } from "react-i18next";
import { FaChevronRight } from "react-icons/fa6";
import type { CreativeTool } from "@/lib/creative/tools";
import { CREATIVE_PATH } from "@/lib/nav/paths";
import ToolArt from "./ToolArt";
import { useCreativeAccess } from "./run/useCreativeAccess";

// Карточка инструмента по макету клиента: превью, номер в жёлтом круге,
// название, описание, жёлтая стрелка. Вся карточка — одна ссылка.
// От 640 px текст лежит поверх нижней части картинки на затемнении (карточка 4:3).
// На телефоне две узкие колонки: там картинка 16:9 видна целиком, текст — под ней,
// иначе «было ≫ стало» на превью обрезалось бы до середины.
// Карточка всегда тёмная (как первый экран), независимо от темы сайта.
export default function ToolCard({ tool, priority = false }: { tool: CreativeTool; priority?: boolean }) {
  // «Скоро» — только у инструмента, который сервер называет закрытым (выключен в админке
  // или раздел не открыт этому человеку). Пока ответа нет — метки нет: раздел открыт всем
  // с 23.11, и «скоро» на работающих инструментах путало людей (замечание клиента).
  const access = useCreativeAccess();
  const closed =
    access.status === "ready" &&
    (access.data.tools.some((x) => x.id === tool.id && !x.enabled) ||
      (access.data.mode !== "on" && !access.data.available));
  const soon = tool.state === "soon" || closed;
  const { t } = useTranslation("creative");
  const name = t(`tools.${tool.id}.name`, { defaultValue: tool.name });
  const desc = t(`tools.${tool.id}.desc`, { defaultValue: tool.desc });

  return (
    <Link
      href={`${CREATIVE_PATH}/${tool.id}`}
      className={clsx(
        "group relative flex h-full flex-col overflow-hidden rounded-2xl sm:aspect-[4/3] sm:h-auto",
        "border border-white/10 bg-neutral-950 text-white",
        "transition duration-300 hover:-translate-y-0.5 hover:border-[#F5C518]/60 hover:shadow-[0_8px_30px_-12px_rgba(245,197,24,0.45)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-text)] focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      )}
    >
      <span className="relative block aspect-video overflow-hidden sm:absolute sm:inset-0 sm:aspect-auto">
        <ToolArt tool={tool} priority={priority} />
      </span>

      <span
        aria-hidden="true"
        className="absolute left-2 top-2 grid size-6 place-items-center rounded-full bg-[#F5C518] text-[11px] font-bold text-black shadow sm:left-3 sm:top-3 sm:size-7 sm:text-[13px]"
      >
        {tool.n}
      </span>
      {soon && (
        <span className="absolute right-2 top-2 rounded-full bg-black/60 px-2 py-0.5 text-[10px] font-medium text-white/85 backdrop-blur sm:right-3 sm:top-3 sm:px-2.5 sm:py-1 sm:text-[11px]">
          {t("page.soon", { defaultValue: "Скоро" })}
        </span>
      )}

      <span className="relative flex flex-1 items-start gap-2 px-3 pb-3 pt-2.5 sm:mt-auto sm:flex-none sm:items-end sm:bg-gradient-to-t sm:from-black sm:via-black/85 sm:to-transparent sm:px-3.5 sm:pt-10">
        <span className="min-w-0 flex-1">
          <span className="block hyphens-auto break-words text-sm font-semibold leading-tight sm:text-base">{name}</span>
          <span className="mt-1 line-clamp-2 text-xs leading-snug text-white/70 sm:text-[13px]">{desc}</span>
        </span>
        <span
          aria-hidden="true"
          className="hidden size-7 shrink-0 place-items-center rounded-full bg-[#F5C518] text-black transition-transform duration-300 group-hover:translate-x-0.5 sm:grid"
        >
          <FaChevronRight className="size-3" />
        </span>
      </span>
    </Link>
  );
}

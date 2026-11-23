"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { FaArrowLeft } from "react-icons/fa6";
import { CREATIVE_TOOLS, toolById, type CreativeTool } from "@/lib/creative/tools";
import { CREATIVE_CATEGORIES } from "@/lib/nav/menu";
import { CREATIVE_PATH } from "@/lib/nav/paths";
import ToolArt from "./ToolArt";
import ToolCard from "./ToolCard";

/**
 * Куски страницы инструмента: шапка (картинка, название, описание), метка
 * «скоро» и соседние инструменты категории. Страница с формой — ToolView;
 * ToolSoon целиком — прежняя заглушка, когда инструмент закрыт.
 */

/** Ссылка «Все инструменты». */
export function ToolBack() {
  const { t } = useTranslation("creative");
  return (
    <Link
      href={CREATIVE_PATH}
      className="inline-flex min-h-11 items-center gap-2 text-sm text-muted transition-colors hover:text-foreground"
    >
      <FaArrowLeft aria-hidden="true" className="size-3" />
      {t("tool.back", { defaultValue: "Все инструменты" })}
    </Link>
  );
}

/** Первый экран: картинка, категория, название, описание; slot — под описанием. */
export function ToolHero({ tool, children }: { tool: CreativeTool; children?: ReactNode }) {
  const { t } = useTranslation("creative");
  const tHome = useTranslation("home").t;
  const cat = CREATIVE_CATEGORIES.find((c) => c.id === tool.cat)!;
  return (
    <section className="mt-3 grid grid-cols-[minmax(0,1fr)] gap-6 md:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] md:items-center">
      <div className="group relative aspect-video overflow-hidden rounded-2xl border border-border bg-neutral-950">
        <ToolArt tool={tool} fetchPriority="high" sizes="(min-width: 1280px) 570px, (min-width: 768px) 45vw, 100vw" />
      </div>
      <div>
        <Link
          href={`${CREATIVE_PATH}?cat=${cat.id}`}
          className="text-xs font-semibold uppercase tracking-wide text-accent hover:underline"
        >
          {tHome(cat.label, { defaultValue: cat.fallback })}
        </Link>
        <h1 className="mt-2 text-3xl font-extrabold leading-tight sm:text-4xl">
          {t(`tools.${tool.id}.name`, { defaultValue: tool.name })}
        </h1>
        <p className="mt-3 text-lg text-muted">{t(`tools.${tool.id}.desc`, { defaultValue: tool.desc })}</p>
        <p className="mt-2 text-sm text-muted">
          {tool.output === "image"
            ? t("tool.output_image", { defaultValue: "Результат: изображение" })
            : t("tool.output_video", { defaultValue: "Результат: видео" })}
        </p>
        {children}
      </div>
    </section>
  );
}

/** Метка «Инструмент скоро откроется». */
export function SoonNotice() {
  const { t } = useTranslation("creative");
  return (
    <div className="mt-6 rounded-2xl border border-[#F5C518]/40 bg-[#F5C518]/10 p-5">
      <p className="font-semibold">{t("tool.soon_title", { defaultValue: "Инструмент скоро откроется" })}</p>
      <p className="mt-1 text-sm text-muted">
        {t("tool.soon_text", { defaultValue: "Мы готовим этот инструмент. Пока можно попробовать другие разделы EsAI." })}
      </p>
    </div>
  );
}

/** Другие инструменты той же категории. */
export function OtherTools({ tool }: { tool: CreativeTool }) {
  const { t } = useTranslation("creative");
  const others = CREATIVE_TOOLS.filter((x) => x.cat === tool.cat && x.id !== tool.id);
  if (!others.length) return null;
  return (
    <section className="mt-14">
      <h2 className="text-xl font-bold">{t("tool.other", { defaultValue: "Другие инструменты этой категории" })}</h2>
      <ul className="mt-4 grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-3 xl:grid-cols-5">
        {others.map((x) => (
          <li key={x.id}>
            <ToolCard tool={x} />
          </li>
        ))}
      </ul>
    </section>
  );
}

// Заглушка страницы инструмента: название, описание, метка «скоро», соседи.
export default function ToolSoon({ id }: { id: string }) {
  const tool = toolById(id);
  if (!tool) return null;
  return (
    <main className="mx-auto max-w-7xl px-4 pb-16 pt-28 sm:px-6 sm:pt-32 lg:px-8">
      <ToolBack />
      <ToolHero tool={tool}>
        <SoonNotice />
      </ToolHero>
      <OtherTools tool={tool} />
    </main>
  );
}

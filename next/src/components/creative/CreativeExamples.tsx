"use client";

import { useTranslation } from "react-i18next";
import { CREATIVE_EXAMPLES, HAS_EXAMPLES } from "@/lib/creative/examples";
import { toolById } from "@/lib/creative/tools";

// Блок «Примеры работ». Пока примеров нет — не выводится (см. lib/creative/examples.ts).
export default function CreativeExamples() {
  const { t } = useTranslation("creative");
  if (!HAS_EXAMPLES) return null;

  return (
    <section id="examples" className="scroll-mt-28 pt-14">
      <h2 className="text-2xl font-bold sm:text-3xl">{t("page.examples_title", { defaultValue: "Примеры работ" })}</h2>
      <p className="mt-2 text-muted">{t("page.examples_sub", { defaultValue: "Реальные результаты инструментов Creative Studio." })}</p>
      <ul className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {CREATIVE_EXAMPLES.map((ex, i) => {
          const tool = toolById(ex.tool);
          return (
            <li key={ex.src} className="overflow-hidden rounded-2xl border border-border bg-surface">
              {ex.kind === "video" ? (
                <video src={ex.src} poster={ex.poster} controls playsInline preload="none" className="aspect-video w-full bg-black object-cover" />
              ) : (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={ex.src} alt={ex.caption} loading="lazy" className="aspect-video w-full object-cover" />
              )}
              <div className="p-4">
                {tool && (
                  <p className="text-xs font-medium uppercase tracking-wide text-[#F5C518]">
                    {t(`tools.${tool.id}.name`, { defaultValue: tool.name })}
                  </p>
                )}
                <p className="mt-1 text-sm text-muted">{t(`examples.${i}`, { defaultValue: ex.caption })}</p>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

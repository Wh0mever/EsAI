"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslation } from "react-i18next";
import EsaiLogo from "@/components/brand/EsaiLogo";
import { SavePanel } from "@/components/ui/SaveSheet";
import { newDiagCode, type SaveTarget } from "@/tools/saveEnv";
import type { SheetStart } from "@/tools/saveMedia";

/**
 * Страница /save: сам файл и та же панель, что в шторке «Сохранить». Файл
 * начинает качаться сразу, поэтому в Safari одно нажатие «Сохранить видео»
 * открывает окно, пока жест ещё действует.
 */
export default function SaveClient({ target }: { target: SaveTarget | null }) {
  const { t } = useTranslation("common");
  const [start] = useState<SheetStart>(() => ({ reason: "", failed: false, diag: newDiagCode() }));
  const video = target?.kind === "video";

  return (
    <main className="flex min-h-dvh flex-col bg-background text-foreground">
      <header className="flex h-14 items-center border-b border-border px-4 sm:px-6">
        <Link
          href="/"
          className="flex min-h-11 items-center rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/80"
        >
          <EsaiLogo className="h-7 w-auto" />
        </Link>
      </header>

      {/* Снизу запас под баннер «Установить приложение»: он фиксирован у нижнего края. */}
      <div className="flex flex-1 flex-col items-center px-4 pb-32 pt-6">
        {target ? (
          <div className="flex w-full max-w-md flex-col gap-4">
            <h1 className="text-xl font-semibold">
              {video
                ? t("media.sheet.save_video", { defaultValue: "Сохранить видео" })
                : t("media.sheet.save_image", { defaultValue: "Сохранить фото" })}
            </h1>
            {video ? (
              // #t=0.1 — iOS иначе показывает чёрный прямоугольник вместо первого кадра.
              <video
                src={`${target.path}#t=0.1`}
                controls
                playsInline
                preload="metadata"
                className="max-h-[50dvh] w-full rounded-xl bg-black object-contain"
              />
            ) : (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={target.path}
                alt={target.filename}
                className="max-h-[50dvh] w-full rounded-xl bg-surface-2 object-contain"
              />
            )}
            <SavePanel url={target.path} filename={target.filename} start={start} page />
          </div>
        ) : (
          <div className="flex w-full max-w-md flex-col items-center gap-4 pt-10 text-center">
            <p className="text-base text-foreground">
              {t("media.save_page.bad_link", { defaultValue: "Ссылка на файл неверная или устарела." })}
            </p>
            <Link
              href="/"
              className="inline-flex min-h-11 items-center rounded-full bg-accent px-5 text-sm font-semibold text-on-accent transition-colors hover:bg-accent-strong motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/80 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              {t("media.save_page.home", { defaultValue: "Перейти на EsAI" })}
            </Link>
          </div>
        )}
      </div>
    </main>
  );
}

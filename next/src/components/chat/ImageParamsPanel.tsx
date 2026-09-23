"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { aspectHint, IconAspect } from "./VideoParamsPanel";

/**
 * ImageParamsPanel — пропорции кадра для генерации изображений.
 *
 * Клиент попросил выбор 16:9 и прочего «везде, даже в генерациях изображений».
 * Панель нарочно скромнее видео-шной: у картинок из настроек только пропорции,
 * длительности и опорных кадров тут нет.
 *
 * Список общий, а не по моделям: каталог /images/models пропорции по моделям не
 * отдаёт (проверено). На стороне сервера значение всё равно сверяется со
 * списком, а моделям без такого параметра (Nano Banana работает через
 * chat-completions) пропорция дописывается в текст запроса.
 */

const RATIOS = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "4:5"];

export default function ImageParamsPanel({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (ratio: string | null) => void;
}) {
  const { t } = useTranslation("common");
  const [open, setOpen] = useState(true);

  const chip = (active: boolean) =>
    "rounded-lg px-2.5 py-1 text-xs font-semibold border transition-all duration-200 cursor-pointer active:scale-95 " +
    (active
      ? "bg-accent text-on-accent border-accent shadow-sm"
      : "bg-surface-2 text-muted border-border hover:text-foreground hover:border-accent/50");

  return (
    <div className="rounded-2xl border border-border bg-surface-2/60 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left cursor-pointer transition-colors hover:bg-surface-2"
      >
        <IconAspect className="size-4 shrink-0 text-accent-strong" />
        <span className="text-xs font-semibold text-foreground">
          {t("chat.image.panel_title", { defaultValue: "Параметры изображения" })}
        </span>
        {value && (
          <span className="ml-auto text-xs font-semibold text-accent-strong">{value}</span>
        )}
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
          strokeLinecap="round" strokeLinejoin="round"
          className={
            (value ? "ml-1 " : "ml-auto ") +
            "size-4 shrink-0 text-muted transition-transform duration-300 " +
            (open ? "rotate-180" : "")
          }
          aria-hidden>
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>

      {/* Раскрытие через grid-rows: плавно и без фиксированной высоты. */}
      <div
        className={
          "grid transition-all duration-300 ease-out " +
          (open ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0")
        }
      >
        <div className="min-h-0 overflow-hidden">
          <div className="flex flex-col gap-1.5 px-3 pb-3">
            <span className="text-[11px] text-muted">
              {t("chat.video.aspect", { defaultValue: "Соотношение сторон" })}
            </span>
            <div className="flex flex-wrap gap-1.5">
              {RATIOS.map((r) => (
                <button
                  key={r}
                  type="button"
                  // Повторное нажатие снимает выбор: без пропорции модель
                  // рисует своим размером по умолчанию, и это нормальный выбор.
                  onClick={() => onChange(value === r ? null : r)}
                  className={chip(value === r)}
                  title={aspectHint(t, r)}
                >
                  {r}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-muted-2 leading-snug">
              {value
                ? aspectHint(t, value)
                : t("chat.image.aspect_hint", {
                    defaultValue: "Не выбрано — модель нарисует своим размером. Можно и словами: «нарисуй вертикально»",
                  })}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

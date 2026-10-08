"use client";

import { memo } from "react";
import { useTranslation } from "react-i18next";
import { FiAlertTriangle, FiImage, FiLoader } from "react-icons/fi";
import type { DroppedInput, ShotInputJSON, Uid } from "@/lib/vstudio/types";
import { VS_FOCUS, vx } from "../ui/skin";
import { inputRows, type InputRow } from "./feedLogic";

export type InputsStripProps = {
  inputs: ShotInputJSON[];
  /** dropped выбранного дубля: что компилятор не отправил модели. */
  dropped?: DroppedInput[];
  /** uid виноватого входа (TakeLite.error.input) — красная рамка. */
  culprit?: Uid | null;
};

function badge(t: (k: string, o?: Record<string, unknown>) => string, row: InputRow): string {
  const { slot } = row.input;
  if (slot === "first_frame") return t("inputs.firstFrame", { defaultValue: "Первый кадр" });
  if (slot === "last_frame") return t("inputs.lastFrame", { defaultValue: "Последний кадр" });
  return row.n ? `@Image ${row.n}` : "@Image —";
}

function reasonText(t: (k: string, o?: Record<string, unknown>) => string, reason: string | null): string {
  if (reason === "duplicate_frame") {
    return t("sent.reason.duplicate_frame", { defaultValue: "Второй кадр в том же слоте — не отправлен" });
  }
  if (reason === "excluded_by_user") {
    return t("sent.reason.excluded_by_user", { defaultValue: "Не учитывается и не оплачивается" });
  }
  return t("sent.reason.other", { defaultValue: "Модель не получила этот материал" });
}

/**
 * Миниатюры входов кадра: @Image N по порядку, затем кадры. Не ушедшее
 * модели — серое с подписью «не учтено» (§0 п. 9), виноватый вход при
 * отказе модерации — в красной рамке с подписью (§9.6).
 */
function InputsStrip({ inputs, dropped, culprit }: InputsStripProps) {
  const { t } = useTranslation("vstudio", { useSuspense: false });
  const tr = t as unknown as (k: string, o?: Record<string, unknown>) => string;
  const rows = inputRows(inputs, dropped, culprit);
  if (!rows.length) return null;

  return (
    <ul
      // Поля со всех сторон: лента прокручивается и иначе срезала бы красное кольцо у виноватого входа.
      className="-mx-1 -mt-1 flex gap-2.5 overflow-x-auto px-1 pb-1 pt-1"
      aria-label={t("sent.inputs", { defaultValue: "Материалы" })}
    >
      {rows.map((row) => {
        const { asset, role } = row.input;
        const label = badge(tr, row);
        const src = asset.thumb_url || asset.url;
        const why = row.excluded ? reasonText(tr, row.reason) : "";
        const aria = [
          label,
          role,
          row.excluded ? why : "",
          row.culprit ? t("inputs.culprit", { defaultValue: "Из-за этого фото модель отказала" }) : "",
        ]
          .filter(Boolean)
          .join(" · ");
        // Пунктир «не учтено» на белом бледнее сплошной линии той же плотности — в светлой теме он плотнее.
        const frame = row.culprit
          ? "border-status-fail ring-2 ring-status-fail/50"
          : row.excluded
            ? "border-dashed border-vs-ink/30 dark:border-vs-ink/20"
            : "border-vs-ink/10 hover:border-vs-ink/25";
        return (
          <li key={row.key} className="flex w-[4.5rem] shrink-0 flex-col gap-1" title={aria}>
            <div
              className={vx(
                "relative size-[4.5rem] overflow-hidden rounded-xl border bg-vs-ink/[0.04] transition-colors",
                frame,
              )}
            >
              {src && asset.status === "ready" ? (
                <a
                  href={asset.url || src}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={aria}
                  // Кольцо фокуса внутрь: рамка миниатюры обрезает всё, что выходит за неё.
                  className={vx("block h-full w-full cursor-zoom-in rounded-xl focus-visible:ring-inset", VS_FOCUS)}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={src}
                    alt=""
                    loading="lazy"
                    decoding="async"
                    className={vx("h-full w-full object-cover", row.excluded && "opacity-40 grayscale")}
                  />
                </a>
              ) : (
                <span className="grid h-full w-full place-items-center text-muted-2" aria-label={aria} role="img">
                  {asset.status === "pending" ? <FiLoader className="animate-spin motion-reduce:animate-none" /> : <FiImage />}
                </span>
              )}
              {row.culprit && (
                <span
                  className="pointer-events-none absolute right-1 top-1 grid size-5 place-items-center rounded-full bg-status-fail text-[11px] text-white"
                  aria-hidden
                >
                  <FiAlertTriangle />
                </span>
              )}
            </div>
            <span
              className={vx(
                "line-clamp-2 break-words text-[11px] font-medium leading-tight",
                row.culprit ? "text-status-fail" : row.excluded ? "text-muted-2 line-through" : "text-foreground/85",
              )}
              aria-hidden
            >
              {label}
            </span>
            {row.excluded ? (
              <span className="truncate text-[10px] leading-tight text-muted-2" aria-hidden>
                {t("inputs.excluded", { defaultValue: "не учтено" })}
              </span>
            ) : role ? (
              <span className="truncate text-[10px] leading-tight text-muted" aria-hidden>
                {role}
              </span>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

export default memo(InputsStrip);

"use client";

import { useState } from "react";
import { FiExternalLink, FiUser } from "react-icons/fi";
import { EXTERNAL_REL } from "@/lib/academy/shared";

/**
 * Карточка курса: обложка 16:9, название в 2 строки, преподаватель, описание в
 * 3 строки, кнопка на всю ширину (ТЗ п.4). Без переводов — подписи приходят
 * пропсами: ту же карточку показывает живое превью в панели.
 */
export type CourseCardData = {
  title: string;
  teacher: string;
  description: string;
  /** null — превью в панели: кнопка нарисована, но никуда не ведёт. */
  href: string | null;
  cover: string | null;
  coverThumb: string | null;
  coverWidth: number | null;
};

export type CourseCardLabels = { cta: string; newTab: string; teacher: string };

/** Ширина колонки сетки: 1 колонка на телефоне, 2 на планшете, 3 по ~384 px в контейнере 1200. */
const SIZES = "(min-width: 1024px) 384px, (min-width: 768px) 50vw, 100vw";

const CTA =
  "mt-auto inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-full bg-accent px-5 py-2.5 text-center text-sm font-semibold text-on-accent";

export default function CourseCard({
  course,
  labels,
  eager = false,
  headingId,
}: {
  course: CourseCardData;
  labels: CourseCardLabels;
  /** Первый ряд сетки грузится сразу — он на первом экране. */
  eager?: boolean;
  /** id заголовка: у всех кнопок текст один, название курса читалка берёт из него. */
  headingId?: string;
}) {
  const full = course.cover;
  const thumb = course.coverThumb && course.coverThumb !== full ? course.coverThumb : null;
  // Лёгкая копия — только если оригинал заметно больше неё; ширину оригинала знает сервер.
  const fullWidth = course.coverWidth && course.coverWidth > 480 ? course.coverWidth : 1280;
  const srcSet = full && thumb ? `${thumb} 480w, ${full} ${fullWidth}w` : undefined;
  // Обложку заменили или курс удалили: старый файл стёрт сразу, а каталог из кэша
  // (до 60 с) ещё ссылается на него — вместо битой картинки знак EsAI.
  const [failed, setFailed] = useState<string | null>(null);

  return (
    <article className="flex h-full min-w-0 flex-col overflow-hidden rounded-2xl border border-border bg-surface">
      <div className="relative aspect-video w-full overflow-hidden bg-surface-2">
        {full && failed !== full ? (
          // Название — в заголовке рядом: alt его повторил бы, обложка декоративная.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={full}
            srcSet={srcSet}
            sizes={srcSet ? SIZES : undefined}
            width={1280}
            height={720}
            alt=""
            loading={eager ? "eager" : "lazy"}
            decoding="async"
            onError={() => setFailed(full)}
            className="absolute inset-0 h-full w-full object-cover"
          />
        ) : (
          <div className="absolute inset-0 grid place-items-center">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/esai-mark.svg" alt="" className="h-10 w-auto opacity-40" />
          </div>
        )}
      </div>

      <div className="flex flex-1 flex-col gap-2 p-5">
        <h3
          id={headingId}
          className="line-clamp-2 text-lg font-bold leading-snug text-foreground [overflow-wrap:anywhere]"
          title={course.title}
        >
          {course.title}
        </h3>
        {course.teacher && (
          <p className="flex min-w-0 items-center gap-1.5 text-sm font-medium text-foreground/80">
            <FiUser className="h-4 w-4 shrink-0 text-muted-2" aria-hidden />
            <span className="sr-only">{labels.teacher} </span>
            <span className="min-w-0 truncate" title={course.teacher}>
              {course.teacher}
            </span>
          </p>
        )}
        {course.description && (
          <p className="mb-3 line-clamp-3 text-sm leading-relaxed text-muted [overflow-wrap:anywhere]">
            {course.description}
          </p>
        )}

        {course.href ? (
          <a
            href={course.href}
            target="_blank"
            rel={EXTERNAL_REL}
            aria-describedby={headingId}
            className={`${CTA} transition-colors hover:bg-accent-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-background`}
          >
            <span className="min-w-0 [overflow-wrap:anywhere]">{labels.cta}</span>
            <FiExternalLink className="h-4 w-4 shrink-0" aria-hidden />
            <span className="sr-only">{labels.newTab}</span>
          </a>
        ) : (
          <span className={CTA} aria-hidden>
            {labels.cta}
            <FiExternalLink className="h-4 w-4 shrink-0" />
          </span>
        )}
      </div>
    </article>
  );
}

"use client";

import { FiChevronDown, FiChevronUp, FiEdit2, FiExternalLink, FiEye, FiEyeOff, FiImage, FiTrash2 } from "react-icons/fi";
import { Badge, CARD, btn, type Tone } from "../vstudio-showcase/parts";
import { STATE_LABEL, STATE_TITLE, aspectWarning, placeLabel, publishHint, type Course } from "./academyAdmin";

const STATE_TONE: Record<Course["state"], Tone> = { live: "accent", draft: "muted", hidden: "muted", incomplete: "wait" };

const ORDER_BTN =
  "flex h-11 w-11 cursor-pointer items-center justify-center rounded-lg border border-border text-muted transition-colors enabled:hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 sm:h-8 sm:w-9";

type Props = {
  course: Course;
  index: number;
  total: number;
  /** Запрос по этому курсу в пути. */
  busy: boolean;
  /** Порядок сейчас менять нельзя: идёт перестановка или список отфильтрован. */
  orderLocked: boolean;
  orderHint: string;
  onMove: (course: Course, to: number) => void;
  onPublish: (course: Course, published: boolean) => void;
  onEdit: (course: Course) => void;
  onDelete: (course: Course) => void;
};

/** Курс в списке: как он выглядит, где стоит на сайте и чего ему не хватает. */
export default function CourseRow({
  course,
  index,
  total,
  busy,
  orderLocked,
  orderHint,
  onMove,
  onPublish,
  onEdit,
  onDelete,
}: Props) {
  const hint = publishHint(course.missing);
  const aspect = course.cover ? aspectWarning(course.coverWidth, course.coverHeight) : null;
  const thumb = course.coverThumb ?? course.cover;
  const where = placeLabel(course.place);

  const commitPlace = (field: HTMLInputElement) => {
    // Пустое поле и не число — не «первое место», а «передумал».
    const typed = /^\d+$/.test(field.value.trim()) ? Number(field.value.trim()) : index + 1;
    const target = Math.min(Math.max(typed, 1), total);
    if (target !== index + 1) onMove(course, target - 1);
    else field.value = String(index + 1);
  };

  return (
    <li className={`${CARD} flex flex-col gap-3 p-3 sm:flex-row sm:items-start`}>
      <div className="flex shrink-0 items-center gap-1 sm:flex-col" title={orderHint}>
        <button
          type="button"
          onClick={() => onMove(course, index - 1)}
          disabled={orderLocked || index === 0}
          aria-label="Поднять выше"
          title="Выше"
          className={ORDER_BTN}
        >
          <FiChevronUp className="h-4 w-4" aria-hidden />
        </button>
        {/* key: после перестановки поле показывает новое место, а не то, что в нём набрали. */}
        <input
          key={index}
          defaultValue={index + 1}
          inputMode="numeric"
          disabled={orderLocked}
          aria-label={`Место в списке: ${index + 1} из ${total}`}
          title="Место в списке — впишите номер, чтобы переставить сразу"
          onFocus={(e) => e.currentTarget.select()}
          onBlur={(e) => commitPlace(e.currentTarget)}
          onKeyDown={(e) => {
            if (e.key === "Enter") e.currentTarget.blur();
            if (e.key === "Escape") {
              e.currentTarget.value = String(index + 1);
              e.currentTarget.blur();
            }
          }}
          className="h-11 w-12 rounded-lg border border-border bg-surface-2 text-center text-sm tabular-nums text-foreground outline-none focus:border-accent disabled:opacity-60 sm:h-8 sm:w-9"
        />
        <button
          type="button"
          onClick={() => onMove(course, index + 1)}
          disabled={orderLocked || index === total - 1}
          aria-label="Опустить ниже"
          title="Ниже"
          className={ORDER_BTN}
        >
          <FiChevronDown className="h-4 w-4" aria-hidden />
        </button>
      </div>

      <div
        className={`relative aspect-video w-full shrink-0 overflow-hidden rounded-xl bg-surface-2 sm:w-48 ${
          course.state === "live" ? "" : "opacity-70"
        }`}
      >
        {thumb ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={thumb} alt="" loading="lazy" decoding="async" className="h-full w-full object-cover" />
        ) : (
          <div className="flex h-full w-full flex-col items-center justify-center gap-1 text-muted-2">
            <FiImage className="h-6 w-6" aria-hidden />
            <span className="text-[11px]">Нет обложки</span>
          </div>
        )}
      </div>

      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex flex-wrap items-start gap-2">
          <div className="min-w-0 flex-1 basis-48">
            <div className="line-clamp-2 text-sm font-semibold text-foreground [overflow-wrap:anywhere]" title={course.title}>
              {course.title || <span className="font-normal italic text-muted-2">Без названия</span>}
            </div>
            {course.teacher && (
              <div className="truncate text-xs text-muted" title={course.teacher}>
                {course.teacher}
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge tone={STATE_TONE[course.state]} title={STATE_TITLE[course.state]}>
              {STATE_LABEL[course.state]}
            </Badge>
            {where && (
              <Badge tone="muted" title="Где курс стоит на /academy: страница и место на ней">
                {where}
              </Badge>
            )}
          </div>
        </div>

        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-2">
          {course.url && course.urlHost ? (
            // Хост в punycode: ссылку с кириллической подменой домена так видно сразу.
            <a
              href={course.url}
              target="_blank"
              rel="noopener noreferrer"
              title={course.url}
              className="inline-flex min-w-0 items-center gap-1 font-mono hover:text-foreground"
            >
              <FiExternalLink className="h-3 w-3 shrink-0" aria-hidden />
              <span className="truncate">{course.urlHost}</span>
            </a>
          ) : (
            <span>{course.url ? "Ссылка не проходит проверку" : "Ссылки нет"}</span>
          )}
          {course.cover && course.coverWidth > 0 && (
            <>
              <span aria-hidden>·</span>
              <span className="tabular-nums">
                обложка {course.coverWidth}×{course.coverHeight}
              </span>
            </>
          )}
        </div>

        {course.description && (
          <p className="line-clamp-2 text-xs text-muted [overflow-wrap:anywhere]" title={course.description}>
            {course.description}
          </p>
        )}
        {hint && <p className="text-xs text-status-wait">{hint}</p>}
        {aspect && <p className="text-xs text-status-wait">{aspect}</p>}

        <div className="mt-auto flex flex-wrap items-center gap-2">
          {course.published ? (
            <button type="button" onClick={() => onPublish(course, false)} disabled={busy} className={`${btn()} min-h-11 sm:min-h-0`}>
              <FiEyeOff className="h-3.5 w-3.5" aria-hidden />
              Скрыть
            </button>
          ) : (
            <button
              type="button"
              onClick={() => onPublish(course, true)}
              disabled={busy}
              title={hint || "Показать курс на /academy"}
              className={`${btn("primary")} min-h-11 sm:min-h-0`}
            >
              <FiEye className="h-3.5 w-3.5" aria-hidden />
              Опубликовать
            </button>
          )}
          <button type="button" onClick={() => onEdit(course)} disabled={busy} className={`${btn()} min-h-11 sm:min-h-0`}>
            <FiEdit2 className="h-3.5 w-3.5" aria-hidden />
            Изменить
          </button>
          <button
            type="button"
            onClick={() => onDelete(course)}
            disabled={busy}
            className={`${btn("danger")} ml-auto min-h-11 sm:min-h-0`}
          >
            <FiTrash2 className="h-3.5 w-3.5" aria-hidden />
            Удалить
          </button>
        </div>
      </div>
    </li>
  );
}

"use client";

import { useEffect, useState } from "react";
import { FiExternalLink, FiImage, FiUpload, FiX } from "react-icons/fi";
import CourseCard from "@/components/academy/CourseCard";
import { ACADEMY_RU } from "@/lib/academy/shared";
import { INPUT_LG, btn } from "../vstudio-showcase/parts";
import Dialog from "../studio-scenes/Dialog";
import { Field } from "../studio-scenes/sceneParts";
import {
  COVER_ACCEPT,
  EMPTY_FORM,
  STATE_LABEL,
  aspectWarning,
  chars,
  checkCourseUrl,
  cleanText,
  courseChanges,
  coverFileError,
  coverSizeError,
  createBody,
  fmtMb,
  formFromCourse,
  lengthError,
  missingForPublish,
  placeLabel,
  publishHint,
  type Course,
  type CourseForm,
  type Limits,
} from "./academyAdmin";

/** Ответ страницы на запрос окна: курс с сервера или текст отказа. */
export type Saved = { course: Course | null; error: string | null };

/** Выбранная, но ещё не отправленная обложка. */
type Staged = {
  file: File;
  /** Ссылка для превью; null — файл отклонён до отправки. */
  url: string | null;
  width: number;
  height: number;
  /** Браузер ещё читает размер. */
  reading: boolean;
  /** Сервер такую не примет — не отправляем. */
  error: string | null;
};

type Mode = "save" | "publish" | "hide";

/** Размер картинки по её превью; 0×0 — браузер не открыл (HEIC в Chrome): размер проверит сервер. */
function readSize(src: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve) => {
    const img = new Image();
    let settled = false;
    const timer = setTimeout(() => finish(0, 0), 10_000);
    function finish(width: number, height: number) {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ width, height });
    }
    img.onload = () => finish(img.naturalWidth, img.naturalHeight);
    img.onerror = () => finish(0, 0);
    img.src = src;
  });
}

const LEGEND = "mb-1 text-xs font-semibold uppercase tracking-wide text-muted-2";
const CARD_LABELS = { cta: ACADEMY_RU["card.cta"], newTab: ACADEMY_RU["card.new_tab"], teacher: ACADEMY_RU["card.teacher"] };

type Props = {
  /**
   * null — новый курс. Созданный страница передаёт сюда же: если обложка не
   * ушла, повторное сохранение дошлёт её к нему, а не создаст второй курс.
   */
  course: Course | null;
  limits: Limits;
  onCreate: (body: Record<string, string>) => Promise<Saved>;
  onUpdate: (course: Course, changes: Record<string, unknown>) => Promise<Saved>;
  onUpload: (course: Course, file: File) => Promise<Saved>;
  /** Всё сохранено: окно закрывается, страница показывает итог. */
  onDone: (note: string) => void;
  onClose: () => void;
};

/**
 * Курс целиком: тексты, ссылка, обложка и живое превью карточки — с теми же
 * обрезками, что на сайте. Одно нажатие сохраняет поля, отправляет выбранную
 * обложку и, если попросили, публикует.
 */
export default function CourseDialog({ course, limits, onCreate, onUpdate, onUpload, onDone, onClose }: Props) {
  const [form, setForm] = useState<CourseForm>(() => (course ? formFromCourse(course) : EMPTY_FORM));
  const [staged, setStaged] = useState<Staged | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [urlTouched, setUrlTouched] = useState(false);

  const stagedUrl = staged?.url ?? null;
  useEffect(
    () => () => {
      if (stagedUrl) URL.revokeObjectURL(stagedUrl);
    },
    [stagedUrl],
  );

  const set = (patch: Partial<CourseForm>) => setForm((prev) => ({ ...prev, ...patch }));
  const live = course?.state === "live";
  const link = checkCourseUrl(form.url, limits.urlMax);
  const hasCover = Boolean(course?.cover) || Boolean(staged && !staged.error);

  const choose = async (file: File) => {
    setError(null);
    const problem = coverFileError(file, limits);
    if (problem) {
      setStaged({ file, url: null, width: 0, height: 0, reading: false, error: problem });
      return;
    }
    const url = URL.createObjectURL(file);
    setStaged({ file, url, width: 0, height: 0, reading: true, error: null });
    const size = await readSize(url);
    // Пока читали, могли выбрать другой файл — его не трогаем.
    setStaged((prev) =>
      prev && prev.file === file
        ? { ...prev, ...size, reading: false, error: coverSizeError(size.width, size.height, limits) }
        : prev,
    );
  };

  const submit = async (mode: Mode) => {
    if (busy) return;
    const tooLong = lengthError(form, limits);
    if (tooLong) {
      setError(tooLong.text);
      return;
    }
    if (staged?.error) {
      setError(staged.error);
      return;
    }
    if (staged?.reading) {
      setError("Подождите секунду: читаю размер обложки.");
      return;
    }
    if (mode === "publish") {
      const missing = missingForPublish(form, hasCover);
      if (missing.length) {
        setError(publishHint(missing));
        return;
      }
    }
    setError(null);

    let current = course;
    const created = current === null;
    if (current === null) {
      setBusy("Создаю…");
      const res = await onCreate(createBody(form));
      if (!res.course) return fail(res.error);
      current = res.course;
    } else {
      const changes: Record<string, unknown> = courseChanges(current, form);
      // Скрыть — тем же запросом, что и правки: опустошить поле у курса на сайте сервер не даст.
      if (mode === "hide" && current.published) changes.is_published = false;
      if (Object.keys(changes).length > 0) {
        setBusy("Сохраняю…");
        const res = await onUpdate(current, changes);
        if (!res.course) return fail(res.error);
        current = res.course;
      }
    }
    if (staged) {
      setBusy("Загружаю обложку…");
      const res = await onUpload(current, staged.file);
      if (!res.course) {
        return fail(`${created ? "Черновик создан" : "Курс сохранён"}, но обложка не загрузилась: ${res.error}`);
      }
      current = res.course;
      setStaged(null);
    }
    if (mode === "publish" && !current.published) {
      setBusy("Публикую…");
      const res = await onUpdate(current, { is_published: true });
      if (!res.course) return fail(`${created ? "Черновик создан" : "Курс сохранён"}, но не опубликован: ${res.error}`);
      current = res.course;
    }
    setBusy(null);
    const name = current.title ? `«${current.title}»` : `№${current.id}`;
    if (mode === "publish") onDone(`Курс ${name} опубликован — на сайте появится в течение минуты.`);
    else if (mode === "hide") onDone(`Курс ${name} скрыт с сайта.`);
    else if (created) onDone(`Черновик ${name} сохранён. На сайте его не видно, пока вы его не опубликуете.`);
    else onDone(`Курс ${name} сохранён.`);
  };

  function fail(text: string | null) {
    setBusy(null);
    setError(text || "Не получилось. Повторите.");
  }

  const coverSrc = staged?.url ?? course?.cover ?? null;
  const stagedWarning = staged && !staged.error ? aspectWarning(staged.width, staged.height) : null;
  const currentWarning = !staged && course?.cover ? aspectWarning(course.coverWidth, course.coverHeight) : null;
  const maxMb = Math.floor(limits.coverMaxBytes / (1024 * 1024));
  const place = placeLabel(course?.place ?? null);
  const subtitle = course
    ? [STATE_LABEL[course.state], place].filter(Boolean).join(" · ")
    : "Новый курс сохраняется черновиком: на сайте его не видно, пока вы его не опубликуете.";

  return (
    <Dialog
      wide
      title={course ? `Курс «${course.title || `№${course.id}`}»` : "Новый курс"}
      subtitle={subtitle}
      busy={busy !== null}
      onClose={onClose}
      onSubmit={() => void submit("save")}
      error={error}
      footer={
        <>
          <button type="button" onClick={onClose} disabled={busy !== null} className={btn("plain", "lg")}>
            Отмена
          </button>
          {live ? (
            <>
              <button type="button" onClick={() => void submit("hide")} disabled={busy !== null} className={btn("plain", "lg")}>
                Скрыть с сайта
              </button>
              <button type="submit" disabled={busy !== null} className={btn("primary", "lg")}>
                {busy ?? "Сохранить"}
              </button>
            </>
          ) : (
            <>
              <button type="submit" disabled={busy !== null} className={btn("plain", "lg")}>
                {course ? "Сохранить" : "Сохранить черновик"}
              </button>
              <button
                type="button"
                onClick={() => void submit("publish")}
                disabled={busy !== null}
                className={btn("primary", "lg")}
              >
                {busy ?? "Сохранить и опубликовать"}
              </button>
            </>
          )}
        </>
      }
    >
      <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_16rem]">
        <div className="min-w-0 space-y-5">
          <fieldset className="min-w-0 space-y-3">
            <legend className={LEGEND}>Карточка</legend>
            <Field label={`Название * · ${chars(form.title, limits.titleMax)}`} hint="На карточке — до 2 строк, дальше обрежется многоточием.">
              <input
                type="text"
                value={form.title}
                placeholder="Например: AI-мультфильмы с нуля"
                onChange={(e) => set({ title: e.target.value })}
                className={`${INPUT_LG} mt-1.5 block w-full`}
              />
            </Field>
            <Field label={`Преподаватель * · ${chars(form.teacher, limits.teacherMax)}`}>
              <input
                type="text"
                value={form.teacher}
                placeholder="Имя и фамилия автора курса"
                onChange={(e) => set({ teacher: e.target.value })}
                className={`${INPUT_LG} mt-1.5 block w-full`}
              />
            </Field>
            <Field
              label={`Краткое описание * · ${chars(form.description, limits.descriptionMax)}`}
              hint="На карточке — до 3 строк. Переводы строк станут пробелами."
            >
              <textarea
                rows={4}
                value={form.description}
                onChange={(e) => set({ description: e.target.value })}
                className={`${INPUT_LG} mt-1.5 block w-full resize-y leading-relaxed`}
              />
            </Field>
            <Field
              label="Ссылка на курс *"
              hint="Сайт преподавателя: там подробности, цена и запись. Откроется в новой вкладке."
            >
              <input
                type="url"
                inputMode="url"
                value={form.url}
                placeholder="https://example.com/kurs"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                onChange={(e) => set({ url: e.target.value })}
                onBlur={() => setUrlTouched(true)}
                className={`${INPUT_LG} mt-1.5 block w-full font-mono`}
              />
            </Field>
            {link.ok && link.href ? (
              <p className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-2">
                <span className="min-w-0 break-all">
                  Сайт: <span className="font-mono text-muted">{link.host}</span>
                </span>
                <a
                  href={link.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex min-h-9 items-center gap-1 text-accent hover:underline"
                >
                  Открыть
                  <FiExternalLink className="h-3.5 w-3.5" aria-hidden />
                </a>
              </p>
            ) : !link.ok && (urlTouched || error) ? (
              <p className="text-xs text-status-wait">{link.error}</p>
            ) : null}
          </fieldset>

          <fieldset className="min-w-0 space-y-3">
            <legend className={LEGEND}>Обложка *</legend>
            <p className="text-xs text-muted-2">
              JPG, PNG, WebP или HEIC до {maxMb} МБ, не меньше {limits.coverMinWidth}×{limits.coverMinHeight}. Лучше
              всего 1280×720 (16:9): карточка показывает обложку в рамке 16:9 и обрезает края, если пропорции другие.
            </p>
            <div className="relative aspect-video w-full overflow-hidden rounded-xl bg-surface-2">
              {coverSrc && !staged?.error ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={coverSrc} alt="" className="h-full w-full object-cover" />
              ) : (
                <div className="flex h-full w-full flex-col items-center justify-center gap-1 text-muted-2">
                  <FiImage className="h-6 w-6" aria-hidden />
                  <span className="text-[11px]">Обложки пока нет</span>
                </div>
              )}
            </div>
            {staged ? (
              <div className="space-y-1 text-xs">
                <div className="flex items-start gap-2">
                  <span className="min-w-0 flex-1 break-words text-muted">
                    {staged.file.name} · {fmtMb(staged.file.size)}
                    {staged.reading ? " · читаю размер…" : ""}
                    {staged.width > 0 ? ` · ${staged.width}×${staged.height}` : ""}
                  </span>
                  <button
                    type="button"
                    onClick={() => setStaged(null)}
                    disabled={busy !== null}
                    aria-label="Не загружать эту обложку"
                    title="Не загружать"
                    className="-m-1 flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50 sm:h-7 sm:w-7"
                  >
                    <FiX className="h-4 w-4" aria-hidden />
                  </button>
                </div>
                {staged.error ? (
                  <p className="text-status-fail">{staged.error}</p>
                ) : (
                  <>
                    {!staged.reading && staged.width === 0 && (
                      <p className="text-muted-2">Браузер не показывает этот формат — сервер переведёт его в JPG.</p>
                    )}
                    {stagedWarning && <p className="text-status-wait">{stagedWarning}</p>}
                    <p className="text-muted-2">Обложка уйдёт на сервер при сохранении.</p>
                  </>
                )}
              </div>
            ) : (
              course?.cover && (
                <p className="text-xs text-muted-2">
                  Сейчас: {course.coverWidth}×{course.coverHeight}
                  {currentWarning ? <span className="block text-status-wait">{currentWarning}</span> : null}
                </p>
              )
            )}
            <label
              className={`${btn("plain", "lg")} relative min-h-11 w-full hover:text-foreground focus-within:border-accent sm:w-auto ${
                busy !== null ? "pointer-events-none opacity-50" : ""
              }`}
            >
              <FiUpload className="h-4 w-4" aria-hidden />
              {course?.cover || staged ? "Выбрать другую обложку" : "Выбрать обложку"}
              <input
                type="file"
                accept={COVER_ACCEPT}
                disabled={busy !== null}
                className="sr-only"
                onChange={(e) => {
                  const file = e.currentTarget.files?.[0] ?? null;
                  // Тот же файл ещё раз — тоже выбор: без сброса браузер промолчит.
                  e.currentTarget.value = "";
                  if (file) void choose(file);
                }}
              />
            </label>
          </fieldset>
        </div>

        <div className="min-w-0">
          <div className={LEGEND}>Так карточка выглядит на сайте</div>
          <div className="md:sticky md:top-0">
            <CourseCard
              course={{
                title: cleanText(form.title) || "Название курса",
                teacher: cleanText(form.teacher) || "Имя преподавателя",
                description: cleanText(form.description) || "Краткое описание курса — до трёх строк на карточке.",
                href: null,
                cover: staged?.error ? null : coverSrc,
                coverThumb: null,
                coverWidth: null,
              }}
              labels={CARD_LABELS}
              eager
            />
          </div>
        </div>
      </div>
    </Dialog>
  );
}

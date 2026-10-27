"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FiExternalLink, FiPlus, FiRefreshCw } from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";
import { CARD, Notices, Skeleton, btn, chip, useNotices } from "../vstudio-showcase/parts";
import ConfirmDelete from "./ConfirmDelete";
import CourseDialog, { type Saved } from "./CourseDialog";
import CourseRow from "./CourseRow";
import SuggestLinkCard from "./SuggestLinkCard";
import {
  COURSES_PATH,
  ORDER_PATH,
  SETTINGS_PATH,
  coursePath,
  coverPath,
  errorText,
  filterCounts,
  matchesFilter,
  orderBy,
  parseCourse,
  parseList,
  parseOrder,
  parseSettings,
  placesChanged,
  publishHint,
  reorderIds,
  replaceCourse,
  type Course,
  type CourseList,
  type Filter,
} from "./academyAdmin";

/**
 * EsAI Академия (ТЗ клиента 27.10.2026): курсы страницы /academy — карточки со
 * ссылками на сайты авторов. Здесь их заводят, правят, публикуют и скрывают,
 * переставляют и удаляют; здесь же ссылка кнопки «Предложить курс». Курс
 * попадает на сайт, только когда у него есть обложка, название, преподаватель,
 * описание и годная ссылка — это проверяет сервер. Без правок кода.
 */

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "Все" },
  { key: "live", label: "На сайте" },
  { key: "draft", label: "Черновики" },
  { key: "hidden", label: "Скрытые" },
];

type DialogState = { id: number | null; seq: number };

export default function AdminAcademyPage() {
  const [tick, setTick] = useState(0);
  const [board, setBoard] = useState<CourseList | null>(null);
  const [loaded, setLoaded] = useState<{ tick: number; error: string | null } | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [busy, setBusy] = useState<ReadonlySet<number>>(new Set());
  const [ordering, setOrdering] = useState(false);
  const [dialog, setDialog] = useState<DialogState | null>(null);
  const [removing, setRemoving] = useState<Course | null>(null);
  const seq = useRef(0);
  const { list: notices, notify, close } = useNotices();

  const loading = loaded?.tick !== tick;
  const reload = useCallback(() => setTick((value) => value + 1), []);

  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await fetchData<unknown>(COURSES_PATH, "GET", undefined, true);
      if (!alive) return;
      const data = res.ok ? parseList(res.data) : null;
      if (!data) {
        setLoaded({ tick, error: errorText(res, "Не удалось загрузить курсы") });
        return;
      }
      setBoard(data);
      setLoaded({ tick, error: null });
    })();
    return () => {
      alive = false;
    };
  }, [tick]);

  const editCourses = (change: (courses: Course[]) => Course[]) =>
    setBoard((prev) => (prev ? { ...prev, courses: change(prev.courses) } : prev));

  const lock = (id: number, on: boolean) =>
    setBusy((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  /**
   * Курс с сервера встаёт на своё место. Если он появился на сайте или ушёл с
   * него, места («стр. · №») соседей сдвинулись — их знает только сервер: перечитываем.
   */
  const putCourse = (saved: Course, before: Course | null) => {
    editCourses((courses) => replaceCourse(courses, saved));
    if (before && placesChanged(before, saved)) reload();
  };

  const publish = async (course: Course, published: boolean) => {
    if (published && course.missing.length) {
      notify("fail", `«${course.title || `№${course.id}`}»: ${publishHint(course.missing).toLowerCase()}.`);
      openEdit(course);
      return;
    }
    lock(course.id, true);
    const res = await fetchData<unknown>(coursePath(course.id), "PATCH", { is_published: published }, true);
    lock(course.id, false);
    const saved = res.ok ? parseCourse(res.data) : null;
    if (!saved) {
      notify("fail", errorText(res, published ? "Не удалось опубликовать" : "Не удалось скрыть"));
      if (res.status === 404) reload();
      return;
    }
    putCourse(saved, course);
    const name = saved.title ? `«${saved.title}»` : `№${saved.id}`;
    notify(
      "ok",
      published ? `Курс ${name} опубликован — на сайте появится в течение минуты.` : `Курс ${name} скрыт с сайта.`,
    );
  };

  /** Перестановка — один запрос со всем списком; на время запроса порядок заблокирован. */
  const move = async (course: Course, to: number) => {
    if (!board || ordering) return;
    const ids = board.courses.map((c) => c.id);
    const from = ids.indexOf(course.id);
    const next = reorderIds(ids, from, to);
    if (from < 0 || next.every((id, i) => id === ids[i])) return;
    const before = board.courses;
    setOrdering(true);
    editCourses((courses) => orderBy(courses, next));
    const res = await fetchData<unknown>(ORDER_PATH, "POST", { ids: next }, true);
    setOrdering(false);
    const saved = res.ok ? parseOrder(res.data) : null;
    if (saved) {
      editCourses(() => saved);
      return;
    }
    editCourses(() => before);
    notify("fail", errorText(res, "Не удалось переставить"));
    // 409 — курсы добавили или удалили в другом окне: берём свежий список.
    if (res.status === 409) reload();
  };

  const remove = async (course: Course): Promise<string | null> => {
    const res = await fetchData<unknown>(coursePath(course.id), "DELETE", undefined, true);
    if (!res.ok && res.status !== 404) return errorText(res, "Не удалось удалить курс");
    setRemoving(null);
    editCourses((courses) => courses.filter((c) => c.id !== course.id));
    notify("ok", `Курс ${course.title ? `«${course.title}»` : `№${course.id}`} удалён.`);
    if (course.state === "live") reload();
    return null;
  };

  const createCourse = async (body: Record<string, string>): Promise<Saved> => {
    const res = await fetchData<unknown>(COURSES_PATH, "POST", body, true);
    if (!res.ok) return { course: null, error: errorText(res, "Не удалось создать курс") };
    const saved = parseCourse(res.data);
    if (!saved) {
      reload();
      return { course: null, error: "Курс создан, но ответ сервера не разобрать — закройте окно, он появится в списке." };
    }
    editCourses((courses) => replaceCourse(courses, saved));
    // Окно дальше правит созданный курс: обложка, если не уйдёт, дошлётся к нему.
    setDialog((prev) => (prev ? { ...prev, id: saved.id } : prev));
    return { course: saved, error: null };
  };

  const updateCourse = async (course: Course, changes: Record<string, unknown>): Promise<Saved> => {
    lock(course.id, true);
    const res = await fetchData<unknown>(coursePath(course.id), "PATCH", changes, true);
    lock(course.id, false);
    const saved = res.ok ? parseCourse(res.data) : null;
    if (!saved) return { course: null, error: errorText(res, "Не удалось сохранить курс") };
    putCourse(saved, course);
    return { course: saved, error: null };
  };

  const uploadCover = async (course: Course, file: File): Promise<Saved> => {
    const form = new FormData();
    form.append("file", file, file.name);
    lock(course.id, true);
    const res = await fetchData<unknown>(coverPath(course.id), "POST", form, true);
    lock(course.id, false);
    const saved = res.ok ? parseCourse(res.data) : null;
    if (!saved) return { course: null, error: errorText(res, "Не удалось загрузить обложку") };
    putCourse(saved, course);
    return { course: saved, error: null };
  };

  const saveSuggest = async (raw: string): Promise<string | null> => {
    const res = await fetchData<unknown>(SETTINGS_PATH, "PATCH", { suggest_url: raw.trim() }, true);
    const value = res.ok ? parseSettings(res.data) : null;
    if (value === null) return errorText(res, "Не удалось сохранить ссылку");
    setBoard((prev) => (prev ? { ...prev, suggestUrl: value } : prev));
    notify("ok", value ? "Ссылка сохранена — кнопка «Предложить курс» на сайте ведёт на неё." : "Кнопка «Предложить курс» убрана с сайта.");
    return null;
  };

  // Ссылки постоянные: окно вешает на них Escape и не должно перевешивать на каждый рендер.
  const closeDialog = useCallback(() => setDialog(null), []);
  const closeRemove = useCallback(() => setRemoving(null), []);
  const finishDialog = useCallback(
    (note: string) => {
      setDialog(null);
      notify("ok", note);
    },
    [notify],
  );

  const openNew = () => setDialog({ id: null, seq: ++seq.current });
  function openEdit(course: Course) {
    setDialog({ id: course.id, seq: ++seq.current });
  }

  const counts = useMemo(() => filterCounts(board?.courses ?? []), [board]);
  const shown = useMemo(() => (board ? board.courses.filter((c) => matchesFilter(c, filter)) : []), [board, filter]);
  const dialogCourse = dialog && dialog.id !== null ? (board?.courses.find((c) => c.id === dialog.id) ?? null) : null;
  const full = board ? board.courses.length >= board.limits.maxCourses : false;
  const orderHint =
    filter !== "all"
      ? "Порядок меняется во вкладке «Все»"
      : "Порядок на сайте — как здесь (среди опубликованных). Новый курс встаёт в конец";

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 max-w-3xl">
          <h1 className="text-xl font-bold">EsAI Академия</h1>
          <p className="mt-1 text-sm text-muted-2">
            Курсы страницы /academy: что видят все и в каком порядке. На сайт попадают только опубликованные курсы с
            обложкой, названием, преподавателем, описанием и ссылкой. Изменения появляются на сайте в течение минуты.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <a
            href="/academy"
            target="_blank"
            rel="noreferrer"
            className="inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs text-muted transition-colors hover:text-foreground sm:min-h-9"
          >
            <FiExternalLink className="h-3.5 w-3.5" aria-hidden />
            Открыть страницу
          </a>
          <button
            type="button"
            onClick={openNew}
            disabled={!board || full}
            title={full ? `Курсов уже ${board?.limits.maxCourses} — удалите ненужные` : undefined}
            className={`${btn("primary", "lg")} min-h-11 sm:min-h-0`}
          >
            <FiPlus className="h-4 w-4" aria-hidden />
            Новый курс
          </button>
        </div>
      </div>

      {!board && loading && (
        <div className="flex flex-col gap-4" aria-busy="true">
          <Skeleton className="h-28" />
          <Skeleton className="h-36" />
          <Skeleton className="h-36" />
        </div>
      )}

      {!board && !loading && (
        <div className={`${CARD} flex flex-col items-start gap-3 p-6`}>
          <div className="text-sm text-status-fail">{loaded?.error || "Не удалось загрузить курсы"}</div>
          <button type="button" onClick={reload} className={btn("plain", "lg")}>
            <FiRefreshCw className="h-4 w-4" aria-hidden />
            Повторить
          </button>
        </div>
      )}

      {board && (
        <>
          <SuggestLinkCard
            key={board.suggestUrl}
            value={board.suggestUrl}
            maxLength={board.limits.suggestUrlMax}
            onSave={saveSuggest}
          />

          <section className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <div role="group" aria-label="Какие курсы показать" className="flex flex-wrap items-center gap-1.5">
                {FILTERS.map((option) => (
                  <button
                    key={option.key}
                    type="button"
                    aria-pressed={filter === option.key}
                    onClick={() => setFilter(option.key)}
                    className={`${chip(filter === option.key)} min-h-11 sm:min-h-9`}
                  >
                    {option.label} ({counts[option.key]})
                  </button>
                ))}
              </div>
              <button type="button" onClick={reload} disabled={loading} className={`${btn()} ml-auto min-h-11 sm:min-h-9`}>
                <FiRefreshCw className={`h-3.5 w-3.5 ${loading ? "motion-safe:animate-spin" : ""}`} aria-hidden />
                Обновить
              </button>
            </div>

            {loaded?.error && !loading && (
              <div className="flex flex-wrap items-center gap-3 text-sm text-status-fail">
                {loaded.error}
                <button type="button" onClick={reload} className={btn()}>
                  Повторить
                </button>
              </div>
            )}

            {board.courses.length === 0 ? (
              <div className={`${CARD} p-6 text-center text-sm text-muted-2`}>
                Курсов пока нет — на сайте показано «Курсы скоро появятся». Нажмите «Новый курс»: сохраните черновик,
                загрузите обложку и опубликуйте.
              </div>
            ) : shown.length === 0 ? (
              <div className={`${CARD} flex flex-col items-center gap-3 p-6 text-center text-sm text-muted-2`}>
                Здесь пусто.
                <button type="button" onClick={() => setFilter("all")} className={btn()}>
                  Показать все
                </button>
              </div>
            ) : (
              <ul aria-busy={loading || ordering} className={`flex flex-col gap-3 transition-opacity ${loading ? "opacity-60" : ""}`}>
                {shown.map((course) => {
                  const index = board.courses.indexOf(course);
                  return (
                    <CourseRow
                      key={course.id}
                      course={course}
                      index={index}
                      total={board.courses.length}
                      busy={busy.has(course.id)}
                      orderLocked={ordering || filter !== "all"}
                      orderHint={orderHint}
                      onMove={(target, to) => void move(target, to)}
                      onPublish={(target, published) => void publish(target, published)}
                      onEdit={openEdit}
                      onDelete={setRemoving}
                    />
                  );
                })}
              </ul>
            )}
          </section>
        </>
      )}

      {/* Окно курса, который тем временем удалили, не показываем: править уже нечего. */}
      {dialog && board && (dialog.id === null || dialogCourse) && (
        <CourseDialog
          key={dialog.seq}
          course={dialogCourse}
          limits={board.limits}
          onCreate={createCourse}
          onUpdate={updateCourse}
          onUpload={uploadCover}
          onDone={finishDialog}
          onClose={closeDialog}
        />
      )}

      {removing && <ConfirmDelete course={removing} onConfirm={remove} onClose={closeRemove} />}

      <Notices list={notices} onClose={close} />
    </div>
  );
}

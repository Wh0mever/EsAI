"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { FiExternalLink, FiPlus, FiRefreshCw } from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";
import { CARD, INPUT, Notices, Skeleton, btn, chip, useNotices } from "../vstudio-showcase/parts";
import SceneDialog, { type Saved } from "./SceneDialog";
import SceneRow from "./SceneRow";
import SectionDialog from "./SectionDialog";
import SectionsPanel from "./SectionsPanel";
import {
  NO_FILTERS,
  SCENES_PATH,
  afterPoll,
  SECTIONS_PATH,
  buildingIds,
  errorText,
  filterScenes,
  filtersActive,
  formFromScene,
  groupScenes,
  newSceneForm,
  parseList,
  parseScene,
  parseSection,
  pollEach,
  pollList,
  previewPath,
  publishNote,
  rebuildPath,
  replaceScene,
  replaceSection,
  sceneFromParams,
  scenePath,
  sceneStats,
  scenesAfterSection,
  sectionCounts,
  sectionWith,
  sectionName,
  sectionOption,
  sectionPath,
  sortError,
  sortSections,
  typedSort,
  type Filters,
  type PollResult,
  type Scene,
  type SceneForm,
  type SceneList,
  type Section,
  type Tri,
} from "./scenesAdmin";

/**
 * Сцены мультстудии.
 *
 * Клиент (12.10.2026): владелец сам добавляет и публикует сцены библиотеки,
 * а пользователи выбирают их для своих мультфильмов. Раньше сцены жили в коде
 * (cartoon/library.py) и заводились командами по SSH. Здесь — вся библиотека
 * по разделам: названия на трёх языках, раздел, аудитория, «Выбор EsAI»,
 * порядок, формат, английские промпты для моделей и ролик превью, из которого
 * сервер сам делает лёгкие копии. Сцену, которую уже взяли в мультфильмы, не
 * удаляют — снимают с публикации. ?scene=<id> открывает сцену сразу: туда
 * ведёт «Опубликовать как новую сцену» из «Работ».
 *
 * useSearchParams требует границы Suspense (иначе сборка не сможет
 * пререндерить страницу).
 */
export default function AdminStudioScenesPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <ScenesPage />
    </Suspense>
  );
}

function PageSkeleton() {
  return (
    <div className="flex flex-col gap-4" aria-busy="true">
      <Skeleton className="h-16" />
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-20" />
        ))}
      </div>
      <Skeleton className="h-40" />
      <Skeleton className="h-36" />
      <Skeleton className="h-36" />
    </div>
  );
}

/** Как часто спрашивать сервер, собралось ли превью. */
const POLL_MS = 3000;
/** Больше сборок разом — один запрос всего списка вместо запроса на каждую: у панели общий лимит запросов. */
const POLL_ONE_BY_ONE = 3;

type SceneDialogState = { id: number | null; seq: number; initial: SceneForm };
type SectionDialogState = { section: Section | null; seq: number };

const TRI_PUBLISHED: { key: Tri; label: string }[] = [
  { key: "all", label: "Все" },
  { key: "yes", label: "Опубликованы" },
  { key: "no", label: "Не опубликованы" },
];
const TRI_PICK: { key: Tri; label: string }[] = [
  { key: "all", label: "Все" },
  { key: "yes", label: "«Выбор EsAI»" },
  { key: "no", label: "Без «Выбора»" },
];

function ScenesPage() {
  // Адрес читаем у роутера: при переходе по ссылке из «Работ» адрес в самом
  // окне браузера на первом рендере ещё прошлый (см. payments/filters.ts).
  const searchParams = useSearchParams();
  const wanted = sceneFromParams(searchParams);

  const [tick, setTick] = useState(0);
  const [board, setBoard] = useState<SceneList | null>(null);
  const [loaded, setLoaded] = useState<{ tick: number; error: string | null } | null>(null);
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [busy, setBusy] = useState<ReadonlySet<number>>(new Set());
  const [sectionBusy, setSectionBusy] = useState<ReadonlySet<number>>(new Set());
  const [dialog, setDialog] = useState<SceneDialogState | null>(null);
  const [sectionDialog, setSectionDialog] = useState<SectionDialogState | null>(null);
  const [poll, setPoll] = useState(0);
  const seq = useRef(0);
  // Какую ссылку ?scene= уже открывали: перечитка списка не должна открывать окно снова.
  const linked = useRef<number | null>(null);
  const { list: notices, notify, close } = useNotices();

  const loading = loaded?.tick !== tick;
  const reload = () => setTick((value) => value + 1);

  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await fetchData<unknown>(SCENES_PATH, "GET", undefined, true);
      if (!alive) return;
      const data = res.ok ? parseList(res.data) : null;
      if (!data) {
        setLoaded({ tick, error: errorText(res, "Не удалось загрузить сцены") });
        return;
      }
      setBoard(data);
      setLoaded({ tick, error: null });
      if (wanted === null || linked.current === wanted) return;
      linked.current = wanted;
      const scene = data.scenes.find((s) => s.id === wanted);
      if (scene) setDialog({ id: scene.id, seq: ++seq.current, initial: formFromScene(scene) });
      else notify("fail", `Сцена №${wanted} не найдена — возможно, её уже удалили.`);
    })();
    return () => {
      alive = false;
    };
  }, [tick, wanted, notify]);

  // Один ролик за раз: запустили следующий — предыдущий замолкает.
  useEffect(() => {
    const onPlay = (event: Event) => {
      for (const video of document.querySelectorAll("video")) {
        if (video !== event.target) video.pause();
      }
    };
    document.addEventListener("play", onPlay, true);
    return () => document.removeEventListener("play", onPlay, true);
  }, []);

  // Пока у сцен собирается превью, спрашиваем сервер, готово ли. Во фоновой
  // вкладке не спрашиваем: смотреть некому, а лимит запросов у панели общий.
  const buildingKey = useMemo(() => (board ? buildingIds(board.scenes) : []).join(","), [board]);
  useEffect(() => {
    if (!buildingKey) return;
    let alive = true;
    const timer = setTimeout(async () => {
      if (document.visibilityState !== "hidden") {
        const ids = buildingKey.split(",").map(Number);
        let result: PollResult = { fresh: [], gone: [] };
        if (ids.length <= POLL_ONE_BY_ONE) {
          const answers = await Promise.all(ids.map((id) => fetchData<unknown>(scenePath(id), "GET", undefined, true)));
          result = pollEach(ids, answers);
        } else {
          const res = await fetchData<unknown>(SCENES_PATH, "GET", undefined, true);
          const data = res.ok ? parseList(res.data) : null;
          if (data) result = pollList(ids, data);
        }
        if (!alive) return;
        const { fresh, gone } = result;
        setBoard((prev) => prev && { ...prev, scenes: afterPoll(prev.scenes, result) });
        // Открытое окно такой сцены закрывается само — пусть будет видно почему.
        if (gone.length === 1) notify("fail", `Сцену №${gone[0]} удалили в другом окне — она убрана из списка.`);
        else if (gone.length > 1) {
          notify("fail", `Сцены ${gone.map((id) => `№${id}`).join(", ")} удалили в другом окне — они убраны из списка.`);
        }
        for (const scene of fresh) {
          if (scene.preview.state === "ready") notify("ok", `Превью собрано: «${scene.title}».`);
          else if (scene.preview.state === "partial") {
            const why = scene.preview.notes.join(". ") || "лёгкой копии или обложки нет";
            notify("fail", `Превью «${scene.title}» собралось не полностью: ${why}.`);
          }
        }
      }
      if (alive) setPoll((n) => n + 1);
    }, POLL_MS);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [buildingKey, poll, notify]);

  const editScenes = (change: (scenes: Scene[]) => Scene[]) =>
    setBoard((prev) => (prev ? { ...prev, scenes: change(prev.scenes) } : prev));

  /** Сцена с сервера встаёт на своё место; удалённую за это время не возвращаем. */
  const putScene = (saved: Scene) => editScenes((scenes) => scenes.map((s) => (s.id === saved.id ? saved : s)));

  const applySection = (saved: Section) =>
    setBoard((prev) =>
      prev
        ? { ...prev, sections: replaceSection(prev.sections, saved), scenes: scenesAfterSection(prev.scenes, saved) }
        : prev,
    );

  const lock = (setter: typeof setBusy, id: number, on: boolean) =>
    setter((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  /**
   * Быстрая правка из строки. Переключатель меняется сразу; сервер не принял —
   * возвращаем только эти поля: превью за это время мог обновить опрос.
   */
  const patchScene = async (
    scene: Scene,
    body: Record<string, unknown>,
    shown: Partial<Scene>,
    undo: Partial<Scene>,
  ): Promise<Scene | null> => {
    lock(setBusy, scene.id, true);
    editScenes((scenes) => scenes.map((s) => (s.id === scene.id ? { ...s, ...shown } : s)));
    const res = await fetchData<unknown>(scenePath(scene.id), "PATCH", body, true);
    lock(setBusy, scene.id, false);
    if (!res.ok) {
      editScenes((scenes) => scenes.map((s) => (s.id === scene.id ? { ...s, ...undo } : s)));
      notify("fail", errorText(res, "Не удалось сохранить"));
      if (res.status === 404) reload();
      return null;
    }
    const saved = parseScene(res.data);
    if (saved) putScene(saved);
    else reload();
    return saved;
  };

  const publish = async (scene: Scene, published: boolean) => {
    const saved = await patchScene(scene, { is_active: published }, { published }, { published: scene.published });
    if (saved) notify("ok", publishNote(saved));
  };

  const pick = (scene: Scene, value: boolean) =>
    void patchScene(scene, { is_pick: value }, { pick: value }, { pick: scene.pick });

  /** false — набрано не число: строка вернёт в поле прежний порядок. */
  const sortScene = (scene: Scene, typed: string): boolean => {
    if (!board) return false;
    const sort = typedSort(typed, board.limits);
    if (sort === null) {
      notify("fail", sortError(board.limits));
      return false;
    }
    void patchScene(scene, { sort_order: sort }, { sort }, { sort: scene.sort });
    return true;
  };

  const remove = async (scene: Scene) => {
    if (!scene.canDelete) {
      notify(
        "fail",
        `Сцену «${scene.title}» уже взяли в мультфильмы (${scene.usedIn}) — удалить нельзя. Снимите её с публикации: из библиотеки она пропадёт, а готовые мультфильмы останутся целы.`,
      );
      return;
    }
    if (!confirm(`Удалить сцену «${scene.title}» насовсем? В мультфильмы её ещё не брали; вернуть её будет нельзя.`)) {
      return;
    }
    lock(setBusy, scene.id, true);
    const res = await fetchData<unknown>(scenePath(scene.id), "DELETE", undefined, true);
    lock(setBusy, scene.id, false);
    if (!res.ok) {
      notify("fail", errorText(res, "Не удалось удалить сцену"));
      // 409 — сцену успели взять в мультфильм: перечитываем, чтобы строка это показала.
      if (res.status === 409 || res.status === 404) reload();
      return;
    }
    editScenes((scenes) => scenes.filter((s) => s.id !== scene.id));
    notify("ok", `Сцена удалена: «${scene.title}».`);
  };

  const rebuild = async (scene: Scene): Promise<Saved> => {
    lock(setBusy, scene.id, true);
    const res = await fetchData<unknown>(rebuildPath(scene.id), "POST", {}, true);
    lock(setBusy, scene.id, false);
    const saved = res.ok ? parseScene(res.data) : null;
    if (!saved) return { scene: null, error: errorText(res, "Не удалось пересобрать превью") };
    putScene(saved);
    return { scene: saved, error: null };
  };

  const rebuildFromRow = async (scene: Scene) => {
    const res = await rebuild(scene);
    if (res.error) notify("fail", res.error);
    else notify("ok", `Превью «${scene.title}» пересобирается — это пара минут.`);
  };

  const createScene = async (body: Record<string, unknown>): Promise<Saved> => {
    const res = await fetchData<unknown>(SCENES_PATH, "POST", body, true);
    if (!res.ok) return { scene: null, error: errorText(res, "Не удалось создать сцену") };
    const saved = parseScene(res.data);
    if (!saved) {
      reload();
      return { scene: null, error: "Сцена создана, но ответ сервера не разобрать — закройте окно, она появится в списке." };
    }
    editScenes((scenes) => replaceScene(scenes, saved));
    // Окно дальше правит созданную сцену: ролик, если не уйдёт, дошлётся к ней.
    setDialog((prev) => (prev ? { ...prev, id: saved.id } : prev));
    return { scene: saved, error: null };
  };

  const updateScene = async (scene: Scene, changes: Record<string, unknown>): Promise<Saved> => {
    lock(setBusy, scene.id, true);
    const res = await fetchData<unknown>(scenePath(scene.id), "PATCH", changes, true);
    lock(setBusy, scene.id, false);
    const saved = res.ok ? parseScene(res.data) : null;
    if (!saved) return { scene: null, error: errorText(res, "Не удалось сохранить сцену") };
    putScene(saved);
    return { scene: saved, error: null };
  };

  const uploadPreview = async (scene: Scene, file: File): Promise<Saved> => {
    const form = new FormData();
    form.append("file", file, file.name);
    lock(setBusy, scene.id, true);
    const res = await fetchData<unknown>(previewPath(scene.id), "POST", form, true);
    lock(setBusy, scene.id, false);
    const saved = res.ok ? parseScene(res.data) : null;
    if (!saved) return { scene: null, error: errorText(res, "Не удалось загрузить ролик") };
    putScene(saved);
    return { scene: saved, error: null };
  };

  const submitSection = async (section: Section | null, body: Record<string, unknown>): Promise<string | null> => {
    const res = await fetchData<unknown>(
      section ? sectionPath(section.id) : SECTIONS_PATH,
      section ? "PATCH" : "POST",
      body,
      true,
    );
    if (!res.ok) return errorText(res, section ? "Не удалось сохранить раздел" : "Не удалось создать раздел");
    const saved = parseSection(res.data);
    if (saved) applySection(saved);
    else reload();
    const name = `«${saved?.title ?? section?.title ?? ""}»`;
    notify(
      "ok",
      section ? `Раздел сохранён: ${name}.` : `Раздел создан: ${name}. Ставьте в него сцены полем «Раздел» в окне сцены.`,
    );
    return null;
  };

  const patchSection = async (section: Section, body: Record<string, unknown>): Promise<Section | null> => {
    lock(setSectionBusy, section.id, true);
    const res = await fetchData<unknown>(sectionPath(section.id), "PATCH", body, true);
    lock(setSectionBusy, section.id, false);
    if (!res.ok) {
      notify("fail", errorText(res, "Не удалось сохранить раздел"));
      return null;
    }
    const saved = parseSection(res.data);
    if (saved) applySection(saved);
    else reload();
    return saved;
  };

  const counts = useMemo(() => sectionCounts(board?.scenes ?? []), [board]);

  const toggleSection = async (section: Section, visible: boolean) => {
    const shown = counts.get(section.id)?.published ?? 0;
    if (!visible && shown > 0) {
      const ok = confirm(
        `Скрыть раздел «${section.title}»? С сайта пропадут и его сцены (опубликованных: ${shown}). Готовые мультфильмы останутся целы.`,
      );
      if (!ok) return;
    }
    const saved = await patchSection(section, { is_active: visible });
    if (saved) notify("ok", visible ? `Раздел снова на сайте: «${saved.title}».` : `Раздел скрыт: «${saved.title}».`);
  };

  const editSections = (change: (list: Section[]) => Section[]) =>
    setBoard((prev) => (prev ? { ...prev, sections: change(prev.sections) } : prev));

  const sortSection = (section: Section, typed: string): boolean => {
    if (!board) return false;
    const sort = typedSort(typed, board.limits);
    if (sort === null) {
      notify("fail", sortError(board.limits));
      return false;
    }
    // Как у сцен: порядок встаёт сразу, а отказ сервера возвращает прежний — и в
    // поле тоже, иначе там осталось бы число, которое не сохранилось.
    editSections((list) => sectionWith(list, section.id, { sort }));
    void patchSection(section, { sort_order: sort }).then((saved) => {
      if (!saved) editSections((list) => sectionWith(list, section.id, { sort: section.sort }));
    });
    return true;
  };

  // Ссылки постоянные: окна вешают на них Escape и не должны перевешивать на каждый рендер.
  const closeDialog = useCallback(() => setDialog(null), []);
  const closeSectionDialog = useCallback(() => setSectionDialog(null), []);
  const finishDialog = useCallback(
    (note: string | null) => {
      setDialog(null);
      if (note) notify("ok", note);
    },
    [notify],
  );

  const openNew = () => {
    if (!board) return;
    setDialog({ id: null, seq: ++seq.current, initial: newSceneForm(board.limits, filters) });
  };
  const openEdit = (scene: Scene) => setDialog({ id: scene.id, seq: ++seq.current, initial: formFromScene(scene) });

  const sections = useMemo(() => sortSections(board?.sections ?? []), [board]);
  const shown = useMemo(() => (board ? filterScenes(board.scenes, filters) : []), [board, filters]);
  const groups = useMemo(() => groupScenes(shown, sections), [shown, sections]);
  const stats = useMemo(() => sceneStats(board?.scenes ?? []), [board]);
  const dialogScene = dialog && dialog.id !== null ? (board?.scenes.find((s) => s.id === dialog.id) ?? null) : null;
  const narrowed = filtersActive(filters);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 max-w-3xl">
          <h1 className="text-xl font-bold">Сцены мультстудии</h1>
          <p className="mt-1 text-sm text-muted-2">
            Библиотека готовых сцен, из которых пользователи собирают мультфильмы. Добавляйте сцены, загружайте ролик
            превью и публикуйте: опубликованная сцена с превью сразу видна в библиотеке. Разделы — вкладки
            библиотеки. Сцену, которую уже взяли в мультфильмы, удалить нельзя — её снимают с публикации.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <a
            href="/studio"
            target="_blank"
            rel="noreferrer"
            className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs text-muted transition-colors hover:text-foreground"
          >
            <FiExternalLink className="h-3.5 w-3.5" aria-hidden />
            Открыть мультстудию
          </a>
          <button type="button" onClick={openNew} disabled={!board} className={btn("primary", "lg")}>
            <FiPlus className="h-4 w-4" aria-hidden />
            Новая сцена
          </button>
        </div>
      </div>

      {!board && loading && <PageSkeleton />}

      {!board && !loading && (
        <div className={`${CARD} flex flex-col items-start gap-3 p-6`}>
          <div className="text-sm text-status-fail">{loaded?.error || "Не удалось загрузить сцены"}</div>
          <button type="button" onClick={reload} className={btn("plain", "lg")}>
            <FiRefreshCw className="h-4 w-4" aria-hidden />
            Повторить
          </button>
        </div>
      )}

      {board && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Сцен" value={stats.total} />
            <Stat label="В библиотеке" value={stats.live} />
            <Stat
              label="Опубликованы, не видны"
              value={stats.stuck}
              hint="без превью или в скрытом разделе"
              warn={stats.stuck > 0}
            />
            <Stat label="Не опубликованы" value={stats.unpublished} />
          </div>

          <SectionsPanel
            sections={sections}
            counts={counts}
            busy={sectionBusy}
            active={typeof filters.section === "number" ? filters.section : null}
            onVisible={(section, visible) => void toggleSection(section, visible)}
            onSort={sortSection}
            onEdit={(section) => setSectionDialog({ section, seq: ++seq.current })}
            onShow={(section) =>
              setFilters((prev) => ({ ...prev, section: prev.section === section.id ? "all" : section.id }))
            }
            onCreate={() => setSectionDialog({ section: null, seq: ++seq.current })}
          />

          <section className="flex flex-col gap-3">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h2 className="text-base font-semibold">Сцены</h2>
              <span className="text-xs text-muted-2">
                По разделам, в порядке библиотеки: меньше число «Порядок» — выше в разделе.
              </span>
            </div>

            <div className="flex flex-col gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={String(filters.section)}
                  aria-label="Раздел"
                  onChange={(e) => {
                    const value = e.target.value;
                    const section = value === "all" || value === "none" ? value : Number(value);
                    setFilters((prev) => ({ ...prev, section }));
                  }}
                  className={`${INPUT} min-h-9 max-w-full cursor-pointer`}
                >
                  <option value="all">Все разделы</option>
                  {sections.map((section) => (
                    <option key={section.id} value={section.id}>
                      {sectionOption(section)}
                    </option>
                  ))}
                  <option value="none">Без раздела</option>
                </select>
                <ChipGroup<Filters["audience"]>
                  label="Для кого"
                  options={[{ key: "all", label: "Все" }, ...board.audiences]}
                  value={filters.audience}
                  onChange={(audience) => setFilters((prev) => ({ ...prev, audience }))}
                />
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <ChipGroup
                  label="Публикация"
                  options={TRI_PUBLISHED}
                  value={filters.published}
                  onChange={(published) => setFilters((prev) => ({ ...prev, published }))}
                />
                <span className="mx-1 hidden h-5 w-px bg-border sm:inline-block" aria-hidden />
                <ChipGroup
                  label="«Выбор EsAI»"
                  options={TRI_PICK}
                  value={filters.pick}
                  onChange={(value) => setFilters((prev) => ({ ...prev, pick: value }))}
                />
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <input
                  type="search"
                  value={filters.q}
                  onChange={(e) => {
                    const q = e.target.value;
                    setFilters((prev) => ({ ...prev, q }));
                  }}
                  placeholder="название, код или текст промпта"
                  aria-label="Поиск по сценам"
                  maxLength={200}
                  className={`${INPUT} min-h-9 min-w-0 flex-1 sm:w-80 sm:flex-none`}
                />
                {narrowed && (
                  <button type="button" onClick={() => setFilters(NO_FILTERS)} className={`${btn()} min-h-9`}>
                    Сбросить фильтры
                  </button>
                )}
                <button type="button" onClick={reload} disabled={loading} className={`${btn()} min-h-9`}>
                  <FiRefreshCw className={`h-3.5 w-3.5 ${loading ? "motion-safe:animate-spin" : ""}`} aria-hidden />
                  Обновить
                </button>
              </div>
              <div className="text-xs text-muted-2" role="status">
                {narrowed ? `Показано ${shown.length} из ${board.scenes.length}` : `Всего сцен: ${board.scenes.length}`}
              </div>
            </div>

            {loaded?.error && !loading && (
              <div className="flex flex-wrap items-center gap-3 text-sm text-status-fail">
                {loaded.error}
                <button type="button" onClick={reload} className={btn()}>
                  Повторить
                </button>
              </div>
            )}

            {board.scenes.length === 0 ? (
              <div className={`${CARD} p-6 text-center text-sm text-muted-2`}>
                В библиотеке пока нет сцен. Нажмите «Новая сцена» — или опубликуйте удачную «свою сцену»
                пользователя из «Работ».
              </div>
            ) : shown.length === 0 ? (
              <div className={`${CARD} flex flex-col items-center gap-3 p-6 text-center text-sm text-muted-2`}>
                Под эти фильтры сцен нет.
                <button type="button" onClick={() => setFilters(NO_FILTERS)} className={btn()}>
                  Сбросить фильтры
                </button>
              </div>
            ) : (
              <div aria-busy={loading} className={`flex flex-col gap-5 transition-opacity ${loading ? "opacity-60" : ""}`}>
                {groups.map((group) => (
                  <div key={group.section?.id ?? "none"} className="flex flex-col gap-3">
                    <h3 className="flex flex-wrap items-baseline gap-x-2 text-sm font-semibold">
                      {group.section ? sectionName(group.section) || group.section.slug : "Без раздела"}
                      <span className="text-xs font-normal text-muted-2">
                        {group.section && !group.section.visible ? "раздел скрыт · " : ""}
                        {group.section ? "" : "видны только во «Всех» · "}
                        {group.scenes.length}
                      </span>
                    </h3>
                    <ul className="flex flex-col gap-3">
                      {group.scenes.map((scene) => (
                        <SceneRow
                          key={scene.id}
                          scene={scene}
                          audiences={board.audiences}
                          busy={busy.has(scene.id)}
                          onPublish={(target, published) => void publish(target, published)}
                          onPick={pick}
                          onSort={sortScene}
                          onRebuild={(target) => void rebuildFromRow(target)}
                          onEdit={openEdit}
                          onDelete={(target) => void remove(target)}
                        />
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      )}

      {/* Окно сцены, которую тем временем удалили, не показываем: править уже нечего. */}
      {dialog && board && (dialog.id === null || dialogScene) && (
        <SceneDialog
          key={dialog.seq}
          scene={dialogScene}
          initial={dialog.initial}
          sections={sections}
          audiences={board.audiences}
          aspects={board.aspects}
          limits={board.limits}
          onCreate={createScene}
          onUpdate={updateScene}
          onUpload={uploadPreview}
          onRebuild={rebuild}
          onDone={finishDialog}
          onClose={closeDialog}
        />
      )}

      {sectionDialog && board && (
        <SectionDialog
          key={sectionDialog.seq}
          section={sectionDialog.section}
          limits={board.limits}
          onSubmit={submitSection}
          onClose={closeSectionDialog}
        />
      )}

      <Notices list={notices} onClose={close} />
    </div>
  );
}

function ChipGroup<K extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: readonly { key: K; label: string }[];
  value: K;
  onChange: (key: K) => void;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap items-center gap-1.5">
      {options.map((option) => (
        <button
          key={option.key}
          type="button"
          aria-pressed={value === option.key}
          onClick={() => onChange(option.key)}
          className={`${chip(value === option.key)} min-h-9`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function Stat({ label, value, hint, warn = false }: { label: string; value: number; hint?: string; warn?: boolean }) {
  return (
    <div className={`${CARD} p-3 sm:p-4`} title={hint}>
      <div className="text-xs text-muted-2">{label}</div>
      <div className={`mt-1 text-2xl font-bold tabular-nums ${warn ? "text-status-wait" : ""}`}>{value}</div>
    </div>
  );
}

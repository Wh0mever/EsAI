"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { FiExternalLink, FiRefreshCw } from "react-icons/fi";
import { REEL_MIN, REEL_SIZE } from "@/components/vstudio/home/showreelData";
import { fetchData } from "@/tools/fetchData";
import AddDialog from "./AddDialog";
import CandidateCard from "./CandidateCard";
import ItemRow from "./ItemRow";
import ScenarioBoard from "./ScenarioBoard";
import { CARD, INPUT, Notices, Skeleton, btn, chip, useNotices } from "./parts";
import {
  SHOWCASE_PATH,
  addBody,
  applyMove,
  carousel,
  errorText,
  insertItem,
  itemPath,
  listPath,
  nextPage,
  parseItem,
  parseList,
  patchBody,
  placesOf,
  planMove,
  previousOf,
  sortForNew,
  type AddForm,
  type Candidate,
  type Category,
  type ItemChanges,
  type ShowcaseItem,
} from "./showcaseAdmin";

/**
 * Витрина видеостудии.
 *
 * Первый экран /video-studio показывает карусель настоящих роликов студии — по
 * одному на сценарий («Киносцена», «Реклама товара»…). Что увидят посетители,
 * решает владелец здесь: сверху — какие сценарии уже заняты, под ними сама
 * витрина (название, сценарий, порядок, показ запроса), ниже — готовые дубли,
 * которые в неё можно поставить. По умолчанию кандидаты — работы сотрудников:
 * их снимают для витрины, и вопроса о согласии автора нет. Работу пользователя
 * сервер в витрину пока не примет: в адресе её файла виден номер аккаунта
 * автора.
 */

type Board = { items: ShowcaseItem[]; categories: Category[]; publicLimit: number };

type Candidates = {
  /** Каким запросом получен список; не совпадает с текущим — идёт загрузка. */
  key: string | null;
  rows: Candidate[];
  count: number;
  pageSize: number;
  error: string | null;
};

const NO_CANDIDATES: Candidates = { key: null, rows: [], count: 0, pageSize: 50, error: null };

export default function AdminVStudioShowcasePage() {
  const [staffOnly, setStaffOnly] = useState(true);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [tick, setTick] = useState(0);
  const key = `${staffOnly ? "staff" : "all"}|${search}#${tick}`;

  const [board, setBoard] = useState<Board | null>(null);
  const [list, setList] = useState<Candidates>(NO_CANDIDATES);
  const [loadingMore, setLoadingMore] = useState(false);
  const [busy, setBusy] = useState<ReadonlySet<number>>(new Set());
  const [ordering, setOrdering] = useState(false);
  const [adding, setAdding] = useState<Candidate | null>(null);
  const { list: notices, notify, close } = useNotices();

  // Один запрос отдаёт и витрину, и кандидатов. Ответ на устаревший фильтр
  // отбрасываем: чипы переключают быстрее, чем отвечает сервер.
  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await fetchData<unknown>(listPath({ staffOnly, search, page: 1 }), "GET", undefined, true);
      if (!alive) return;
      const data = res.ok ? parseList(res.data) : null;
      if (data) {
        setBoard({ items: data.items, categories: data.categories, publicLimit: data.publicLimit });
        setList({ key, rows: data.candidates, count: data.count, pageSize: data.pageSize, error: null });
      } else {
        setList({ ...NO_CANDIDATES, key, error: errorText(res, "Не удалось загрузить витрину") });
      }
    })();
    return () => {
      alive = false;
    };
  }, [staffOnly, search, key]);

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

  // Карусель считаем здесь тем же правилом, что сайт: сервер знает только,
  // отдана ли работа, а кто из отданных попал в двенадцать — решает первый экран.
  const reel = useMemo(
    () => carousel(board?.items ?? [], { limit: board?.publicLimit ?? 0, size: REEL_SIZE, min: REEL_MIN }),
    [board],
  );
  const places = useMemo(() => placesOf(board?.items ?? [], board?.publicLimit ?? 0, reel), [board, reel]);

  const loading = list.key !== key;
  const reload = () => setTick((value) => value + 1);
  // Ссылка постоянная: окно вешает на неё Escape и не должно перевешивать на каждый рендер.
  const closeDialog = useCallback(() => setAdding(null), []);

  const editItems = (change: (items: ShowcaseItem[]) => ShowcaseItem[]) =>
    setBoard((prev) => (prev ? { ...prev, items: change(prev.items) } : prev));

  const lock = (id: number, on: boolean) =>
    setBusy((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  const patch = async (item: ShowcaseItem, changes: ItemChanges) => {
    lock(item.id, true);
    editItems((items) => items.map((x) => (x.id === item.id ? { ...x, ...changes } : x)));
    const res = await fetchData<unknown>(itemPath(item.id), "PATCH", patchBody(changes), true);
    lock(item.id, false);
    if (!res.ok) {
      const undo = previousOf(item, changes);
      editItems((items) => items.map((x) => (x.id === item.id ? { ...x, ...undo } : x)));
      notify("fail", errorText(res, "Не удалось сохранить"));
      return;
    }
    // Сервер мог поправить название (лишние пробелы) — берём его строку. sort
    // оставляем свой: его в это время могла менять перестановка.
    const saved = parseItem(res.data);
    if (saved) editItems((items) => items.map((x) => (x.id === saved.id ? { ...saved, sort: x.sort } : x)));
  };

  const move = async (item: ShowcaseItem, index: number) => {
    if (!board) return;
    const before = board.items;
    const plan = planMove(before, item.id, index);
    if (!plan) return;
    setOrdering(true);
    editItems((items) => applyMove(items, plan));
    let failure: string | null = null;
    for (const [id, sort] of plan.sorts) {
      const res = await fetchData<unknown>(itemPath(id), "PATCH", patchBody({ sort }), true);
      if (!res.ok) {
        failure = errorText(res, "Не удалось сохранить порядок");
        break;
      }
    }
    setOrdering(false);
    if (failure) {
      // Часть записей могла пройти — как теперь стоит витрина, знает только сервер.
      notify("fail", failure);
      editItems(() => before);
      reload();
    } else if (plan.sorts.size > 1) {
      // Нумерация всего списка шла долго: сверяемся с сервером, вдруг витрину правили рядом.
      reload();
    }
  };

  const remove = async (item: ShowcaseItem) => {
    const name = item.title ? `«${item.title}»` : "работу без названия";
    if (!confirm(`Убрать ${name} из витрины? Сам дубль и его файл останутся у автора.`)) return;
    lock(item.id, true);
    const res = await fetchData<unknown>(itemPath(item.id), "DELETE", undefined, true);
    lock(item.id, false);
    if (!res.ok) {
      notify("fail", errorText(res, "Не удалось убрать работу"));
      return;
    }
    editItems((items) => items.filter((x) => x.id !== item.id));
    notify("ok", item.title ? `Убрано из витрины: «${item.title}»` : "Убрано из витрины");
    // Дубль снова кандидат — перечитываем список, чтобы он появился ниже.
    reload();
  };

  const add = async (candidate: Candidate, form: AddForm): Promise<string | null> => {
    const body = addBody(candidate.takeUid, form, sortForNew(board?.items ?? []));
    const res = await fetchData<unknown>(SHOWCASE_PATH, "POST", body, true);
    if (!res.ok) return errorText(res, "Не удалось добавить в витрину");
    const saved = parseItem(res.data);
    if (saved) editItems((items) => insertItem(items, saved));
    else reload();
    setList((prev) => {
      const rows = prev.rows.filter((c) => c.takeUid !== candidate.takeUid);
      return { ...prev, rows, count: Math.max(prev.count - (prev.rows.length - rows.length), rows.length) };
    });
    // 200 вместо 201 — дубль успел поставить кто-то другой: его строка осталась как была.
    if (res.status !== 201) {
      notify("ok", "Этот дубль уже стоит в витрине — название и сценарий остались прежними.");
      return null;
    }
    const place = saved ? insertItem(board?.items ?? [], saved).findIndex((x) => x.id === saved.id) + 1 : 0;
    const where = place === 1 ? " Стоит первой — переставьте, если нужно." : place > 1 ? ` Место в списке: ${place}.` : "";
    notify("ok", `В витрине: «${saved?.title || form.title.trim()}».${where}`);
    return null;
  };

  const more = async () => {
    if (loadingMore) return;
    setLoadingMore(true);
    const page = nextPage(list.rows.length, list.pageSize);
    const res = await fetchData<unknown>(listPath({ staffOnly, search, page }), "GET", undefined, true);
    setLoadingMore(false);
    const data = res.ok ? parseList(res.data) : null;
    if (!data) {
      notify("fail", errorText(res, "Не удалось загрузить ещё"));
      return;
    }
    // Пока страница шла, фильтр могли сменить — к чужому списку её не приклеиваем.
    setList((prev) => {
      if (prev.key !== key) return prev;
      const seen = new Set(prev.rows.map((c) => c.takeUid));
      const fresh = data.candidates.filter((c) => !seen.has(c.takeUid));
      const rows = [...prev.rows, ...fresh];
      // Ничего нового при «есть ещё» — список на сервере сдвинулся: кнопку прячем, «Обновить» перечитает.
      return { ...prev, rows, count: fresh.length ? Math.max(data.count, rows.length) : rows.length };
    });
  };

  const items = board?.items ?? [];
  const shown = items.filter((item) => places.get(item.id) === "reel");

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 max-w-3xl">
          <h1 className="text-xl font-bold">Витрина видеостудии</h1>
          <p className="mt-1 text-sm text-muted-2">
            Ролики карусели на первом экране видеостудии. В ней {REEL_SIZE} мест: верхний ролик каждого
            сценария, на свободные — остальные по порядку списка. Ставьте сюда удачные дубли из кандидатов
            ниже. Новые посетители видят изменения сразу, в уже открытой вкладке студии — в течение 10 минут.
          </p>
        </div>
        <a
          href="/video-studio"
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs text-muted transition-colors hover:text-foreground"
        >
          <FiExternalLink className="h-3.5 w-3.5" aria-hidden />
          Открыть видеостудию
        </a>
      </div>

      {!board && loading && (
        <div className="flex flex-col gap-4" aria-busy="true">
          <Skeleton className="h-64" />
          <div className="grid grid-cols-3 gap-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-20" />
            ))}
          </div>
          <Skeleton className="h-36" />
          <Skeleton className="h-36" />
        </div>
      )}

      {!board && !loading && (
        <div className={`${CARD} flex flex-col items-start gap-3 p-6`}>
          <div className="text-sm text-status-fail">{list.error || "Не удалось загрузить витрину"}</div>
          <button type="button" onClick={reload} className={btn("plain", "lg")}>
            <FiRefreshCw className="h-4 w-4" aria-hidden />
            Повторить
          </button>
        </div>
      )}

      {board && (
        <>
          <ScenarioBoard carousel={reel} min={REEL_MIN} />

          <div className="grid grid-cols-3 gap-3">
            <Stat label="В витрине" value={items.length} />
            <Stat label="В карусели" value={shown.length} hint={`из ${REEL_SIZE}`} />
            <Stat label="С запросом" value={shown.filter((item) => item.showPrompt && item.prompt).length} />
          </div>

          <section className="flex flex-col gap-3">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h2 className="text-base font-semibold">В витрине</h2>
              <span className="text-xs text-muted-2">Из роликов одного сценария в карусель идёт верхний.</span>
              {ordering && (
                <span role="status" className="text-xs text-status-wait">
                  Сохраняю порядок…
                </span>
              )}
            </div>
            {items.length === 0 ? (
              <div className={`${CARD} p-6 text-center text-sm text-muted-2`}>
                В витрине пока пусто — на первом экране идут только сцены мультстудии. Поставьте первую работу
                из кандидатов ниже.
              </div>
            ) : (
              <ul className="flex flex-col gap-3">
                {items.map((item, index) => (
                  <ItemRow
                    key={item.id}
                    item={item}
                    index={index}
                    total={items.length}
                    place={places.get(item.id) ?? "out"}
                    categories={board.categories}
                    busy={busy.has(item.id)}
                    orderLocked={ordering}
                    onPatch={(target, changes) => void patch(target, changes)}
                    onMove={(target, to) => void move(target, to)}
                    onRemove={(target) => void remove(target)}
                  />
                ))}
              </ul>
            )}
          </section>

          <section className="flex flex-col gap-3">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h2 className="text-base font-semibold">Кандидаты</h2>
              <span className="text-xs text-muted-2">
                Готовые дубли видеостудии, которых в витрине ещё нет. Новые — выше.
              </span>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button type="button" aria-pressed={staffOnly} onClick={() => setStaffOnly(true)} className={chip(staffOnly)}>
                Только сотрудники
              </button>
              <button type="button" aria-pressed={!staffOnly} onClick={() => setStaffOnly(false)} className={chip(!staffOnly)}>
                Все
              </button>
              <button type="button" onClick={reload} disabled={loading} className={btn()}>
                <FiRefreshCw className={`h-3.5 w-3.5 ${loading ? "motion-safe:animate-spin" : ""}`} aria-hidden />
                Обновить
              </button>
              <form
                className="flex w-full items-center gap-2 sm:ml-auto sm:w-auto"
                onSubmit={(e) => {
                  e.preventDefault();
                  setSearch(query.trim());
                }}
              >
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="почта, модель, текст запроса или uid дубля"
                  aria-label="Поиск по кандидатам"
                  maxLength={200}
                  className={`${INPUT} min-w-0 flex-1 sm:w-80 sm:flex-none`}
                />
                <button type="submit" className={btn()}>
                  Найти
                </button>
                {search && (
                  <button
                    type="button"
                    onClick={() => {
                      setQuery("");
                      setSearch("");
                    }}
                    className={btn()}
                  >
                    Сбросить
                  </button>
                )}
              </form>
            </div>

            {!staffOnly && (
              <p className="text-xs text-muted-2">
                Здесь работы всех пользователей — только посмотреть. В витрину пока ставятся работы сотрудников: в
                адресе файла виден номер аккаунта автора.
              </p>
            )}

            {list.error && !loading && (
              <div className="flex flex-wrap items-center gap-3 text-sm text-status-fail">
                {list.error}
                <button type="button" onClick={reload} className={btn()}>
                  Повторить
                </button>
              </div>
            )}

            {!list.error && <div className="text-xs text-muted-2">Найдено: {list.count}</div>}

            <ul
              aria-busy={loading}
              className={`grid grid-cols-1 gap-4 transition-opacity sm:grid-cols-2 xl:grid-cols-3 ${
                loading ? "opacity-60" : ""
              }`}
            >
              {list.rows.map((candidate) => (
                <CandidateCard key={candidate.takeUid} candidate={candidate} onAdd={setAdding} />
              ))}
            </ul>

            {!loading && !list.error && list.rows.length === 0 && (
              <div className={`${CARD} p-6 text-center text-sm text-muted-2`}>
                {search
                  ? "Ничего не нашлось. Проверьте запрос или сбросьте поиск."
                  : staffOnly
                    ? "У сотрудников пока нет готовых дублей вне витрины. Снимите ролик в видеостудии — он появится здесь."
                    : "Готовых дублей вне витрины пока нет."}
              </div>
            )}

            {!loading && list.rows.length < list.count && (
              <button type="button" onClick={() => void more()} disabled={loadingMore} className={`${btn("plain", "lg")} self-center`}>
                {loadingMore ? "Загружаю…" : `Показать ещё (показано ${list.rows.length} из ${list.count})`}
              </button>
            )}
          </section>
        </>
      )}

      {adding && board && (
        <AddDialog
          key={adding.takeUid}
          candidate={adding}
          categories={board.categories}
          onSubmit={(form) => add(adding, form)}
          onClose={closeDialog}
        />
      )}

      <Notices list={notices} onClose={close} />
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: number; hint?: string }) {
  return (
    <div className={`${CARD} p-3 sm:p-4`}>
      <div className="text-xs text-muted-2">{label}</div>
      <div className="mt-1 text-2xl font-bold tabular-nums">
        {value}
        {hint && <span className="ml-2 text-sm font-normal text-muted">{hint}</span>}
      </div>
    </div>
  );
}

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { FiPlus, FiRefreshCw, FiSearch } from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";
import { INPUT_LG, Notices, Skeleton, btn, useNotices } from "../vstudio-showcase/parts";
import AddModelDialog from "./AddModelDialog";
import ModelRow, { ModelsHead } from "./ModelRow";
import TextRecomputeDialog from "./TextRecomputeDialog";
import {
  MODELS_PATH,
  PRICING_SETTINGS_LINK,
  RECOMPUTE_COPY,
  errorText,
  formFromModel,
  matchesModel,
  modeOf,
  modelPath,
  parseModel,
  parseModels,
  replaceModel,
  rowChanges,
  touchesPrice,
  type Added,
  type Model,
  type RecomputeKind,
  type RowForm,
} from "./modelsAdmin";

const MODE_NAME = { legacy: "по-старому", markup: "наценка" } as const;

type RecomputeState = { kind: RecomputeKind; ids: number[]; seq: number };

/**
 * Модели: тарифы, своя наценка, себестоимость, цена типичной генерации и
 * доступность. Клиент (15.10.2026): наценка к себестоимости OpenRouter —
 * общая в «Настройках» и своя у каждой модели здесь; новые модели — кнопкой
 * «Добавить модель» из каталога OpenRouter, без Django-админки.
 */
export default function AdminModelsPage() {
  const [tick, setTick] = useState(0);
  const [models, setModels] = useState<Model[]>([]);
  const [loaded, setLoaded] = useState<{ tick: number; error: string | null } | null>(null);
  // Правленые строки: форма есть только у тех, что трогали.
  const [forms, setForms] = useState<Record<number, RowForm>>({});
  const [saving, setSaving] = useState<ReadonlySet<number>>(new Set());
  const [flashed, setFlashed] = useState<ReadonlySet<number>>(new Set());
  const [rowErrors, setRowErrors] = useState<Record<number, string>>({});
  // По умолчанию показываем ТОЛЬКО активные: в БД ~100 легаси-моделей из старого
  // импорта — клиенту они не нужны и превращают список в свалку.
  const [showInactive, setShowInactive] = useState(false);
  const [query, setQuery] = useState("");
  // Добавленные и показанные по ссылке видны, даже если выключены.
  const [pinned, setPinned] = useState<ReadonlySet<number>>(new Set());
  const [highlight, setHighlight] = useState<number | null>(null);
  // Куда прокрутить, когда окна закроются: под затемнением прокрутка не видна.
  const [scrollTarget, setScrollTarget] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [recompute, setRecompute] = useState<RecomputeState | null>(null);
  const seq = useRef(0);
  const { list: notices, notify, close } = useNotices();

  const loading = loaded?.tick !== tick;
  const reload = () => setTick((value) => value + 1);

  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await fetchData<unknown>(MODELS_PATH, "GET", undefined, true);
      if (!alive) return;
      const data = res.ok ? parseModels(res.data) : null;
      if (data) setModels(data);
      setLoaded({ tick, error: data ? null : errorText(res, "Не удалось загрузить модели") });
    })();
    return () => {
      alive = false;
    };
  }, [tick]);

  // Показанную строку прокручиваем к себе, когда она нарисована и окна закрыты.
  useEffect(() => {
    if (scrollTarget === null || adding || recompute) return;
    const timer = setTimeout(() => {
      document.getElementById(`model-${scrollTarget}`)?.scrollIntoView({ block: "center" });
      setScrollTarget(null);
    }, 50);
    return () => clearTimeout(timer);
  }, [scrollTarget, adding, recompute]);

  const visible = useMemo(
    () =>
      models.filter(
        (m) =>
          (showInactive || m.isActive || Boolean(forms[m.id]) || pinned.has(m.id)) && matchesModel(m, query),
      ),
    [models, forms, showInactive, pinned, query],
  );
  const inactiveCount = useMemo(() => models.filter((m) => !m.isActive).length, [models]);
  const mode = modeOf(models);

  const lock = (id: number, on: boolean) =>
    setSaving((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  const dropForm = (id: number) => {
    setForms((prev) => {
      const out = { ...prev };
      delete out[id];
      return out;
    });
    setRowErrors((prev) => {
      const out = { ...prev };
      delete out[id];
      return out;
    });
  };

  const change = (m: Model, patch: Partial<RowForm>) => {
    setForms((prev) => {
      const next = { ...(prev[m.id] ?? formFromModel(m)), ...patch };
      const out = { ...prev };
      const { body, error } = rowChanges(m, next);
      // Вернули как было — строка снова чистая.
      if (!error && Object.keys(body).length === 0) delete out[m.id];
      else out[m.id] = next;
      return out;
    });
  };

  const save = async (m: Model) => {
    const form = forms[m.id];
    if (!form || saving.has(m.id)) return;
    const { body, error } = rowChanges(m, form);
    if (error) {
      setRowErrors((prev) => ({ ...prev, [m.id]: error }));
      return;
    }
    if (Object.keys(body).length === 0) {
      dropForm(m.id);
      return;
    }
    lock(m.id, true);
    setRowErrors((prev) => {
      const out = { ...prev };
      delete out[m.id];
      return out;
    });
    const res = await fetchData<unknown>(modelPath(m.id), "PATCH", body, true);
    lock(m.id, false);
    const saved = res.ok ? parseModel(res.data) : null;
    if (!saved) {
      const text = errorText(res, "Не удалось сохранить");
      setRowErrors((prev) => ({ ...prev, [m.id]: text }));
      notify("fail", `«${m.name}»: ${text}`);
      if (res.status === 404) reload();
      return;
    }
    setModels((prev) => replaceModel(prev, saved));
    // Выключили — строка не пропадает из списка сразу: видно, что сохранилось.
    setPinned((prev) => new Set(prev).add(m.id));
    dropForm(m.id);
    setFlashed((prev) => new Set(prev).add(m.id));
    setTimeout(
      () =>
        setFlashed((prev) => {
          const next = new Set(prev);
          next.delete(m.id);
          return next;
        }),
      2000,
    );
  };

  const show = useCallback((id: number) => {
    setPinned((prev) => new Set(prev).add(id));
    setQuery("");
    setHighlight(id);
    setScrollTarget(id);
    setAdding(false);
  }, []);

  // Об удаче говорит само окно «Добавить модель» — с предупреждениями сервера.
  const added = useCallback((result: Added) => {
    setModels((prev) => replaceModel(prev, result.model));
    setPinned((prev) => new Set(prev).add(result.model.id));
    setHighlight(result.model.id);
    setScrollTarget(result.model.id);
  }, []);

  const openRecompute = useCallback((ids: number[], kind: RecomputeKind = "text") => {
    setAdding(false);
    setRecompute({ kind, ids, seq: ++seq.current });
  }, []);

  const applied = useCallback(
    (count: number, kind: RecomputeKind) => {
      notify(
        "ok",
        count > 0 ? `${RECOMPUTE_COPY[kind].applied}: ${count}.` : "Тарифы уже такие — менять было нечего.",
      );
      setTick((value) => value + 1);
    },
    [notify],
  );

  const closeAdd = useCallback(() => setAdding(false), []);
  const closeRecompute = useCallback(() => setRecompute(null), []);

  if (loading && models.length === 0) {
    return (
      <div className="space-y-4" aria-busy="true">
        <Skeleton className="h-16" />
        <Skeleton className="h-12" />
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-36" />
        ))}
      </div>
    );
  }

  if (loaded?.error && models.length === 0) {
    return (
      <div className="rounded-2xl border border-border bg-surface p-6 text-sm text-muted">
        <p>Ошибка загрузки: {loaded.error}</p>
        <button type="button" onClick={reload} className={`${btn("plain")} mt-3`}>
          <FiRefreshCw className="h-3.5 w-3.5" aria-hidden />
          Повторить
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold">Модели</h1>
          <p className="mt-1 text-sm text-muted">
            Тарифы, наценка, себестоимость и доступность моделей. Изменили строку — нажмите «Сохранить».
          </p>
          {mode && (
            <p className="mt-1 text-xs text-muted-2">
              Режим цен: <span className="text-foreground">{MODE_NAME[mode]}</span> · общая наценка, порог и курс —{" "}
              <Link href={PRICING_SETTINGS_LINK} className="text-accent underline-offset-2 hover:underline">
                Настройки → Цены и наценка
              </Link>
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => openRecompute([])} className={btn("plain", "lg")}>
            {RECOMPUTE_COPY.text.button}
          </button>
          <button
            type="button"
            onClick={() => openRecompute([], "chat_image")}
            title={RECOMPUTE_COPY.chat_image.title}
            className={btn("plain", "lg")}
          >
            {RECOMPUTE_COPY.chat_image.button}
          </button>
          <button type="button" onClick={() => setAdding(true)} className={btn("primary", "lg")}>
            <FiPlus className="h-4 w-4" aria-hidden />
            Добавить модель
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-0 flex-1 basis-56">
          <FiSearch
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-2"
            aria-hidden
          />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Поиск по названию или ID"
            aria-label="Поиск модели"
            className={`${INPUT_LG} w-full pl-9`}
          />
        </div>
        {inactiveCount > 0 && (
          <label className="inline-flex min-h-9 cursor-pointer items-center gap-2 rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm text-muted hover:text-foreground">
            <input
              type="checkbox"
              checked={showInactive}
              onChange={(e) => setShowInactive(e.target.checked)}
              className="h-4 w-4 accent-accent"
            />
            Показать выключенные ({inactiveCount})
          </label>
        )}
        <button
          type="button"
          onClick={reload}
          disabled={loading}
          aria-label="Обновить список"
          title="Обновить список"
          className={`${btn("plain", "lg")} min-h-9`}
        >
          <FiRefreshCw className={`h-4 w-4 ${loading ? "motion-safe:animate-spin" : ""}`} aria-hidden />
        </button>
      </div>

      {loaded?.error && (
        <p role="alert" className="text-sm text-status-fail">
          Список не обновился: {loaded.error}
        </p>
      )}

      <p className="text-xs text-muted-2">
        Себестоимость — что платим OpenRouter за типичную генерацию: видео 5 с 720p, одну картинку, сообщение в
        2000 токенов. Цена — сколько кредитов спишется с покупателя в действующем режиме, строкой ниже — в другом
        и в чате, если чат берёт иначе. Пустая наценка — общая из настроек; ниже нижнего порога наценка не
        опускается. Картинку Nano Banana чат берёт по токенам × тариф: под цену по наценке его подгоняет кнопка
        «{RECOMPUTE_COPY.chat_image.button}».
      </p>

      {visible.length === 0 ? (
        <div className="rounded-2xl border border-border bg-surface p-6 text-sm text-muted">
          {query.trim()
            ? `Ничего не нашлось по «${query.trim()}».${!showInactive && inactiveCount > 0 ? " Среди выключенных тоже можно поискать." : ""}`
            : "Включённых моделей нет. Отметьте «Показать выключенные» или добавьте модель."}
        </div>
      ) : (
        <div className="space-y-2">
          <ModelsHead modeLabel={mode ? MODE_NAME[mode] : "сейчас"} />
          <ul className="space-y-3">
            {visible.map((m) => {
              const form = forms[m.id];
              const changes = form ? rowChanges(m, form) : null;
              return (
                <ModelRow
                  key={m.id}
                  model={m}
                  form={form ?? formFromModel(m)}
                  dirty={Boolean(form)}
                  priceStale={Boolean(changes && touchesPrice(changes.body))}
                  busy={saving.has(m.id)}
                  flash={flashed.has(m.id)}
                  error={changes?.error ?? rowErrors[m.id] ?? null}
                  highlight={highlight === m.id}
                  onChange={(patch) => change(m, patch)}
                  onSave={() => void save(m)}
                  onReset={() => dropForm(m.id)}
                />
              );
            })}
          </ul>
        </div>
      )}

      {adding && (
        <AddModelDialog
          onAdded={added}
          onShow={show}
          onRecompute={(id) => openRecompute([id])}
          onClose={closeAdd}
        />
      )}
      {recompute && (
        <TextRecomputeDialog
          key={recompute.seq}
          kind={recompute.kind}
          ids={recompute.ids}
          onApplied={(count) => applied(count, recompute.kind)}
          onClose={closeRecompute}
        />
      )}
      <Notices list={notices} onClose={close} />
    </div>
  );
}

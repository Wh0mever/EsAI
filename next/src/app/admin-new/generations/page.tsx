"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { fetchData } from "@/tools/fetchData";

/**
 * Журнал генераций.
 *
 * Клиент (21.09.2026): в кабинете OpenRouter появилась оплаченная генерация,
 * которую в EsAI никто не нашёл. Здесь каждая генерация оставляет след: кто,
 * когда, какой моделью, что именно, ID у провайдера, сколько стоило, сколько
 * кредитов списали и на каком шаге всё остановилось. Ищется по почте, модели
 * или началу ID из кабинета провайдера.
 */

type Stage = { at: string; stage: string; note: string };

type Generation = {
  id: number;
  created_at: string;
  user_email: string;
  kind: string;
  kind_label: string;
  source?: string;
  source_label: string;
  provider: string;
  model: string;
  status: string;
  status_label: string;
  provider_id: string;
  prompt: string;
  params: Record<string, unknown>;
  credits_planned: number;
  credits_charged: number;
  provider_cost_usd: string | null;
  result_url: string;
  error: string;
  stages: Stage[];
  ip: string | null;
  needs_review: boolean;
  /** Видеостудия: uid дубля (params.take) и ссылка на него в Django-админке. */
  take_uid?: string;
  take_admin_url?: string;
};

type SourceOption = { key: string; label: string };

type ListResponse = {
  count: number;
  results: Generation[];
  totals: { review: number; lost: number; open: number; lost_usd: string };
  /** Варианты фильтра «Откуда» (?source=) — список отдаёт бэкенд. */
  sources?: SourceOption[];
};

const KINDS = [
  { key: "", label: "Всё" },
  { key: "video", label: "Видео" },
  { key: "image", label: "Изображения" },
  { key: "voice", label: "Озвучка" },
  { key: "music", label: "Музыка" },
  { key: "sfx", label: "Эффекты" },
];

const STATES = [
  { key: "", label: "Любое состояние" },
  { key: "lost", label: "Оплачено, не выдано" },
  { key: "submitted", label: "В работе" },
  { key: "failed", label: "Не удалось" },
  { key: "delivered", label: "Выдано" },
  { key: "recovered", label: "Довезено фоном" },
];

const STAGE_LABEL: Record<string, string> = {
  started: "Запрос получен",
  submitting: "Отправляем провайдеру",
  submitted: "Провайдер принял",
  timeout: "Не дождались в соединении",
  download_failed: "Скачивание сорвалось",
  saved: "Файл сохранён",
  delivered: "Выдано пользователю",
  recovered: "Довезено фоном",
  recover_waiting: "Довоз: ещё снимается",
  recover_poll_failed: "Довоз: провайдер не ответил",
  recover_download_failed: "Довоз: не скачалось",
  failed: "Ошибка",
  lost: "Потеряно",
};

const STATUS_TONE: Record<string, string> = {
  delivered: "text-emerald-400",
  recovered: "text-emerald-400",
  failed: "text-muted",
  lost: "text-red-400",
  submitted: "text-status-wait",
  submitting: "text-status-wait",
};

const fmt = (s: string) => {
  const d = new Date(s);
  return isNaN(d.getTime())
    ? s
    : d.toLocaleString("ru-RU", {
        day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
      });
};

// useSearchParams требует границы Suspense (иначе сборка не сможет пререндерить страницу).
export default function AdminGenerationsPage() {
  return (
    <Suspense fallback={<div className="text-sm text-muted-2">Загрузка…</div>}>
      <GenerationsJournal />
    </Suspense>
  );
}

function GenerationsJournal() {
  // ?q=<uid дубля> — ссылка из админки видеостудии: журнал открывается уже отфильтрованным.
  const initialQ = (useSearchParams().get("q") ?? "").trim();
  const [kind, setKind] = useState("");
  const [source, setSource] = useState("");
  const [sources, setSources] = useState<SourceOption[]>([]);
  const [state, setState] = useState("");
  const [review, setReview] = useState(false);
  const [query, setQuery] = useState(initialQ);
  const [search, setSearch] = useState(initialQ);
  const [items, setItems] = useState<Generation[]>([]);
  const [totals, setTotals] = useState<ListResponse["totals"] | null>(null);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  const [opened, setOpened] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (pageNum: number, append: boolean) => {
      setLoading(true);
      setError(null);
      const params = new URLSearchParams({ page: String(pageNum) });
      if (kind) params.set("kind", kind);
      if (source) params.set("source", source);
      if (state) params.set("status", state);
      if (review) params.set("review", "1");
      if (search) params.set("q", search);
      const res = await fetchData<ListResponse>(
        `manage/generations/?${params.toString()}`, "GET", undefined, true
      );
      setLoading(false);
      if (res.ok && res.data) {
        setCount(res.data.count);
        setTotals(res.data.totals);
        if (Array.isArray(res.data.sources)) setSources(res.data.sources);
        setItems((prev) => (append ? [...prev, ...res.data!.results] : res.data!.results));
        setPage(pageNum);
      } else {
        setError(res.error || "Не удалось загрузить журнал");
      }
    },
    [kind, source, state, review, search]
  );

  useEffect(() => {
    // Первая загрузка — следующей задачей, а не в теле эффекта: load меняет состояние,
    // а синхронный setState в эффекте — лишний проход рендера. Отмена таймера заодно
    // не даёт StrictMode в разработке отправить запрос дважды.
    const timer = setTimeout(() => void load(1, false));
    return () => clearTimeout(timer);
  }, [load]);

  const markReviewed = async (g: Generation) => {
    const res = await fetchData<Generation>(
      `manage/generations/${g.id}/reviewed/`, "POST", {}, true
    );
    if (res.ok && res.data) {
      setItems((prev) => prev.map((x) => (x.id === g.id ? { ...x, ...res.data! } : x)));
    }
  };

  const chip = (active: boolean) =>
    `rounded-lg border px-3 py-1.5 text-xs transition-colors ${
      active ? "border-accent bg-accent/10 text-accent" : "border-border text-muted hover:text-foreground"
    }`;

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-xl font-bold">Генерации</h1>
        <p className="mt-1 text-sm text-muted-2">
          Каждая платная генерация: кто, когда, чем и что сделал, ID у провайдера, стоимость,
          списанные кредиты и ход по шагам. Если в кабинете OpenRouter или ElevenLabs появилось
          непонятное списание — вставьте начало его ID в поиск.
        </p>
      </div>

      {totals && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="rounded-2xl border border-border bg-surface p-4">
            <div className="text-xs text-muted-2">Нужен разбор</div>
            <div className={`mt-1 text-2xl font-bold ${totals.review ? "text-red-400" : ""}`}>
              {totals.review}
            </div>
          </div>
          <div className="rounded-2xl border border-border bg-surface p-4">
            <div className="text-xs text-muted-2">Оплачено, но не выдано</div>
            <div className="mt-1 text-2xl font-bold">
              {totals.lost}
              {Number(totals.lost_usd) > 0 && (
                <span className="ml-2 text-sm font-normal text-muted">${totals.lost_usd}</span>
              )}
            </div>
          </div>
          <div className="rounded-2xl border border-border bg-surface p-4">
            <div className="text-xs text-muted-2">Сейчас в работе</div>
            <div className="mt-1 text-2xl font-bold">{totals.open}</div>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {KINDS.map((k) => (
          <button key={k.key} onClick={() => setKind(k.key)} className={chip(kind === k.key)}>
            {k.label}
          </button>
        ))}
        <span className="mx-1 h-5 w-px bg-border" />
        {sources.length > 0 && (
          <select
            value={source}
            onChange={(e) => setSource(e.target.value)}
            aria-label="Откуда"
            className="rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-xs text-foreground outline-none focus:border-accent"
          >
            <option value="">Откуда: отовсюду</option>
            {sources.map((s) => (
              <option key={s.key} value={s.key}>{s.label}</option>
            ))}
          </select>
        )}
        <select
          value={state}
          onChange={(e) => setState(e.target.value)}
          className="rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-xs text-foreground outline-none focus:border-accent"
        >
          {STATES.map((s) => (
            <option key={s.key} value={s.key}>{s.label}</option>
          ))}
        </select>
        <button onClick={() => setReview((v) => !v)} className={chip(review)}>
          Только требующие разбора
        </button>
        <form
          className="ml-auto flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setSearch(query.trim());
          }}
        >
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="почта, модель, ID провайдера или uid дубля"
            className="w-64 rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-sm text-foreground outline-none focus:border-accent"
          />
        </form>
      </div>

      {error && <div className="text-sm text-red-400">{error}</div>}
      <div className="text-xs text-muted-2">Найдено: {count}</div>

      <div className="overflow-x-auto rounded-2xl border border-border bg-surface">
        <table className="w-full min-w-[60rem] text-left text-sm">
          <thead className="text-xs text-muted-2">
            <tr className="border-b border-border">
              <th className="px-3 py-2 font-medium">Время</th>
              <th className="px-3 py-2 font-medium">Пользователь</th>
              <th className="px-3 py-2 font-medium">Что</th>
              <th className="px-3 py-2 font-medium">Модель</th>
              <th className="px-3 py-2 font-medium">Состояние</th>
              <th className="px-3 py-2 text-right font-medium">Кредиты</th>
              <th className="px-3 py-2 text-right font-medium">$ у провайдера</th>
              <th className="px-3 py-2 font-medium">ID провайдера</th>
            </tr>
          </thead>
          <tbody>
            {items.map((g) => (
              <Row
                key={g.id}
                g={g}
                open={opened === g.id}
                onToggle={() => setOpened((v) => (v === g.id ? null : g.id))}
                onReviewed={() => void markReviewed(g)}
              />
            ))}
          </tbody>
        </table>
        {!loading && items.length === 0 && (
          <div className="p-6 text-center text-sm text-muted-2">Пока пусто</div>
        )}
      </div>

      {loading && <div className="text-sm text-muted-2">Загрузка…</div>}
      {!loading && items.length < count && (
        <button
          onClick={() => void load(page + 1, true)}
          className="self-center rounded-lg border border-border px-4 py-2 text-sm text-muted hover:text-foreground"
        >
          Показать ещё
        </button>
      )}
    </div>
  );
}

function Row({
  g, open, onToggle, onReviewed,
}: {
  g: Generation;
  open: boolean;
  onToggle: () => void;
  onReviewed: () => void;
}) {
  return (
    <>
      <tr
        onClick={onToggle}
        className={`cursor-pointer border-b border-border/60 hover:bg-surface-2 ${
          g.needs_review ? "bg-red-500/5" : ""
        }`}
      >
        <td className="whitespace-nowrap px-3 py-2 text-xs text-muted">{fmt(g.created_at)}</td>
        <td className="max-w-[14rem] truncate px-3 py-2">{g.user_email || "—"}</td>
        <td className="whitespace-nowrap px-3 py-2">
          {g.kind_label} <span className="text-xs text-muted-2">· {g.source_label}</span>
        </td>
        <td className="max-w-[12rem] truncate px-3 py-2 font-mono text-xs">{g.model}</td>
        <td className={`whitespace-nowrap px-3 py-2 ${STATUS_TONE[g.status] || ""}`}>
          {g.status_label}
          {g.needs_review && <span className="ml-1 text-red-400">●</span>}
        </td>
        <td className="whitespace-nowrap px-3 py-2 text-right">
          {g.credits_charged}
          <span className="text-xs text-muted-2"> / {g.credits_planned}</span>
        </td>
        <td className="whitespace-nowrap px-3 py-2 text-right text-xs">
          {g.provider_cost_usd ?? "—"}
        </td>
        <td className="max-w-[12rem] truncate px-3 py-2 font-mono text-[11px] text-muted">
          {g.provider_id || "—"}
        </td>
      </tr>
      {open && (
        <tr className="border-b border-border/60 bg-surface-2/40">
          <td colSpan={8} className="px-4 py-3">
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <div className="flex flex-col gap-2 text-xs">
                <div>
                  <span className="text-muted-2">
                    Запрос{g.prompt ? ` (${g.prompt.length} симв., ушёл провайдеру целиком)` : ""}:{" "}
                  </span>
                  <span className="whitespace-pre-wrap break-words text-foreground">{g.prompt || "—"}</span>
                </div>
                <div className="text-muted">
                  <span className="text-muted-2">Параметры: </span>
                  {Object.entries(g.params || {})
                    .map(([k, v]) => `${k}=${String(v)}`)
                    .join(" · ") || "—"}
                </div>
                <div className="text-muted">
                  <span className="text-muted-2">Провайдер: </span>{g.provider}
                  {g.ip && <> · <span className="text-muted-2">IP: </span>{g.ip}</>}
                </div>
                {g.provider_id && (
                  <div className="break-all font-mono text-[11px] text-muted">{g.provider_id}</div>
                )}
                {g.error && <div className="text-red-400">Ошибка: {g.error}</div>}
                {g.result_url && (
                  <a href={g.result_url} target="_blank" rel="noreferrer" className="text-accent underline">
                    Открыть результат
                  </a>
                )}
                {g.take_admin_url ? (
                  <a
                    href={g.take_admin_url}
                    target="_blank"
                    rel="noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    className="text-accent underline"
                  >
                    Дубль видеостудии
                  </a>
                ) : g.take_uid ? (
                  <div className="text-muted">
                    <span className="text-muted-2">Дубль видеостудии: </span>
                    <span className="font-mono text-[11px]">{g.take_uid}</span>
                  </div>
                ) : null}
                {g.needs_review && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onReviewed();
                    }}
                    className="self-start rounded-lg border border-border px-3 py-1.5 text-xs text-muted hover:text-foreground"
                  >
                    Разобрано — снять отметку
                  </button>
                )}
              </div>
              <ol className="flex flex-col gap-1 text-xs">
                {(g.stages || []).map((s, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="w-16 shrink-0 text-muted-2">
                      {new Date(s.at).toLocaleTimeString("ru-RU")}
                    </span>
                    <span className="text-foreground">{STAGE_LABEL[s.stage] || s.stage}</span>
                    {s.note && <span className="truncate text-muted">{s.note}</span>}
                  </li>
                ))}
              </ol>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

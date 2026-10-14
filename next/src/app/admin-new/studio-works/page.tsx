"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { fetchData } from "@/tools/fetchData";
import { FiStar, FiImage, FiLock, FiUploadCloud, FiArrowRight } from "react-icons/fi";
import { errorText, parsePublished, publishScenePath, sceneLink } from "../studio-scenes/scenesAdmin";

/**
 * Работы пользователей студии.
 *
 * Клиент: пары «герой + сцена» создают сами пользователи, а удачные потом идут
 * в рекламу и в библиотеку. Здесь видно все готовые сцены и мультфильмы:
 * «Для рекламы» — отметка, «Сделать превью сцены» — ролик становится превью
 * этой сцены в библиотеке для всех, «Опубликовать как новую сцену» — «своя
 * сцена» пользователя становится новой сценой библиотеки (неопубликованной:
 * названия и публикация — в «Сценах мультстудии»). Работы со своими
 * персонажами пользователей (там может быть живой человек) публично не
 * показываются — кнопки закрыты.
 */

type Work = {
  kind: "scene" | "movie";
  id: number;
  created_at: string;
  user_email: string;
  project_id: number;
  title: string;
  custom_text: string;
  preset_id: number | null;
  preset_slug: string;
  hero: { name: string; image: string; own: boolean } | null;
  scenes?: number;
  video: string;
  poster: string;
  featured: boolean;
  public_ok: boolean;
  can_preview: boolean;
  /** Только у сцен: «своя сцена» годится в библиотеку. Сервер прежней версии поля не знает. */
  can_publish_scene?: boolean;
  /** Почему не годится; пусто — годится или это сцена библиотеки. */
  publish_scene_note?: string;
  /** Сцена библиотеки, уже сделанная из этой; null — ещё не делали. */
  library_scene_id?: number | null;
};

type WorksResponse = { count: number; results: Work[] };

/** Чем кончилось «Опубликовать как новую сцену»: сцена библиотеки или отказ. */
type Published = { sceneId: number; created: boolean } | { error: string };

const KINDS = [
  { key: "scenes", label: "Сцены" },
  { key: "movies", label: "Мультфильмы" },
];

const SHOWS = [
  { key: "all", label: "Все" },
  { key: "public", label: "Можно показывать" },
  { key: "featured", label: "Для рекламы" },
];

const fmtDate = (s: string) => {
  const d = new Date(s);
  if (isNaN(d.getTime())) return s;
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
};

export default function AdminStudioWorksPage() {
  const [kind, setKind] = useState("scenes");
  const [show, setShow] = useState("public");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [items, setItems] = useState<Work[]>([]);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  // Каким фильтром получен список: не совпадает с текущим — идёт загрузка.
  const key = `${kind}|${show}|${search}`;
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [published, setPublished] = useState<Record<number, Published>>({});
  const loading = loadedKey !== key || loadingMore;

  const fetchPage = useCallback(
    (pageNum: number) => {
      const params = new URLSearchParams({ kind, show, page: String(pageNum) });
      if (search) params.set("q", search);
      return fetchData<WorksResponse>(`manage/studio/works/?${params.toString()}`, "GET", undefined, true);
    },
    [kind, show, search]
  );

  useEffect(() => {
    let alive = true;
    (async () => {
      const res = await fetchPage(1);
      if (!alive) return;
      const data = res.ok ? res.data : null;
      if (data) {
        setCount(data.count);
        setItems(data.results);
        setPage(1);
        setError(null);
      } else {
        setError(errorText(res, "Не удалось загрузить работы"));
      }
      setLoadedKey(key);
    })();
    return () => {
      alive = false;
    };
  }, [fetchPage, key]);

  const more = async () => {
    setLoadingMore(true);
    setError(null);
    const res = await fetchPage(page + 1);
    setLoadingMore(false);
    const data = res.ok ? res.data : null;
    if (data) {
      setCount(data.count);
      setItems((prev) => [...prev, ...data.results]);
      setPage(page + 1);
    } else {
      setError(errorText(res, "Не удалось загрузить работы"));
    }
  };

  const replace = (w: Work) =>
    setItems((prev) => prev.map((x) => (x.kind === w.kind && x.id === w.id ? { ...x, ...w } : x)));

  const toggleFeatured = async (w: Work) => {
    setBusy(`f${w.kind}${w.id}`);
    setError(null);
    const res = await fetchData<Work>(
      `manage/studio/works/${w.kind}/${w.id}/feature/`,
      "POST",
      { featured: !w.featured },
      true
    );
    setBusy(null);
    if (res.ok && res.data) replace(res.data);
    else setError(errorText(res, "Не получилось"));
  };

  const setPreview = async (w: Work) => {
    if (!confirm(`Сделать этот ролик превью сцены «${w.title}» для всех посетителей студии?`)) return;
    setBusy(`p${w.id}`);
    setError(null);
    setNote(null);
    const res = await fetchData<{ detail?: string; notes?: string[] }>(
      `manage/studio/works/scene/${w.id}/set-preview/`,
      "POST",
      {},
      true
    );
    setBusy(null);
    if (res.ok) {
      const extra = res.data?.notes?.length ? ` (${res.data.notes.join("; ")})` : "";
      setNote(`Превью сцены «${w.title}» обновлено${extra}`);
    } else {
      setError(errorText(res, "Не получилось"));
    }
  };

  /**
   * «Своя сцена» → новая сцена библиотеки. Сервер создаёт её снятой с
   * публикации и сам собирает превью; повторный клик отдаёт уже созданную.
   * Итог — в карточке, рядом с кнопкой: строка вверху страницы осталась бы за экраном.
   */
  const publishScene = async (w: Work) => {
    const name = w.title ? `«${w.title}»` : `#${w.id}`;
    const ok = confirm(
      `Сделать из сцены ${name} новую сцену библиотеки? Она появится в «Сценах мультстудии» неопубликованной — там поправьте названия и опубликуйте её.`
    );
    if (!ok) return;
    setBusy(`s${w.id}`);
    const res = await fetchData<unknown>(publishScenePath(w.id), "POST", {}, true);
    setBusy(null);
    const done = res.ok ? parsePublished(res.data) : null;
    setPublished((prev) => ({
      ...prev,
      [w.id]: done
        ? { sceneId: done.scene.id, created: done.created }
        : { error: errorText(res, "Не удалось опубликовать сцену") },
    }));
  };

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-xl font-bold">Работы пользователей</h1>
        <p className="mt-1 text-sm text-muted-2">
          Готовые сцены и мультфильмы студии. Удачные отмечайте «Для рекламы», делайте превью сцены в
          библиотеке или публикуйте «свою сцену» как новую сцену библиотеки. Работы со своими персонажами
          пользователей публично не показываются: на загруженном фото может быть живой человек.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {KINDS.map((k) => (
          <button
            key={k.key}
            onClick={() => setKind(k.key)}
            className={`rounded-lg border px-3 py-1.5 text-xs transition-colors ${
              kind === k.key
                ? "border-accent bg-accent/10 text-accent"
                : "border-border text-muted hover:text-foreground"
            }`}
          >
            {k.label}
          </button>
        ))}
        <span className="mx-1 h-5 w-px bg-border" />
        {SHOWS.map((k) => (
          <button
            key={k.key}
            onClick={() => setShow(k.key)}
            className={`rounded-lg border px-3 py-1.5 text-xs transition-colors ${
              show === k.key
                ? "border-accent bg-accent/10 text-accent"
                : "border-border text-muted hover:text-foreground"
            }`}
          >
            {k.label}
          </button>
        ))}
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
            placeholder="почта пользователя"
            className="rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-sm text-foreground outline-none focus:border-accent"
          />
        </form>
      </div>

      {error && <div className="text-sm text-red-400">{error}</div>}
      {note && <div className="text-sm text-emerald-400">{note}</div>}

      <div className="text-xs text-muted-2">Найдено: {count}</div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {items.map((w) => {
          // Сделанную раньше (до перезагрузки или другим сотрудником) сцену знает сервер:
          // без этого кнопка вернулась бы и повторный клик искал бы копию заново.
          const earlier = w.library_scene_id ? { sceneId: w.library_scene_id, created: false } : undefined;
          const outcome = w.kind === "scene" ? (published[w.id] ?? earlier) : undefined;
          return (
            <div key={`${w.kind}${w.id}`} className="flex flex-col overflow-hidden rounded-2xl border border-border bg-surface">
              <video
                src={w.video}
                poster={w.poster || undefined}
                controls
                preload="none"
                playsInline
                className="aspect-video w-full bg-black object-contain"
              />
              <div className="flex flex-1 flex-col gap-2 p-3">
                <div className="flex items-start gap-2">
                  {w.hero?.image && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={w.hero.image} alt="" className="h-9 w-9 shrink-0 rounded-lg object-cover" />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold text-foreground">
                      {w.title || (w.kind === "movie" ? `Мультфильм #${w.id}` : `Сцена #${w.id}`)}
                    </div>
                    <div className="truncate text-[11px] text-muted-2">
                      {w.hero ? `${w.hero.name}${w.hero.own ? " · свой персонаж" : ""}` : "без героя"}
                      {w.kind === "movie" && w.scenes !== undefined ? ` · сцен: ${w.scenes}` : ""}
                      {w.custom_text ? " · своя сцена" : ""}
                    </div>
                    <div className="truncate text-[11px] text-muted-2">
                      {w.user_email} · {fmtDate(w.created_at)}
                    </div>
                  </div>
                </div>
                {w.custom_text && (
                  <p className="line-clamp-2 text-[11px] text-muted">{w.custom_text}</p>
                )}
                <div className="mt-auto flex flex-wrap gap-2 pt-1">
                  {w.public_ok ? (
                    <button
                      onClick={() => void toggleFeatured(w)}
                      disabled={busy !== null}
                      className={`inline-flex items-center gap-1 rounded-lg border px-3 py-1.5 text-xs transition-colors disabled:opacity-50 ${
                        w.featured
                          ? "border-amber-400 bg-amber-400/10 text-amber-400"
                          : "border-border text-muted hover:text-foreground"
                      }`}
                    >
                      <FiStar /> {w.featured ? "Для рекламы ✓" : "Для рекламы"}
                    </button>
                  ) : (
                    <span className="inline-flex items-center gap-1 rounded-lg border border-border px-3 py-1.5 text-xs text-muted-2">
                      <FiLock /> Свой персонаж — не показываем
                    </span>
                  )}
                  {w.can_preview && (
                    <button
                      onClick={() => void setPreview(w)}
                      disabled={busy !== null}
                      className="inline-flex items-center gap-1 rounded-lg border border-border px-3 py-1.5 text-xs text-muted transition-colors hover:text-foreground disabled:opacity-50"
                    >
                      <FiImage /> {busy === `p${w.id}` ? "Ставлю…" : "Сделать превью сцены"}
                    </button>
                  )}
                  {outcome && "sceneId" in outcome ? (
                    <Link
                      href={sceneLink(outcome.sceneId)}
                      className="inline-flex items-center gap-1 rounded-lg border border-accent/40 bg-accent/10 px-3 py-1.5 text-xs text-accent transition-colors hover:bg-accent/20"
                    >
                      {outcome.created ? "Сцена создана — открыть" : "Уже в библиотеке — открыть"} <FiArrowRight />
                    </Link>
                  ) : (
                    w.can_publish_scene && (
                      <button
                        onClick={() => void publishScene(w)}
                        disabled={busy !== null}
                        title="Новая сцена библиотеки из этой «своей сцены»: её промпты, ролик и кадр. Появится неопубликованной"
                        className="inline-flex items-center gap-1 rounded-lg border border-border px-3 py-1.5 text-xs text-muted transition-colors hover:text-foreground disabled:opacity-50"
                      >
                        <FiUploadCloud /> {busy === `s${w.id}` ? "Публикую…" : "Опубликовать как новую сцену"}
                      </button>
                    )
                  )}
                </div>
                {outcome && "sceneId" in outcome && (
                  <p className="text-[11px] text-muted-2">
                    {outcome.created
                      ? "Она пока не опубликована: поправьте названия и опубликуйте её в «Сценах мультстудии»."
                      : "Из этой сцены уже сделали сцену библиотеки — вторая не создаётся."}
                  </p>
                )}
                {outcome && "error" in outcome && <p className="text-[11px] text-red-400">{outcome.error}</p>}
                {/* Почему «своя сцена» не годится в библиотеку — чтобы не искать кнопку, которой нет. */}
                {!w.can_publish_scene && w.publish_scene_note && (
                  <p className="flex items-start gap-1 text-[11px] text-muted-2">
                    <FiLock className="mt-0.5 shrink-0" aria-hidden />
                    <span>В библиотеку нельзя: {w.publish_scene_note}</span>
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {!loading && items.length === 0 && (
        <div className="rounded-2xl border border-border bg-surface p-6 text-center text-sm text-muted-2">
          Пока пусто
        </div>
      )}
      {loading && <div className="text-sm text-muted-2">Загрузка…</div>}
      {!loading && items.length < count && (
        <button
          onClick={() => void more()}
          className="self-center rounded-lg border border-border px-4 py-2 text-sm text-muted hover:text-foreground"
        >
          Показать ещё
        </button>
      )}
    </div>
  );
}

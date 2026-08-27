"use client";

import { useTranslation } from "react-i18next";
import { useCallback, useEffect, useRef, useState } from "react";
import { FiFilm, FiLoader, FiPlus, FiZap } from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";
import SaveMediaButton from "@/components/ui/SaveMediaButton";
import CharacterPicker, { type StudioCharacter } from "./CharacterPicker";
import SceneTimeline, { type StudioScene } from "./SceneTimeline";

/**
 * CartoonStudio — студия мультфильмов: персонаж → сцены → таймлайн → готовый
 * ролик.
 *
 * Замысел клиента: человек не пишет промпты и не выбирает видео-модели. Он
 * берёт героя, набирает готовые сцены и жмёт «Собрать мультфильм». Всё, что
 * влияет на результат, спрятано в пресетах и правится в админке.
 *
 * Пока хоть одна сцена считается, состояние проекта опрашивается раз в 4
 * секунды. Опрос останавливается, как только считать нечего — иначе вкладка
 * будет молотить запросы часами, пока человек любуется результатом.
 */

type Preset = {
  id: number;
  slug: string;
  title: string;
  subtitle: string;
  preview_video: string;
  preview_poster: string;
  duration: number;
  aspect_ratio: string;
  credits: number;
  category: string;
};

type Category = { slug: string; title: string; emoji: string };

type Project = {
  id: number;
  title: string;
  status: "draft" | "assembling" | "ready" | "failed";
  aspect_ratio: string;
  character: StudioCharacter | null;
  result_video: string;
  error: string;
  scenes: StudioScene[];
  credits_spent: number;
};

const WORKING: StudioScene["status"][] = ["new", "keyframe", "video"];

export default function CartoonStudio() {
  const { t, i18n } = useTranslation("common");
  const [presets, setPresets] = useState<Preset[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [activeCat, setActiveCat] = useState("");
  const [characters, setCharacters] = useState<StudioCharacter[]>([]);
  const [character, setCharacter] = useState<StudioCharacter | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [balance, setBalance] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState<number | null>(null);
  const [busyIds, setBusyIds] = useState<Set<number>>(new Set());
  const [assembling, setAssembling] = useState(false);
  // Не хватило кредитов — не ошибка, а точка покупки: человек уже выбрал героя
  // и сцену, и это самый дорогой момент, чтобы упереться в сухую красную строку.
  const [shortfall, setShortfall] = useState<{ required: number; balance: number } | null>(null);
  const [authed, setAuthed] = useState(true);
  const pollRef = useRef<number | null>(null);

  const visiblePresets = activeCat
    ? presets.filter((p) => p.category === activeCat)
    : presets;

  const markBusy = (id: number, on: boolean) =>
    setBusyIds((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  const loadBalance = useCallback(async () => {
    const res = await fetchData<any>("users/profile/", "GET", null, true);
    const b = res?.data?.token_balance ?? res?.data?.data?.token_balance;
    if (Number.isFinite(Number(b))) setBalance(Number(b));
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      // Язык нужен серверу: названия сцен и героев лежат в базе и переводятся
      // там же, поэтому витрина просит их сразу на нужном языке.
      const lang = (i18n.language || "ru").slice(0, 2) === "ky" ? "kg" : (i18n.language || "ru").slice(0, 2);
      const [p, c, mine] = await Promise.all([
        fetchData<{ categories: Category[]; presets: Preset[] }>(`cartoon/presets/?lang=${lang}`, "GET", null, true),
        fetchData<StudioCharacter[]>(`cartoon/characters/?lang=${lang}`, "GET", null, true),
        fetchData<Project[]>("cartoon/projects/", "GET", null, true),
      ]);
      if (!alive) return;
      if (p.ok && p.data) {
        setPresets(p.data.presets || []);
        setCategories(p.data.categories || []);
      }
      if (c.ok && Array.isArray(c.data)) setCharacters(c.data);
      if (!p.ok) setError(t("studio_ui.err_load"));

      // Витрина открыта всем, а свои мультфильмы есть только у вошедших:
      // по ответу этого запроса и понимаем, гость перед нами или нет.
      setAuthed(mine.ok);

      // Продолжаем последний мультфильм, а не начинаем пустой: сцены стоят
      // денег, и терять их при перезагрузке страницы недопустимо.
      const last = (mine.ok && Array.isArray(mine.data) ? mine.data : [])
        .find((x) => x.scenes.length > 0);
      if (last) {
        setProject(last);
        if (last.character) setCharacter(last.character);
      }
      setLoading(false);
      void loadBalance();
    })();
    return () => {
      alive = false;
    };
  }, [loadBalance, i18n.language]);

  // Опрос, пока что-то считается.
  const refresh = useCallback(async (id: number) => {
    const res = await fetchData<Project>(`cartoon/projects/${id}/`, "GET", null, true);
    if (res.ok && res.data) setProject(res.data);
    return res.data || null;
  }, []);

  useEffect(() => {
    const busy =
      !!project &&
      (project.status === "assembling" ||
        project.scenes.some((s) => WORKING.includes(s.status)));
    if (!busy || !project) {
      if (pollRef.current) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }
    if (pollRef.current) return;
    pollRef.current = window.setInterval(() => {
      void refresh(project.id).then(() => void loadBalance());
    }, 4000);
    return () => {
      if (pollRef.current) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [project, refresh, loadBalance]);

  const ensureProject = useCallback(async (): Promise<Project | null> => {
    if (project) return project;
    if (!character) return null;
    const res = await fetchData<Project>(
      "cartoon/projects/", "POST", { character_id: character.id }, true
    );
    if (res.ok && res.data) {
      setProject(res.data);
      return res.data;
    }
    setError((res.data as any)?.detail || t("studio_ui.err_project"));
    return null;
  }, [project, character]);

  const addScene = async (preset: Preset) => {
    // Гость свободно ходит по студии и видит цену, но сцена стоит денег —
    // на этом шаге и просим войти. Возврат — обратно в студию.
    if (!authed) {
      window.location.href = "/auth/signin?next=" + encodeURIComponent("/studio");
      return;
    }
    setError("");
    setShortfall(null);
    setAdding(preset.id);
    const p = await ensureProject();
    if (!p) {
      setAdding(null);
      return;
    }
    const res = await fetchData<StudioScene>(
      `cartoon/projects/${p.id}/scenes/`, "POST", { preset_id: preset.id }, true
    );
    setAdding(null);
    if (res.ok && res.data) {
      await refresh(p.id);
    } else {
      const d = res.data as any;
      if (d?.required) {
        setShortfall({ required: Number(d.required), balance: Number(d.balance ?? 0) });
      } else {
        setError(d?.detail || t("studio_ui.err_scene"));
      }
    }
  };

  const moveScene = async (scene: StudioScene, dir: -1 | 1) => {
    if (!project) return;
    const list = [...project.scenes].sort((a, b) => a.order - b.order);
    const i = list.findIndex((s) => s.id === scene.id);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= list.length) return;
    // Меняем местами и сохраняем обе позиции: сервер хранит явный порядок,
    // а не выводит его из времени создания.
    markBusy(scene.id, true);
    const a = list[i];
    const b = list[j];
    await Promise.all([
      fetchData(`cartoon/scenes/${a.id}/`, "PATCH", { order: b.order }, true),
      fetchData(`cartoon/scenes/${b.id}/`, "PATCH", { order: a.order }, true),
    ]);
    markBusy(scene.id, false);
    await refresh(project.id);
  };

  const retryScene = async (scene: StudioScene) => {
    if (!project) return;
    markBusy(scene.id, true);
    await fetchData(`cartoon/scenes/${scene.id}/`, "PATCH", { retry: true }, true);
    markBusy(scene.id, false);
    await refresh(project.id);
  };

  const deleteScene = async (scene: StudioScene) => {
    if (!project) return;
    markBusy(scene.id, true);
    await fetchData(`cartoon/scenes/${scene.id}/`, "DELETE", null, true);
    markBusy(scene.id, false);
    await refresh(project.id);
  };

  const assemble = async () => {
    if (!project) return;
    setAssembling(true);
    setError("");
    const res = await fetchData<Project>(
      `cartoon/projects/${project.id}/assemble/`, "POST", {}, true
    );
    setAssembling(false);
    if (res.ok && res.data) setProject(res.data);
    else setError((res.data as any)?.detail || t("studio_ui.err_assemble"));
  };

  const scenes = project ? [...project.scenes].sort((a, b) => a.order - b.order) : [];
  const readyCount = scenes.filter((s) => s.status === "ready").length;
  const working = scenes.some((s) => WORKING.includes(s.status));

  if (loading) {
    return (
      <div className="mx-auto max-w-5xl space-y-4 px-4 pt-24 sm:pt-28 pb-16">
        <div className="h-8 w-64 animate-pulse rounded-lg bg-surface-2" />
        <div className="h-40 animate-pulse rounded-2xl bg-surface-2" />
        <div className="h-64 animate-pulse rounded-2xl bg-surface-2" />
      </div>
    );
  }

  return (
    // pt-24/28 — как на /models: шапка сайта fixed, и без отступа заголовок
    // оказывался ПОД меню (жалоба клиента: «2 текста в одном месте»).
    <main className="mx-auto max-w-5xl px-4 pt-24 sm:pt-28 pb-16">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-foreground sm:text-3xl">{t("studio_ui.title")}</h1>
        <p className="mt-1 text-sm text-muted">
          {t("studio_ui.subtitle")}
        </p>
      </header>

      {error && (
        <div className="mb-4 rounded-xl border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-400">
          {error}
        </div>
      )}

      {shortfall && (
        <div className="mb-4 flex flex-col gap-3 rounded-2xl border border-accent/40 bg-accent/5 p-4 sm:flex-row sm:items-center">
          <div className="flex-1">
            <p className="text-sm font-semibold text-foreground">
              {t("studio_ui.short_title", {
                count: Math.max(0, shortfall.required - shortfall.balance),
              })}
            </p>
            <p className="mt-0.5 text-sm text-muted">
              {t("studio_ui.short_note", {
                required: shortfall.required,
                balance: shortfall.balance,
              })}
            </p>
          </div>
          <a
            href="/pricing/studio"
            className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold text-on-accent transition-colors hover:bg-accent-strong"
          >
            <FiZap />
            {t("studio_ui.short_cta")}
          </a>
        </div>
      )}

      <CharacterPicker
        characters={characters}
        value={character}
        onPick={setCharacter}
        onCreated={(c) => setCharacters((prev) => [c, ...prev])}
        balance={balance}
      />

      {/* Сцены и таймлайн показываем только после выбора героя: без него
          добавлять сцены некуда, и лишние блоки только путают. */}
      {character && (
        <>
          <section className="mt-8 flex flex-col gap-4">
            <div>
              <h2 className="text-lg font-bold text-foreground">{t("studio_ui.step2")}</h2>
              <p className="mt-0.5 text-sm text-muted">
                {t("studio_ui.step2_note")}
              </p>
            </div>

            {/* Разделы: сцен три десятка, и одной простынёй они не читаются —
                человек ищет не «сцену вообще», а начало, погоню или финал. */}
            {categories.length > 1 && (
              <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden sm:mx-0 sm:flex-wrap sm:px-0">
                {[{ slug: "", title: t("studio_ui.cat_all"), emoji: "🎞" }, ...categories].map((c) => (
                  <button
                    key={c.slug || "all"}
                    type="button"
                    onClick={() => setActiveCat(c.slug)}
                    className={`shrink-0 rounded-full border px-3 py-1.5 text-[13px] font-medium transition-colors cursor-pointer ${
                      activeCat === c.slug
                        ? "border-accent bg-accent text-on-accent"
                        : "border-border bg-surface text-muted hover:text-foreground"
                    }`}
                  >
                    {c.emoji && <span className="mr-1">{c.emoji}</span>}
                    {c.title}
                  </button>
                ))}
              </div>
            )}

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              {visiblePresets.map((p) => (
                <div
                  key={p.id}
                  className="flex flex-col overflow-hidden rounded-2xl border border-border bg-surface"
                >
                  <div className="relative aspect-video bg-surface-2">
                    {p.preview_video ? (
                      <video
                        src={p.preview_video}
                        poster={p.preview_poster || undefined}
                        muted
                        loop
                        playsInline
                        preload="metadata"
                        onMouseEnter={(e) => void e.currentTarget.play().catch(() => {})}
                        onMouseLeave={(e) => {
                          e.currentTarget.pause();
                          e.currentTarget.currentTime = 0;
                        }}
                        className="h-full w-full object-cover"
                      />
                    ) : p.preview_poster ? (
                      /* eslint-disable-next-line @next/next/no-img-element */
                      <img src={p.preview_poster} alt="" className="h-full w-full object-cover" />
                    ) : (
                      <span className="grid h-full w-full place-items-center text-muted-2">
                        <FiFilm className="text-2xl" />
                      </span>
                    )}
                  </div>
                  <div className="flex flex-1 flex-col gap-1 p-2.5">
                    <span className="text-sm font-semibold text-foreground">{p.title}</span>
                    {p.subtitle && (
                      <span className="text-[11px] leading-snug text-muted-2">{p.subtitle}</span>
                    )}
                    <div className="mt-auto flex items-center gap-2 pt-2">
                      <span className="inline-flex items-center gap-1 text-[11px] text-muted">
                        <FiZap className="text-accent" />
                        {t("studio_ui.price", { credits: p.credits, duration: p.duration })}
                      </span>
                      <button
                        type="button"
                        onClick={() => void addScene(p)}
                        disabled={adding !== null}
                        className="ml-auto inline-flex items-center gap-1 rounded-lg bg-accent px-2.5 py-1 text-[11px] font-semibold text-on-accent transition-colors hover:bg-accent-strong disabled:opacity-60 cursor-pointer"
                      >
                        {adding === p.id ? (
                          <FiLoader className="animate-spin" />
                        ) : (
                          <FiPlus />
                        )}
                        {t("studio_ui.add")}
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="mt-8 flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-bold text-foreground">{t("studio_ui.step3")}</h2>
              {scenes.length > 0 && (
                <span className="text-sm text-muted">
                  {t("studio_ui.progress", { ready: readyCount, total: scenes.length })}
                  {project && project.credits_spent > 0 &&
                    t("studio_ui.spent", { count: project.credits_spent })}
                </span>
              )}
            </div>

            <SceneTimeline
              scenes={scenes}
              busyIds={busyIds}
              onMove={moveScene}
              onRetry={retryScene}
              onDelete={deleteScene}
            />

            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => void assemble()}
                disabled={!readyCount || assembling || project?.status === "assembling"}
                className="inline-flex items-center gap-2 rounded-full bg-accent px-5 py-2.5 text-sm font-bold text-on-accent transition-colors hover:bg-accent-strong disabled:opacity-50 cursor-pointer"
              >
                {assembling || project?.status === "assembling" ? (
                  <FiLoader className="animate-spin" />
                ) : (
                  <FiFilm />
                )}
                {t("studio_ui.assemble")}
              </button>
              {working && (
                <span className="text-xs text-muted">
                  {t("studio_ui.working_note")}
                </span>
              )}
              {!readyCount && !working && scenes.length === 0 && (
                <span className="text-xs text-muted-2">{t("studio_ui.empty_hint")}</span>
              )}
            </div>
          </section>

          {project?.result_video && (
            <section className="mt-8 flex flex-col gap-3">
              <h2 className="text-lg font-bold text-foreground">{t("studio_ui.result")}</h2>
              <video
                src={project.result_video}
                controls
                playsInline
                className="w-full rounded-2xl border border-border bg-black"
              />
              {/* Не <a download>: на iPhone он не скачивает, а открывает файл
                  серой заглушкой «Открыть в iMovie» (жалоба клиента). */}
              <SaveMediaButton
                url={project.result_video}
                filename="esai-cartoon.mp4"
                label={t("studio_ui.download_label")}
                className="inline-flex w-fit cursor-pointer items-center gap-2 rounded-full border border-accent px-4 py-2 text-sm font-semibold text-accent transition-colors hover:bg-accent-soft"
              >
                {t("studio_ui.download")}
              </SaveMediaButton>
            </section>
          )}

          {project?.status === "failed" && project.error && (
            <p className="mt-3 text-sm text-red-400">Склейка не удалась: {project.error}</p>
          )}
        </>
      )}
    </main>
  );
}

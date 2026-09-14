"use client";

import { useTranslation } from "react-i18next";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FiChevronDown, FiFilm, FiLoader, FiPlay, FiPlus, FiUser, FiZap } from "react-icons/fi";
import { fetchData } from "@/tools/fetchData";
import { trackFunnel } from "@/tools/funnel";
import { getOrCreateDeviceKey } from "@/tools/deviceKey";
import {
  MAX_DRAFT_SCENES,
  clearDraft,
  emptyDraft,
  isFreeTryUsed,
  loadDraft,
  markFreeTryUsed,
  newSceneKey,
  recallProject,
  rememberProject,
  saveDraft,
  type StudioDraft,
} from "@/lib/studioDraft";
import SaveMediaButton from "@/components/ui/SaveMediaButton";
import ShareButtons from "@/components/ui/ShareButtons";
import { StudioAuthDialog, StudioPaywallDialog } from "./StudioDialogs";
import CharacterPicker, { type StudioCharacter } from "./CharacterPicker";
import SceneTimeline, { type StudioScene } from "./SceneTimeline";
import { apiLang } from "@/lib/apiLang";

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
  /** Цена примерки героя — показываем на кнопке до запуска. */
  tryon_credits?: number;
  category: string;
  audience: "kids" | "adults";
  is_pick: boolean;
};

type AuthReason = "character" | "scene" | "tryon" | "render";

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
  created_at?: string;
};

const WORKING: StudioScene["status"][] = ["new", "keyframe", "video"];

/** Сколько сцен показываем за раз. Шесть — просьба клиента, ради медленного интернета. */
const PAGE_SIZE = 6;

export default function CartoonStudio() {
  const { t, i18n } = useTranslation("common");
  const [presets, setPresets] = useState<Preset[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  // Подборки наверху библиотеки: «Популярное» приходит с сервера по
  // реальным добавлениям, «Выбор EsAI» помечен у самих сцен в админке.
  const [popular, setPopular] = useState<string[]>([]);
  const [activeCat, setActiveCat] = useState("");
  // Показываем по горсти карточек, остальное — по кнопке. У многих в Кыргызстане
  // медленный мобильный интернет, а сразу полторы сотни превью — это и запросы,
  // и память телефона на ровном месте.
  const [shown, setShown] = useState(PAGE_SIZE);
  // Что сейчас играет. В ленте ролики заводятся сами, как только карточка
  // появилась на экране, — по просьбе клиента, «как в мини-приложениях».
  // Играют только видимые: держать сотню запущенных видео нельзя ни по
  // трафику, ни по памяти телефона.
  const [visibleIds, setVisibleIds] = useState<Set<number>>(new Set());
  // Ручное проигрывание — запасной путь для тех, у кого автозапуск выключен
  // (экономия трафика или системная просьба убрать анимации).
  const [previewing, setPreviewing] = useState<number | null>(null);
  const [autoplay, setAutoplay] = useState(true);
  const cardObserver = useRef<IntersectionObserver | null>(null);
  // Для кого снимаем. Разделов девятнадцать, героев больше двух десятков, и
  // взрослому сюжету нужен взрослый герой — поэтому один переключатель наверху
  // сужает сразу оба списка.
  const [audience, setAudience] = useState<"all" | "kids" | "adults">("all");
  // Сцены видны сразу, без выбора героя (просьба клиента), поэтому нажатие
  // «В ленту» без героя не ошибка, а подсказка с прокруткой к первому шагу.
  const [needHero, setNeedHero] = useState(false);
  const [characters, setCharacters] = useState<StudioCharacter[]>([]);
  const [character, setCharacter] = useState<StudioCharacter | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  // Все мультфильмы пользователя. Нужны не для красоты: как только человек
  // начинает новый, старый перестаёт быть «последним» и без списка исчезает
  // из интерфейса вместе с оплаченными сценами.
  const [projects, setProjects] = useState<Project[]>([]);
  const [balance, setBalance] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState<number | null>(null);
  const [busyIds, setBusyIds] = useState<Set<number>>(new Set());
  const [assembling, setAssembling] = useState(false);
  // Не хватило кредитов — не ошибка, а точка покупки: человек уже выбрал героя
  // и сцену, и это самый дорогой момент, чтобы упереться в сухую красную строку.
  const [shortfall, setShortfall] = useState<
    { required: number; balance: number; kind?: "scene" | "character" } | null
  >(null);
  const [authFor, setAuthFor] = useState<AuthReason | null>(null);
  const [authed, setAuthed] = useState(true);
  // Лента гостя. Клиент: без регистрации человек выбирает героя, набирает
  // сцены и видит результат — а войти просим, когда ему уже есть что терять.
  // Живёт в браузере и после входа переезжает в настоящий проект.
  const [draft, setDraft] = useState<StudioDraft | null>(null);
  // Одна бесплатная примерка на устройство. Решает сервер, здесь только
  // подпись кнопки: «бесплатно» или обычная.
  const [freeTryUsed, setFreeTryUsed] = useState(false);
  const pollRef = useRef<number | null>(null);
  const heroRef = useRef<HTMLDivElement | null>(null);
  const timelineRef = useRef<HTMLDivElement | null>(null);
  // Примерка героя: кадр «этот герой в этой сцене». Готовые пары приходят с
  // сервера бесплатно и подставляются сами — клиент просил, чтобы выбранный
  // герой сразу был виден в примерах. Недостающие рисуются по кнопке.
  // Кадры храним по героям: в ленте у каждой сцены может быть свой герой, и
  // карточке нужен кадр именно её персонажа.
  const [framesByChar, setFramesByChar] = useState<Record<number, Record<number, string>>>({});
  // Ролики пар «герой + сцена», уже снятые кем-то раньше: движущееся превью
  // сцены именно с этим героем, без новой генерации (просьба клиента).
  const [videosByChar, setVideosByChar] = useState<Record<number, Record<number, string>>>({});
  const fetchedChars = useRef<Set<number>>(new Set());
  const [tryingOn, setTryingOn] = useState<number | null>(null);
  // Своя сцена: вместо готового пресета человек пишет, что делает герой
  // (клиент: «быстро выбрать готовую сцену или самому описать, что хочешь»).
  const [customText, setCustomText] = useState("");
  const [framingId, setFramingId] = useState<number | null>(null);
  const [shareUrl, setShareUrl] = useState("");
  const [sharing, setSharing] = useState(false);

  useEffect(() => {
    // Системная просьба «меньше движения» и режим экономии трафика — повод не
    // заводить ничего самому: человек попросил об этом на уровне устройства.
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
    const saveData = Boolean((navigator as any)?.connection?.saveData);
    if (reduce || saveData) {
      setAutoplay(false);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        setVisibleIds((prev) => {
          const next = new Set(prev);
          for (const e of entries) {
            const id = Number((e.target as HTMLElement).dataset.presetId || 0);
            if (!id) continue;
            if (e.isIntersecting) next.add(id);
            else next.delete(id);
          }
          return next;
        });
      },
      // Половина карточки на экране: иначе ролики заводятся у самого края и
      // гаснут, не успев показать ни кадра.
      { threshold: 0.5 }
    );
    cardObserver.current = io;
    return () => io.disconnect();
  }, []);

  const watchCard = useCallback((el: HTMLDivElement | null) => {
    if (el) cardObserver.current?.observe(el);
  }, []);

  // Готовые кадры героев. Их отдают бесплатно, поэтому подставляем сразу и
  // молча: для человека это выглядит так, будто сцены сами перерисовались под
  // его персонажа. Спрашиваем по каждому герою один раз — и для выбранного, и
  // для тех, кого поставили на отдельные сцены ленты.
  const wantedChars = useMemo(() => {
    const ids = new Set<number>();
    if (character) ids.add(character.id);
    for (const s of draft?.scenes || []) if (s.character_id) ids.add(s.character_id);
    for (const s of project?.scenes || []) if (s.character?.id) ids.add(s.character.id);
    return [...ids].sort((a, b) => a - b).join(",");
  }, [character, draft, project]);

  useEffect(() => {
    const ids = wantedChars ? wantedChars.split(",").map(Number) : [];
    for (const id of ids) {
      if (fetchedChars.current.has(id)) continue;
      fetchedChars.current.add(id);
      void (async () => {
        const res = await fetchData<Record<string, { frame: string; video: string }>>(
          `cartoon/previews/?character_id=${id}`, "GET", null, true
        );
        if (!res.ok || !res.data) {
          fetchedChars.current.delete(id);
          return;
        }
        const frames: Record<number, string> = {};
        const videos: Record<number, string> = {};
        for (const [pid, row] of Object.entries(res.data)) {
          if (row?.frame) frames[Number(pid)] = row.frame;
          if (row?.video) videos[Number(pid)] = row.video;
        }
        setFramesByChar((prev) => ({ ...prev, [id]: { ...frames, ...(prev[id] || {}) } }));
        setVideosByChar((prev) => ({ ...prev, [id]: { ...videos, ...(prev[id] || {}) } }));
      })();
    }
  }, [wantedChars]);

  const tryOn: Record<number, string> = (character && framesByChar[character.id]) || {};
  const heroVideos: Record<number, string> = (character && videosByChar[character.id]) || {};

  /** Окно входа — и отметка в воронке: это главный шаг, который мы меряем. */
  const openAuth = (reason: AuthReason) => {
    setAuthFor(reason);
    trackFunnel("studio_auth_prompt", { reason });
  };

  /** Окно «не хватает кредитов» — точка покупки, её тоже считаем. */
  const openPaywall = (value: { required: number; balance: number; kind?: "scene" | "character" }) => {
    setShortfall(value);
    trackFunnel("studio_paywall", { kind: value.kind || "scene", required: value.required });
  };

  /** Нарисовать кадр этой сцены с выбранным героем. */
  const tryOnScene = async (preset: Preset) => {
    if (!character) {
      setNeedHero(true);
      heroRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    trackFunnel("studio_tryon", { preset_id: preset.id, authed });
    const heroId = character.id;
    setTryingOn(preset.id);
    // Гость шлёт запрос без токена: ответ «нужен вход» (403) иначе принимается
    // за истёкшую сессию и уводит со страницы. Ключ устройства — чтобы сервер
    // посчитал «одну бесплатную на устройство».
    const res = await fetchData<{ image: string; charged: number; free?: boolean }>(
      `cartoon/presets/${preset.id}/try-on/`, "POST", { character_id: heroId }, authed,
      { "X-Device-Key": getOrCreateDeviceKey() }
    );
    setTryingOn(null);
    if (res.ok && res.data?.image) {
      const image = res.data.image;
      setFramesByChar((prev) => ({ ...prev, [heroId]: { ...(prev[heroId] || {}), [preset.id]: image } }));
      if (res.data.free) {
        markFreeTryUsed();
        setFreeTryUsed(true);
      }
      if (res.data.charged) void loadBalance();
      return;
    }
    const d = res.data as any;
    if (d?.need_auth) {
      if (d.reason === "used") {
        markFreeTryUsed();
        setFreeTryUsed(true);
      }
      openAuth("tryon");
      return;
    }
    if (d?.required) {
      openPaywall({ required: Number(d.required), balance: Number(d.balance ?? 0), kind: "character" });
    } else {
      setError(d?.detail || t("studio_ui.err_tryon"));
    }
  };

  /** Изменить ленту гостя и сразу сохранить её в браузере. */
  const updateDraft = useCallback(
    (change: (d: StudioDraft) => StudioDraft) => {
      setDraft((prev) => saveDraft(change(prev || emptyDraft(character?.id ?? null))));
    },
    [character]
  );

  const byAudience = (p: Preset) => audience === "all" || p.audience === audience;

  // Раздел показываем, только если в нём есть что смотреть при текущем выборе
  // аудитории — иначе человек ткнёт в «Спорт» и увидит пустоту.
  const visibleCategories = categories.filter((c) =>
    presets.some((p) => p.category === c.slug && byAudience(p))
  );

  const picks = presets.filter((p) => p.is_pick && byAudience(p));
  const popularPresets = popular
    .map((slug) => presets.find((p) => p.slug === slug))
    .filter((p): p is Preset => Boolean(p) && byAudience(p as Preset));

  // Свои персонажи показываются всегда: человек загрузил их сам, и прятать их
  // за чужим делением на «детское/взрослое» было бы странно.
  const visibleCharacters =
    audience === "all"
      ? characters
      : characters.filter((c) => c.is_mine || c.audience === audience);

  const allPresets =
    activeCat === "__pick"
      ? picks
      : activeCat === "__popular"
      ? popularPresets
      : activeCat
      ? presets.filter((p) => p.category === activeCat && byAudience(p))
      : presets.filter(byAudience);

  const visiblePresets = allPresets.slice(0, shown);
  const restCount = Math.max(0, allPresets.length - visiblePresets.length);

  // Сколько роликов крутим разом. На широком экране в поле зрения попадает до
  // дюжины карточек, и заводить их все — лишний трафик без выигрыша: человек
  // всё равно смотрит на две-три.
  const MAX_PLAYING = 6;
  const playingIds = new Set(
    autoplay
      ? visiblePresets.filter((p) => visibleIds.has(p.id)).slice(0, MAX_PLAYING).map((p) => p.id)
      : []
  );

  const pickAudience = (next: "all" | "kids" | "adults") => {
    // Список карточек сменился целиком — прежние отметки видимости больше ни
    // к чему не относятся, и показ начинаем с первой горсти.
    setVisibleIds(new Set());
    setShown(PAGE_SIZE);
    setAudience(next);
    if (activeCat && !activeCat.startsWith("__") && next !== "all") {
      const still = presets.some((p) => p.category === activeCat && p.audience === next);
      if (!still) setActiveCat("");
    }
  };

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
      const lang = apiLang(i18n.language);
      const [p, c, mine] = await Promise.all([
        fetchData<{ categories: Category[]; presets: Preset[]; popular: string[] }>(
          `cartoon/presets/?lang=${lang}`, "GET", null, true),
        fetchData<StudioCharacter[]>(`cartoon/characters/?lang=${lang}`, "GET", null, true),
        fetchData<Project[]>(`cartoon/projects/?lang=${lang}`, "GET", null, true),
      ]);
      if (!alive) return;
      if (p.ok && p.data) {
        setPresets(p.data.presets || []);
        setCategories(p.data.categories || []);
        setPopular(p.data.popular || []);
      }
      const chars = c.ok && Array.isArray(c.data) ? c.data : [];
      setCharacters(chars);
      if (!p.ok) setError(t("studio_ui.err_load"));

      // Витрина открыта всем, а свои мультфильмы есть только у вошедших:
      // по ответу этого запроса и понимаем, гость перед нами или нет.
      setAuthed(mine.ok);
      // Первый шаг воронки. Неделю рекламы студия не отправляла его вовсе —
      // и о 700 посетителях в день мы узнавали из чужой статистики.
      trackFunnel("studio_view", { authed: mine.ok });

      if (!mine.ok) {
        // Гость: поднимаем его ленту, если он уже начинал собирать.
        const saved = loadDraft();
        if (saved) {
          setDraft(saved);
          const hero = chars.find((x) => x.id === saved.character_id);
          if (hero) setCharacter(hero);
        }
        setFreeTryUsed(isFreeTryUsed());
        setLoading(false);
        return;
      }

      // Продолжаем последний мультфильм, а не начинаем пустой: сцены стоят
      // денег, и терять их при перезагрузке страницы недопустимо.
      const mineList = mine.ok && Array.isArray(mine.data) ? mine.data : [];
      setProjects(mineList);

      // Только что вошёл, а в браузере лежит лента, собранная гостем: переносим
      // её в настоящий проект и открываем именно его (просьба клиента: «вернуть
      // пользователя именно в этот проект»).
      let imported: Project | null = null;
      const saved = loadDraft();
      if (saved?.scenes.length && saved.character_id) {
        // Сбой переноса не должен оставить студию на заглушке загрузки:
        // черновик останется в браузере, и перенос повторится при следующем
        // открытии (сервер по ключу черновика второго проекта не заведёт).
        try {
          const res = await fetchData<Project>("cartoon/projects/import/", "POST", {
            draft_id: saved.id,
            character_id: saved.character_id,
            scenes: saved.scenes.map((s) => ({
              preset_id: s.preset_id,
              character_id: s.character_id,
              // Своя сцена переезжает вместе с описанием, иначе она пропала бы.
              ...(s.custom_text ? { custom_text: s.custom_text } : {}),
            })),
          }, true);
          if (!alive) return;
          if (res.ok && res.data) {
            const fresh = res.data;
            imported = fresh;
            clearDraft();
            setProjects((prev) => [fresh, ...prev.filter((x) => x.id !== fresh.id)]);
          }
        } catch {
          // тихо: остаёмся на обычном открытии студии
        }
      } else if (saved) {
        clearDraft();
      }

      // Бот и Mini App открывают конкретный мультфильм: ?project=<id>. После
      // оплаты и входа возвращаемся к тому, что было открыто последним, — а
      // не к «какому-нибудь последнему с сценами».
      const wanted = Number(new URLSearchParams(window.location.search).get("project") || 0);
      const remembered = recallProject();
      const last = imported
        || (wanted && mineList.find((x) => x.id === wanted))
        || (remembered && mineList.find((x) => x.id === remembered))
        || mineList.find((x) => x.scenes.length > 0);
      if (last) {
        setProject(last);
        if (last.character) setCharacter(last.character);
      }
      setLoading(false);
      void loadBalance();
      if (imported) {
        window.setTimeout(
          () => timelineRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
          400
        );
      }
    })();
    return () => {
      alive = false;
    };
  }, [loadBalance, i18n.language]);

  // Опрос, пока что-то считается.
  const refresh = useCallback(async (id: number) => {
    const res = await fetchData<Project>(`cartoon/projects/${id}/`, "GET", null, true);
    if (res.ok && res.data) {
      const fresh = res.data;
      setProject(fresh);
      setProjects((prev) => prev.map((x) => (x.id === fresh.id ? fresh : x)));
    }
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
      setProjects((prev) => [res.data as Project, ...prev]);
      return res.data;
    }
    setError((res.data as any)?.detail || t("studio_ui.err_project"));
    return null;
  }, [project, character]);

  // Открытый мультфильм запоминаем: после оплаты и входа студия откроет его же.
  useEffect(() => {
    if (project?.id) rememberProject(project.id);
  }, [project?.id]);

  const addScene = async (preset: Preset) => {
    if (!authed) {
      // Гость собирает ленту без входа (просьба клиента): она живёт в браузере,
      // а войти мы попросим, когда он захочет снимать.
      if (!character) {
        setNeedHero(true);
        heroRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
        return;
      }
      if ((draft?.scenes.length || 0) >= MAX_DRAFT_SCENES) {
        setError(t("studio_ui.err_draft_full"));
        return;
      }
      setNeedHero(false);
      // Сцена запоминает героя, с которым её добавили: сменил героя для
      // следующей сцены — предыдущая остаётся со своим (правило клиента).
      updateDraft((d) => ({
        ...d,
        character_id: d.character_id ?? character.id,
        scenes: [...d.scenes, { key: newSceneKey(), preset_id: preset.id, character_id: character.id }],
      }));
      trackFunnel("studio_scene_add", { preset_id: preset.id, authed: false });
      window.setTimeout(
        () => timelineRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }),
        60
      );
      return;
    }
    if (!character) {
      // Сцены видны сразу, но снимать их не с кем — ведём к первому шагу.
      setNeedHero(true);
      heroRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    setError("");
    setNeedHero(false);
    setShortfall(null);
    setAdding(preset.id);
    const p = await ensureProject();
    if (!p) {
      setAdding(null);
      return;
    }
    // Героя передаём явно: иначе сцена снялась бы с героем, с которого начат
    // мультфильм, а не с тем, кого человек выбрал сейчас.
    const res = await fetchData<StudioScene>(
      `cartoon/projects/${p.id}/scenes/`, "POST", { preset_id: preset.id, character_id: character.id }, true
    );
    setAdding(null);
    if (res.ok && res.data) {
      trackFunnel("studio_scene_add", { preset_id: preset.id, authed: true });
      await refresh(p.id);
      // Лента ниже сцен, и без прокрутки человек не понимает, куда делась
      // добавленная сцена.
      timelineRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } else {
      setError((res.data as any)?.detail || t("studio_ui.err_scene"));
    }
  };

  /** Снять сцену из ленты. Здесь и только здесь тратятся кредиты. */
  const renderScene = async (scene: StudioScene) => {
    if (!project) return;
    trackFunnel("studio_render_click", { authed: true, scene_id: scene.id });
    markBusy(scene.id, true);
    const res = await fetchData<StudioScene>(
      `cartoon/scenes/${scene.id}/render/`, "POST", {}, true
    );
    markBusy(scene.id, false);
    if (res.ok) {
      await refresh(project.id);
      return;
    }
    const d = res.data as any;
    if (d?.required) {
      openPaywall({ required: Number(d.required), balance: Number(d.balance ?? 0) });
    } else {
      setError(d?.detail || t("studio_ui.err_scene"));
    }
  };

  // --- лента гостя: те же действия, что у проекта, но над черновиком ---
  // У черновика нет id из базы, поэтому сцена ленты получает отрицательный id,
  // а по нему восстанавливается её место в черновике.
  const guestIndex = (scene: StudioScene) => -scene.id - 1;

  const guestMove = (scene: StudioScene, dir: -1 | 1) =>
    updateDraft((d) => {
      const list = [...d.scenes];
      const i = guestIndex(scene);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= list.length) return d;
      [list[i], list[j]] = [list[j], list[i]];
      return { ...d, scenes: list };
    });

  const guestDelete = (scene: StudioScene) =>
    updateDraft((d) => ({ ...d, scenes: d.scenes.filter((_, i) => i !== guestIndex(scene)) }));

  const guestPickCharacter = (scene: StudioScene, characterId: number) =>
    updateDraft((d) => ({
      ...d,
      scenes: d.scenes.map((s, i) => (i === guestIndex(scene) ? { ...s, character_id: characterId } : s)),
    }));

  /** Добавить свою сцену по описанию. Ничего не генерируется и не списывается. */
  const addCustomScene = async () => {
    const text = customText.replace(/\s+/g, " ").trim().slice(0, 300);
    if (text.length < 3) {
      setError(t("studio_ui.custom_too_short"));
      return;
    }
    if (!character) {
      setNeedHero(true);
      heroRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    setError("");
    setNeedHero(false);
    const scrollToTimeline = () =>
      window.setTimeout(
        () => timelineRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }),
        60
      );

    if (!authed) {
      if ((draft?.scenes.length || 0) >= MAX_DRAFT_SCENES) {
        setError(t("studio_ui.err_draft_full"));
        return;
      }
      updateDraft((d) => ({
        ...d,
        character_id: d.character_id ?? character.id,
        scenes: [...d.scenes, {
          key: newSceneKey(), preset_id: 0, character_id: character.id, custom_text: text,
        }],
      }));
      trackFunnel("studio_scene_add", { custom: true, authed: false });
      setCustomText("");
      scrollToTimeline();
      return;
    }

    setAdding(-1);
    const p = await ensureProject();
    if (!p) {
      setAdding(null);
      return;
    }
    const res = await fetchData<StudioScene>(
      `cartoon/projects/${p.id}/scenes/`, "POST", { custom_text: text, character_id: character.id }, true
    );
    setAdding(null);
    if (res.ok && res.data) {
      trackFunnel("studio_scene_add", { custom: true, authed: true });
      setCustomText("");
      await refresh(p.id);
      scrollToTimeline();
    } else {
      setError((res.data as any)?.detail || t("studio_ui.err_scene"));
    }
  };

  /** Кадр своей сцены до съёмки — увидеть, что получится. */
  const frameScene = async (scene: StudioScene) => {
    if (!authed || !project) {
      openAuth("render");
      return;
    }
    setFramingId(scene.id);
    setError("");
    const res = await fetchData<StudioScene>(`cartoon/scenes/${scene.id}/frame/`, "POST", {}, true);
    setFramingId(null);
    if (res.ok) {
      await refresh(project.id);
      void loadBalance();
      return;
    }
    const d = res.data as any;
    if (d?.required) {
      openPaywall({ required: Number(d.required), balance: Number(d.balance ?? 0), kind: "character" });
    } else {
      setError(d?.detail || t("studio_ui.err_tryon"));
    }
  };

  /** Выбрать героя для следующих сцен. Уже набранные сцены своих героев не меняют. */
  const pickHero = (c: StudioCharacter) => {
    setCharacter(c);
    setNeedHero(false);
    trackFunnel("studio_hero_pick", { character_id: c.id, authed });
    // Первый выбранный герой становится героем мультфильма — с ним проект
    // переедет после входа. Дальше у каждой сцены свой.
    if (!authed) updateDraft((d) => ({ ...d, character_id: d.character_id ?? c.id }));
  };

  /** Снимать гость не может — это деньги и аккаунт. Здесь и просим войти. */
  const guestRender = (from: "scene" | "cta") => {
    trackFunnel("studio_render_click", { authed: false, from });
    openAuth("render");
  };

  /** Поставить на сцену другого героя. Работает, пока сцена не снята. */
  const setSceneCharacter = async (scene: StudioScene, characterId: number) => {
    if (!project) return;
    markBusy(scene.id, true);
    await fetchData(`cartoon/scenes/${scene.id}/`, "PATCH",
                    { character_id: characterId }, true);
    markBusy(scene.id, false);
    await refresh(project.id);
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

  /** Начать новый мультфильм: проект обнуляется, герой остаётся выбранным —
   *  чаще всего следующую историю снимают тем же персонажем. Старый проект
   *  никуда не девается, к нему можно вернуться списком ниже. */
  const startNewMovie = () => {
    setShareUrl("");
    setProject(null);
    setShortfall(null);
    setError("");
    setBusyIds(new Set());
  };

  const openProject = async (id: number) => {
    setShareUrl("");
    setShortfall(null);
    setError("");
    const known = projects.find((x) => x.id === id);
    if (known) setProject(known);
    const fresh = await refresh(id);
    if (fresh?.character) setCharacter(fresh.character);
  };

  // Пустые черновики в список не берём: проект создаётся при первой сцене, и
  // брошенная попытка не должна засорять переключатель.
  const myMovies = projects.filter((m) => m.scenes.length > 0);

  /** Ссылка на публичную страницу мультфильма.
   *
   *  Делимся именно ей, а не файлом: страница несёт og:video (мессенджеры
   *  играют ролик прямо в переписке) и призыв «Создайте свой мультфильм» с
   *  переходом в студию. Отправленный mp4 не сказал бы про EsAI ничего.
   */
  const makeShareLink = useCallback(async () => {
    if (!project?.result_video || shareUrl || sharing) return;
    setSharing(true);
    const res = await fetchData<{ share_url: string }>(
      "ai/video/share/", "POST", { url: project.result_video }, true
    );
    setSharing(false);
    if (res.ok && res.data?.share_url) setShareUrl(res.data.share_url);
  }, [project?.result_video, shareUrl, sharing]);

  // Готовый ролик появляется после склейки — ссылку готовим сразу, чтобы
  // кнопки соцсетей не заставляли ждать ещё один запрос.
  useEffect(() => {
    if (project?.result_video) void makeShareLink();
  }, [project?.result_video, makeShareLink]);

  // Лента гостя в том же виде, что и сцены проекта: так её рисует та же
  // SceneTimeline, и гость видит ровно то, что увидит после входа.
  const presetById = new Map(presets.map((p) => [p.id, p]));
  const charById = new Map(characters.map((c) => [c.id, c]));
  const guestScenes: StudioScene[] =
    !authed && draft
      ? draft.scenes.map((s, i) => {
          const custom = Boolean(s.custom_text);
          const p = custom ? undefined : presetById.get(s.preset_id);
          const heroId = s.character_id ?? draft.character_id ?? character?.id ?? null;
          const hero = heroId ? charById.get(heroId) : undefined;
          return {
            id: -(i + 1),
            order: i,
            custom_text: s.custom_text || "",
            preset: {
              id: s.preset_id,
              title: custom ? (s.custom_text || "").slice(0, 60) : p?.title || "…",
              // Своя сцена стоит как готовая: те же кадр и видео.
              credits: custom ? presets[0]?.credits : p?.credits,
              duration: custom ? presets[0]?.duration : p?.duration,
              poster: custom ? "" : p?.preview_poster,
              clip: custom ? "" : p?.preview_video,
            },
            character: hero ? { id: hero.id, name: hero.name, image: hero.image } : null,
            keyframe: custom ? "" : (heroId && framesByChar[heroId]?.[s.preset_id]) || "",
            preview_video: custom ? "" : (heroId && videosByChar[heroId]?.[s.preset_id]) || "",
            video: "",
            status: "draft",
            error: "",
            credits_spent: 0,
          };
        })
      : [];

  const scenes = !authed
    ? guestScenes
    : project
    ? [...project.scenes]
        .sort((a, b) => a.order - b.order)
        // Героя сцены сменили — ролик новой пары известен сразу, не дожидаясь
        // ответа сервера: превью переключается мгновенно (просьба клиента).
        .map((s) =>
          s.video || s.preview_video || !s.character || s.custom_text
            ? s
            : { ...s, preview_video: videosByChar[s.character.id]?.[s.preset.id] || "" }
        )
    : [];

  // Герои этого мультфильма: все, кого человек уже поставил в сцены. Их
  // держим под рукой — в следующую сцену чаще берут кого-то из уже занятых.
  const cast: StudioCharacter[] = [];
  {
    const seen = new Set<number>();
    const push = (id: number | null | undefined) => {
      if (!id || seen.has(id)) return;
      const c = charById.get(id);
      if (c) {
        seen.add(id);
        cast.push(c);
      }
    };
    for (const s of scenes) push(s.character?.id);
  }
  const castIds = new Set(cast.map((c) => c.id));
  const timelineCharacters = [...cast, ...visibleCharacters.filter((c) => !castIds.has(c.id))];
  const readyCount = scenes.filter((s) => s.status === "ready").length;
  const drafts = scenes.filter((s) => s.status === "draft").length;
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

      {/* Для кого снимаем: сужает и библиотеку героев, и разделы сцен. */}
      {presets.some((p) => p.audience === "adults") && (
        <div className="mb-6 inline-flex rounded-full border border-border bg-surface p-1">
          {([
            ["all", t("studio_ui.aud_all")],
            ["kids", t("studio_ui.aud_kids")],
            ["adults", t("studio_ui.aud_adults")],
          ] as const).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => pickAudience(key)}
              className={`rounded-full px-4 py-1.5 text-sm font-medium transition-colors cursor-pointer ${
                audience === key
                  ? "bg-accent text-on-accent"
                  : "text-muted hover:text-foreground"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-xl border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-400">
          {error}
        </div>
      )}

      <StudioPaywallDialog
        open={Boolean(shortfall)}
        required={shortfall?.required ?? 0}
        balance={shortfall?.balance ?? 0}
        kind={shortfall?.kind ?? "scene"}
        onClose={() => setShortfall(null)}
      />
      <StudioAuthDialog
        open={Boolean(authFor)}
        reason={authFor ?? "render"}
        onClose={() => setAuthFor(null)}
      />

      {/* Свои мультфильмы. Показываем, только когда есть куда переключаться:
          иначе строка занимала бы место у того, кто снимает первый ролик. */}
      {myMovies.length > (project ? 1 : 0) && (
        <div className="mb-6">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-2">
            {t("studio_ui.my_movies")}
          </div>
          <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden sm:mx-0 sm:flex-wrap sm:px-0">
            {myMovies.map((m) => {
              const active = project?.id === m.id;
              return (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => void openProject(m.id)}
                  className={`shrink-0 rounded-xl border px-3 py-2 text-left text-xs transition-colors cursor-pointer ${
                    active
                      ? "border-accent bg-accent/10 text-foreground"
                      : "border-border bg-surface text-muted hover:text-foreground"
                  }`}
                >
                  <span className="block font-semibold">
                    {m.title || t("studio_ui.movie_fallback", { id: m.id })}
                  </span>
                  <span className="mt-0.5 block text-muted-2">
                    {t("studio_ui.movie_scenes", { count: m.scenes.length })}
                    {m.result_video ? ` · ${t("studio_ui.movie_ready")}` : ""}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      <div ref={heroRef} className="scroll-mt-28">
        {needHero && !character && (
          <div className="mb-3 rounded-xl border border-accent/40 bg-accent/5 p-3 text-sm text-foreground">
            {t("studio_ui.need_hero")}
          </div>
        )}
        <CharacterPicker
          authed={authed}
          onNeedAuth={() => openAuth("character")}
          onNeedCredits={(required, bal) => openPaywall({ required, balance: bal, kind: "character" })}
          characters={visibleCharacters}
          value={character}
          onPick={pickHero}
          onCreated={(c) => setCharacters((prev) => [c, ...prev])}
          balance={balance}
        />
      </div>

      {/* Сцены показываем сразу, не дожидаясь выбора героя: клиент попросил,
          чтобы витрину было видно с порога — ради неё в студию и заходят. */}
      {true && (
        <>
          <section className="mt-8 flex flex-col gap-4">
            <div>
              <h2 className="text-lg font-bold text-foreground">{t("studio_ui.step2")}</h2>
              <p className="mt-0.5 text-sm text-muted">
                {t("studio_ui.step2_note")}
              </p>
            </div>

            {/* Своя сцена: второй путь рядом с библиотекой — описать словами, что
                делает герой. Сцена встаёт в ленту черновиком; студия сама
                превратит описание в сцену при съёмке, с тем же героем. */}
            <div className="rounded-2xl border border-border bg-surface-2/60 p-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <span aria-hidden>✍️</span>
                {t("studio_ui.custom_title")}
              </div>
              <p className="mt-1 text-xs text-muted-2">{t("studio_ui.custom_note")}</p>
              <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-start">
                <textarea
                  value={customText}
                  onChange={(e) => setCustomText(e.target.value.slice(0, 300))}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey && adding === null) {
                      e.preventDefault();
                      void addCustomScene();
                    }
                  }}
                  rows={2}
                  placeholder={t("studio_ui.custom_placeholder")}
                  className="min-h-[3rem] flex-1 resize-none rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm text-foreground outline-none placeholder:text-muted-2 focus:border-accent"
                />
                <button
                  type="button"
                  onClick={() => void addCustomScene()}
                  disabled={adding !== null || customText.trim().length < 3}
                  className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-on-accent transition-colors hover:bg-accent-strong disabled:opacity-50 cursor-pointer"
                >
                  {adding === -1 ? <FiLoader className="animate-spin" /> : <FiPlus />}
                  {t("studio_ui.add")}
                </button>
              </div>
              {character && (
                <p className="mt-1.5 text-[11px] text-muted-2">
                  {t("studio_ui.custom_hero", { name: character.name })}
                </p>
              )}
            </div>

            {/* Герои этого мультфильма — под рукой прямо над сценами: следующую
                сцену чаще снимают кем-то из уже занятых, и искать его в
                библиотеке заново не нужно. Сцены показываются с выбранным. */}
            {cast.length > 0 && (
              <div className="-mx-4 flex items-center gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden sm:mx-0 sm:flex-wrap sm:px-0">
                <span className="shrink-0 text-xs font-semibold uppercase tracking-wide text-muted-2">
                  {t("studio_ui.cast_title")}
                </span>
                {cast.map((c) => {
                  const active = character?.id === c.id;
                  return (
                    <button
                      key={c.id}
                      type="button"
                      onClick={() => pickHero(c)}
                      aria-pressed={active}
                      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border py-1 pl-1 pr-2.5 text-xs transition-colors cursor-pointer ${
                        active
                          ? "border-accent bg-accent/10 text-foreground"
                          : "border-border bg-surface text-muted hover:text-foreground"
                      }`}
                    >
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={c.image} alt="" loading="lazy" className="size-6 rounded-full object-cover" />
                      {c.name}
                    </button>
                  );
                })}
              </div>
            )}

            {/* Разделы: сцен три десятка, и одной простынёй они не читаются —
                человек ищет не «сцену вообще», а начало, погоню или финал. */}
            {visibleCategories.length > 1 && (
              <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden sm:mx-0 sm:flex-wrap sm:px-0">
                {[
                  { slug: "", title: t("studio_ui.cat_all"), emoji: "🎞" },
                  ...(popularPresets.length ? [{ slug: "__popular", title: t("studio_ui.cat_popular"), emoji: "🔥" }] : []),
                  ...(picks.length ? [{ slug: "__pick", title: t("studio_ui.cat_pick"), emoji: "⭐" }] : []),
                  ...visibleCategories,
                ].map((c) => (
                  <button
                    key={c.slug || "all"}
                    type="button"
                    onClick={() => {
                      setVisibleIds(new Set());
                      setShown(PAGE_SIZE);
                      setActiveCat(c.slug);
                    }}
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
              {visiblePresets.map((p) => {
                const playing = playingIds.has(p.id) || previewing === p.id;
                return (
                <div
                  key={p.id}
                  className="flex flex-col overflow-hidden rounded-2xl border border-border bg-surface"
                >
                  {/* Ролик заводится, когда карточка попала на экран, и
                      останавливается, когда ушла: сотня одновременно играющих
                      видео не по силам ни трафику, ни памяти телефона.
                      Пока ролика нет, стоит лёгкая картинка — она же остаётся
                      единственным содержимым, если автозапуск выключен. */}
                  <div
                    ref={watchCard}
                    data-preset-id={p.id}
                    className="relative aspect-video cursor-pointer bg-surface-2"
                    onClick={() => setPreviewing((cur) => (cur === p.id ? null : p.id))}
                  >
                    {character && heroVideos[p.id] ? (
                      <>
                        {/* Эту пару уже снимали: показываем настоящий ролик
                            сцены с выбранным героем — сразу и бесплатно. Играет,
                            пока карточка на экране, как и обычные превью. */}
                        {playing ? (
                          <video
                            src={heroVideos[p.id]}
                            poster={tryOn[p.id] || p.preview_poster || undefined}
                            autoPlay
                            muted
                            loop
                            playsInline
                            preload="auto"
                            className="h-full w-full object-cover"
                          />
                        ) : (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img
                            src={tryOn[p.id] || p.preview_poster}
                            alt=""
                            loading="lazy"
                            decoding="async"
                            className="h-full w-full object-cover"
                          />
                        )}
                        <span className="pointer-events-none absolute left-2 top-2 rounded-full bg-black/55 px-2 py-0.5 text-[10px] font-medium text-white backdrop-blur-sm">
                          {t("studio_ui.with_hero")}
                        </span>
                      </>
                    ) : tryOn[p.id] ? (
                      <>
                        {/* Ролика пары ещё нет, но кадр с героем готов: он
                            медленно движется камерой, чтобы сцена не выглядела
                            застывшей, и честно подписан «кадр». */}
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={tryOn[p.id]}
                          alt=""
                          loading="lazy"
                          decoding="async"
                          className={`h-full w-full object-cover ${autoplay ? "studio-live" : ""}`}
                        />
                        <span className="pointer-events-none absolute left-2 top-2 rounded-full bg-black/55 px-2 py-0.5 text-[10px] font-medium text-white backdrop-blur-sm">
                          {t("studio_ui.hero_frame")}
                        </span>
                      </>
                    ) : playing && p.preview_video ? (
                      <video
                        src={p.preview_video}
                        poster={p.preview_poster || undefined}
                        autoPlay
                        muted
                        loop
                        playsInline
                        preload="auto"
                        className="h-full w-full object-cover"
                      />
                    ) : p.preview_poster ? (
                      <>
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={p.preview_poster}
                          alt=""
                          loading="lazy"
                          decoding="async"
                          className="h-full w-full object-cover"
                        />
                        {p.preview_video && !autoplay && (
                          <span className="pointer-events-none absolute inset-0 grid place-items-center">
                            <span className="grid size-10 place-items-center rounded-full bg-black/45 text-white backdrop-blur-sm">
                              <FiPlay className="ml-0.5" />
                            </span>
                          </span>
                        )}
                      </>
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
                    {/* Низ карточки — столбиком: на телефоне цена, примерка и
                        «В ленту» в одну строку не помещались, и главная кнопка
                        уезжала за край, оставляя один «+» (жалоба клиента). */}
                    <div className="mt-auto flex flex-col gap-1.5 pt-2">
                      <span className="inline-flex items-center gap-1 text-[11px] text-muted">
                        <FiZap className="text-accent" />
                        {t("studio_ui.price", { credits: p.credits, duration: p.duration })}
                      </span>
                      {character && !tryOn[p.id] && (
                        <button
                          type="button"
                          onClick={() => void tryOnScene(p)}
                          disabled={tryingOn !== null}
                          title={t("studio_ui.try_on_hint")}
                          className="inline-flex w-full items-center justify-center gap-1 rounded-lg border border-border px-2 py-1.5 text-[11px] text-muted transition-colors hover:border-accent hover:text-foreground disabled:opacity-60 cursor-pointer"
                        >
                          {tryingOn === p.id ? (
                            <FiLoader className="animate-spin" />
                          ) : (
                            <FiUser />
                          )}
                          {/* Цена — до нажатия (просьба клиента). Гостю первая
                              примерка бесплатна, и об этом кнопка говорит прямо. */}
                          {authed
                            ? t("studio_ui.try_on_price", { credits: p.tryon_credits ?? 4 })
                            : freeTryUsed
                            ? t("studio_ui.try_on")
                            : t("studio_ui.try_on_free")}
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => void addScene(p)}
                        disabled={adding !== null}
                        className="inline-flex w-full items-center justify-center gap-1.5 rounded-xl bg-accent px-3 py-2.5 text-sm font-bold text-on-accent transition-colors hover:bg-accent-strong disabled:opacity-60 cursor-pointer"
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
                );
              })}
            </div>

            {restCount > 0 && (
              <button
                type="button"
                onClick={() => setShown((n) => n + PAGE_SIZE)}
                className="mx-auto inline-flex items-center gap-2 rounded-full border border-border bg-surface px-5 py-2.5 text-sm font-medium text-muted transition-colors hover:border-accent hover:text-foreground cursor-pointer"
              >
                {t("studio_ui.show_more")}
                <span className="text-muted-2">{restCount}</span>
                <FiChevronDown />
              </button>
            )}
          </section>

          {(character || scenes.length > 0) && (
          <section ref={timelineRef} className="mt-8 flex flex-col gap-3 scroll-mt-24">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-bold text-foreground">{t("studio_ui.step3")}</h2>
              {authed && project && scenes.length > 0 && (
                <button
                  type="button"
                  onClick={startNewMovie}
                  className="ml-auto inline-flex items-center gap-1.5 rounded-full border border-border px-3 py-1.5 text-xs font-semibold text-muted transition-colors hover:border-accent hover:text-foreground cursor-pointer"
                >
                  <FiPlus />
                  {t("studio_ui.new_movie")}
                </button>
              )}
              {authed && scenes.length > 0 && (
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
              onMove={authed ? moveScene : guestMove}
              onRetry={authed ? retryScene : () => undefined}
              onDelete={authed ? deleteScene : guestDelete}
              onRender={authed ? renderScene : () => guestRender("scene")}
              characters={timelineCharacters.map((c) => ({
                id: c.id, name: c.name, image: c.image,
              }))}
              onPickCharacter={authed ? setSceneCharacter : guestPickCharacter}
              onFrame={frameScene}
              framingId={framingId}
              frameCredits={presets[0]?.tryon_credits ?? 4}
            />

            {/* Гость дособрал ленту: одна понятная кнопка вместо «Собрать» и
                прогресса съёмки, которых у него ещё нет. */}
            {!authed && scenes.length > 0 && (
              <div className="flex flex-col gap-3 rounded-2xl border border-accent/40 bg-accent/5 p-4 sm:flex-row sm:items-center">
                <div className="flex-1">
                  <p className="text-sm font-semibold text-foreground">
                    {t("studio_ui.guest_cta_title", { count: scenes.length })}
                  </p>
                  <p className="mt-0.5 text-xs text-muted">{t("studio_ui.guest_cta_note")}</p>
                </div>
                <button
                  type="button"
                  onClick={() => guestRender("cta")}
                  className="inline-flex items-center justify-center gap-2 rounded-full bg-accent px-5 py-2.5 text-sm font-bold text-on-accent transition-colors hover:bg-accent-strong cursor-pointer"
                >
                  <FiFilm />
                  {t("studio_ui.guest_cta_btn")}
                </button>
              </div>
            )}
            {!authed && scenes.length === 0 && (
              <span className="text-xs text-muted-2">{t("studio_ui.empty_hint")}</span>
            )}

            {authed && (
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
              {drafts > 0 && (
                <span className="text-xs text-muted-2">
                  {t("studio_ui.drafts_hint", { count: drafts })}
                </span>
              )}
              {!readyCount && !working && scenes.length === 0 && (
                <span className="text-xs text-muted-2">{t("studio_ui.empty_hint")}</span>
              )}
            </div>
            )}
          </section>
          )}

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
              <button
                type="button"
                onClick={startNewMovie}
                className="inline-flex w-fit items-center gap-2 rounded-full bg-accent px-4 py-2 text-sm font-semibold text-on-accent transition-colors hover:bg-accent-strong cursor-pointer"
              >
                <FiPlus />
                {t("studio_ui.new_movie")}
              </button>

              {/* Поделиться. Ссылка ведёт на страницу мультфильма, а не на
                  файл: там ролик играет прямо в мессенджере и стоит призыв
                  создать свой — так каждый отправленный мультфильм работает
                  рекламой студии. */}
              <div className="mt-2 rounded-2xl border border-border bg-surface-2/50 p-4">
                <p className="text-sm font-semibold text-foreground">{t("studio_ui.share_title")}</p>
                <p className="mt-0.5 mb-3 text-xs text-muted-2">{t("studio_ui.share_note")}</p>
                {shareUrl ? (
                  <ShareButtons
                    url={shareUrl}
                    text={t("studio_ui.share_text")}
                  />
                ) : (
                  <span className="inline-flex items-center gap-2 text-sm text-muted">
                    <FiLoader className="animate-spin" />
                    {t("studio_ui.share_preparing")}
                  </span>
                )}
              </div>
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

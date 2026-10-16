/**
 * Общие типы и константы мультстудии: их делят состояние (useCartoonStudio)
 * и компоненты страницы, поэтому они живут отдельно от обоих.
 */
import type { StudioCharacter } from "./CharacterPicker";
import type { SceneDurationChoice, StudioScene } from "./SceneTimeline";
import type { AdjustedNote, DockEffective } from "./dockLogic";

export type Preset = {
  id: number;
  slug: string;
  title: string;
  subtitle: string;
  preview_video: string;
  preview_poster: string;
  duration: number;
  aspect_ratio: string;
  /** Цена сцены под формат мультфильма. null — цены сейчас нет (в режиме цен
   *  «наценка» неизвестна себестоимость модели), сервер ставит и price_unavailable. */
  credits: number | null;
  price_unavailable?: boolean;
  /** Цена примерки героя — показываем на кнопке до запуска. */
  tryon_credits?: number;
  category: string;
  audience: "kids" | "adults";
  is_pick: boolean;
};

export type Category = { slug: string; title: string; emoji: string };

export type Project = {
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
  /** Док мультфильма: свои модель, качество, длительность; null — как в сцене библиотеки. */
  video_model?: string | null;
  resolution?: string | null;
  duration?: number | null;
  /** Что показывает док: свои значения, пустые — по «типичной сцене». */
  effective?: DockEffective | null;
  /** Что сервер подогнал к модели сам (только в ответе на правку). */
  adjusted?: AdjustedNote[];
  /** Идёт озвучка всего мультфильма: сколько реплик готово из скольких. */
  voicing?: {
    done: number;
    total: number;
    error?: string;
    spent?: number;
    finished?: boolean;
  } | null;
};

export type AuthReason = "character" | "scene" | "tryon" | "render";

export type Audience = "all" | "kids" | "adults";

/** Не хватило кредитов: цена, баланс и на что (окно покупки пишет своё пояснение). */
export type Shortfall = { required: number; balance: number; kind?: "scene" | "character" | "audio" };

/** Ответ сервера с отказом: текст и, если не хватило кредитов, цена и баланс.
 *  need_auth — гостю нужен вход (примерка). */
export type ApiRefusal = { detail?: string; required?: number; balance?: number; need_auth?: boolean } | null | undefined;

export const WORKING: StudioScene["status"][] = ["new", "keyframe", "video"];

/** Сколько сцен показываем за раз. Шесть — просьба клиента, ради медленного интернета. */
export const PAGE_SIZE = 6;

// Ссылка на видеостудию — по тому же правилу, что пункт меню сайта
// (components/main/Nav.tsx): только в сборке, где студия открыта всем.
export const VSTUDIO_NAV = process.env.NEXT_PUBLIC_VSTUDIO_NAV === "1";

/** Цена и длительность карточки библиотеки при нынешних настройках дока. */
export type CardPrice = { credits: number | null; duration: number };

/** Кого можно поставить на сцену ленты. */
export type TimelineCharacter = { id: number; name: string; image: string };

export type DockValue = {
  /** OpenRouter id модели; null — неизвестна (пусто в библиотеке). */
  model: string | null;
  /** Подпись, если модели нет в списке дока (выключили): «Seedance 2.0». */
  modelName: string;
  resolution: string | null;
  duration: number | null;
  aspect: string;
};

/** Главная кнопка дока (BUILD_D решение 5): только существующие действия. */
export type DockPrimary =
  | { kind: "guest"; count: number; onClick: () => void }
  | { kind: "assemble"; ready: number; total: number; busy: boolean; fresh: boolean; onClick: () => void }
  | { kind: "assemble_off"; total: number };

/** Пропсы SceneTimeline с уже выбранной веткой «вошёл / гость». */
export type SceneHandlers = {
  onMove: (scene: StudioScene, dir: -1 | 1) => void;
  onRetry: (scene: StudioScene) => void;
  onDelete: (scene: StudioScene) => void;
  onRender: (scene: StudioScene) => void;
  onPickCharacter: (scene: StudioScene, characterId: number) => void;
  onFrame: (scene: StudioScene) => void;
  onTryOn: (scene: StudioScene) => void;
  onRedraw?: (scene: StudioScene) => void;
  onDialogue: (scene: StudioScene, text: string) => void;
  onAudio?: (scene: StudioScene) => void;
  durationFor: (scene: StudioScene) => SceneDurationChoice | null;
  onDuration: (scene: StudioScene, value: number | null) => void;
  onDismissNote: (scene: StudioScene) => void;
};

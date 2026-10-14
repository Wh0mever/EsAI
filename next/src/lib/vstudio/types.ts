/**
 * Видеостудия (/video-studio): общий контракт фронта.
 *
 * Формы данных — ровно §8.3 спецификации (их отдаёт core/vstudio, трек BE-9),
 * стор — §9.4, редактор — §9.5. Остальные треки фронта (FE-1…FE-5) импортируют
 * типы только отсюда: если форма ответа меняется, правка одна и tsc сам покажет
 * всех, кого она задела.
 *
 * Файл намеренно без импорта значений: его грузят и Next, и node-тесты
 * (node --experimental-strip-types), а type-импорты стираются целиком.
 */
import type { Ref } from "react";
import type { PaywallContext } from "@/components/chat/PaywallModal";

/* ------------------------------------------------------------------ */
/* Базовые перечисления                                                */
/* ------------------------------------------------------------------ */

/** Публичный идентификатор: uuid4().hex, 32 символа [0-9a-f]. Числовых id API не принимает. */
export type Uid = string;

export type VsKind = "video" | "image";
/** Флаг VSTUDIO_MODE: off — студия закрыта, staff — только is_staff, on — все. */
export type VsMode = "off" | "staff" | "on";

export type InputSlot = "reference" | "first_frame" | "last_frame";
export type FrameSlot = "first_frame" | "last_frame";
export const FRAME_SLOTS: readonly FrameSlot[] = ["first_frame", "last_frame"];

export type TakeStatus =
  | "queued"
  | "submitting"
  | "running"
  | "saving"
  | "done"
  | "failed"
  | "canceled"
  | "lost";
/** Открытые статусы: деньги в резерве, дубль ещё опрашиваем (Take.OPEN на бэкенде). */
export const OPEN_TAKE_STATUSES: readonly TakeStatus[] = ["queued", "submitting", "running", "saving"];
export type ChargeState = "reserved" | "charged" | "released";
export type TakeMode = "t2v" | "i2v" | "flf2v" | "r2v" | "r2v_pin" | "t2i" | "i2i";

export type AssetKind = "image" | "video" | "audio";
export type AssetSource =
  | "upload"
  | "generated_image"
  | "generated_video"
  | "frame"
  | "import_cartoon"
  | "import_chat";
export type AssetStatus = "pending" | "ready" | "failed";

export type ShotOrigin = "composer" | "tray";
export type ProjectKind = "playground" | "production";
export type FramesWithRefs = "soft_pin" | "block" | "none";
export type PromptLang = "en" | "any";
export type MeterLevel = "ok" | "soft" | "hard";

/* ------------------------------------------------------------------ */
/* prompt_doc v1 (§4.1)                                                */
/* ------------------------------------------------------------------ */

export type PromptTextNode = { t: "text"; v: string };
/** Ссылка на материал. Метка «@Image N» в документ НЕ пишется — её считает labels.ts. */
export type PromptRefNode = { t: "ref"; asset: Uid };
export type PromptNode = PromptTextNode | PromptRefNode;
/** Абзац; при сериализации абзацы соединяются «\n». */
export type PromptBlock = PromptNode[];
export type PromptDoc = { v: 1; blocks: PromptBlock[] };

/** Пределы prompt_doc.validate на сервере; превышение → 422 prompt_doc_invalid. */
export const PROMPT_DOC_LIMITS = {
  maxBlocks: 200,
  maxNodesPerBlock: 400,
  maxTextChars: 20000,
  maxRefs: 64,
} as const;
/** Лимит редактора (§9.5): больше сервер не примет ни при какой модели. */
export const PROMPT_MAX_CHARS = 20000;
/** Лимит материалов в одном запросе (too_many_inputs). */
export const MAX_INPUTS = 16;

export const EMPTY_PROMPT_DOC: PromptDoc = { v: 1, blocks: [[]] };

/* ------------------------------------------------------------------ */
/* Модели (GET models/)                                                */
/* ------------------------------------------------------------------ */

export type ModelCapsJSON = {
  /** Пустые у картинок. */
  durations: number[];
  resolutions: string[];
  aspect_ratios: string[];
  audio: boolean;
  seed: boolean;
  /** Негатив можно передать (только через passthrough провайдера). */
  negative: boolean;
  frames: FrameSlot[];
  /** Сколько фото-референсов включено у нас (0 — референсы выключены до пробы). */
  refs: { image: number };
  frames_with_refs: FramesWithRefs;
  /** Veo + референсы → только 8 с; null — не форсирует. */
  ref_forces_duration: number | null;
  prompt: { soft_words: number | null; hard_chars: number; lang: PromptLang };
  rejects_real_faces: boolean;
  /** Минимальная короткая сторона референса в px (0 — без проверки). */
  min_ref_px: number;
  /** Допустимое соотношение сторон референса [от, до] (Seedance 0.4…2.5); null — без проверки. */
  ref_aspect_range?: [number, number] | null;
  /** Как модель понимает упоминания фото: indexed ([Image N]), natural, none. */
  mention_style?: string;
  /** Дата живой пробы референсов (ISO) или null — не проверено. */
  verified?: string | null;
};

export type ModelDefaults = {
  duration?: number;
  resolution?: string;
  aspect_ratio?: string;
};

/** {разрешение: {секунды: кредиты}} при images=0 — только подсказки «от N кр». */
export type PriceTable = Record<string, Record<string, number>>;

export type ModelPriceJSON = {
  table: PriceTable;
  /** {пропорция: PriceTable}, если цена зависит от пропорций (Seedance 21:9). */
  by_aspect?: Record<string, PriceTable>;
};

export type ModelJSON = {
  /** OpenRouter id, он же `model` в QuoteBody: "bytedance/seedance-2.0". */
  id: string;
  name: string;
  badge: string;
  /** Бесплатный тариф: модель видна, но запуск ведёт в пэйволл premium_locked. */
  locked: boolean;
  eta_s: number;
  /** null — цену не посчитать (каталог провайдера не ответил). */
  price_from: number | null;
  caps: ModelCapsJSON;
  defaults: ModelDefaults;
  /** Только у видео. */
  price?: ModelPriceJSON;
  /** Только у картинок: плоская цена за картинку. */
  per_image?: number;
};

export type ModelsResponse = {
  mode: VsMode;
  /** Может ли текущий человек запускать генерации (mode=on или staff при mode=staff). */
  available: boolean;
  video: ModelJSON[];
  image: ModelJSON[];
};

/* ------------------------------------------------------------------ */
/* Ассеты, проекты, кадры, дубли (§8.3)                                */
/* ------------------------------------------------------------------ */

export type AssetFlags = {
  too_small?: boolean;
  aspect?: boolean | number;
  heic?: boolean;
  exif_rotated?: boolean;
  downscaled_from?: [number, number];
  animated?: boolean;
};

export type AssetJSON = {
  uid: Uid;
  kind: AssetKind;
  source: AssetSource;
  status: AssetStatus;
  /** null, пока картинка создаётся (pending). */
  url: string | null;
  thumb_url: string | null;
  width: number | null;
  height: number | null;
  duration_s: number | null;
  /** Алиас «@Анна» (UI — Фаза 1.5); пустая строка — нет алиаса. */
  label: string;
  flags: AssetFlags;
  /** Пустая строка или null — ошибки нет. */
  error_code: string | null;
  created_at: string;
  /** Материал удалён (мягко): чип старого кадра — красный. */
  deleted?: boolean;
};

export type ShotParams = {
  duration?: number;
  resolution?: string;
  /** Конкретная пропорция или "auto" (не отправляется провайдеру). */
  aspect_ratio?: string;
  generate_audio?: boolean;
  seed?: number | null;
  negative_prompt?: string;
};

/** Project.settings — последние параметры правой панели (PATCH projects/<uid>/). */
export type ProjectSettings = {
  kind?: VsKind;
  model?: string;
  params?: ShotParams;
  [key: string]: unknown;
};

export type ProjectJSON = {
  uid: Uid;
  title: string;
  kind: ProjectKind;
  settings: ProjectSettings;
  is_archived: boolean;
  last_activity_at: string;
  thumb_url: string | null;
  open_takes: number;
};

export type EffectiveParams = {
  duration?: number;
  resolution?: string;
  aspect_ratio?: string;
  generate_audio?: boolean;
};

export type DroppedInput = {
  asset: Uid;
  slot: InputSlot;
  reason: "excluded_by_user" | (string & {});
};

/** Исправление одной кнопкой (§4.7). */
export type IssueFix =
  | { action: "condense" }
  | { action: "exclude_inputs"; assets: Uid[] }
  | { action: "move_to_first_frame"; asset: Uid }
  /** assets — что выключить (included=false, не удалять): референсы или кадры. */
  | { action: "use_frames_only"; assets?: Uid[] }
  | { action: "use_refs_only"; assets?: Uid[] }
  | { action: "set_param"; field: keyof ShotParams; value: string | number | boolean | null }
  | { action: "pick_model"; model: string }
  | { action: "topup" };
export type IssueFixAction = IssueFix["action"];

/** Блокирующие коды компилятора (422 blocked / QuoteJSON.errors). */
export type BlockingCode =
  | "prompt_empty"
  | "prompt_too_long"
  | "prompt_doc_invalid"
  | "mention_not_attached"
  | "asset_not_found"
  | "asset_not_ready"
  | "asset_failed"
  | "refs_not_supported"
  | "too_many_refs"
  | "frames_not_supported"
  | "last_frame_not_supported"
  | "last_frame_with_refs"
  | "frames_refs_conflict"
  | "ref_too_small"
  | "ref_bad_aspect"
  | "video_refs_unsupported"
  | "invalid_param"
  | "model_unavailable"
  | "too_many_inputs"
  | "service_misconfigured";

/** Предупреждения компилятора: запуск разрешён. */
export type WarningCode =
  | "prompt_long"
  | "looks_like_script"
  | "ref_unmentioned"
  | "tag_unknown"
  | "frame_soft_pin"
  | "duration_forced"
  | "faces_risk"
  | "aspect_in_text"
  | "lang_hint"
  | "input_excluded";

/** Одна запись errors[] / warnings[]: {code, params, message, fix?}. */
export type CompilerIssue = {
  code: BlockingCode | WarningCode | (string & {});
  /** Подстановки для перевода: model, chars, hard, n, max, min, field, value, allowed, words, soft, k, text, current… */
  params: Record<string, unknown>;
  /** Готовый русский текст с бэкенда — defaultValue для t(). */
  message: string;
  fix?: IssueFix | null;
  /** Если исправлений несколько (frames_refs_conflict: «Оставить кадры» / «Оставить референсы»). */
  fixes?: IssueFix[];
};

export type ShotInputJSON = {
  asset: AssetJSON;
  slot: InputSlot;
  position: number;
  role: string;
  included: boolean;
  /** "Image 1" | "first_frame" | "last_frame"; null — не учитывается. */
  label: string | null;
};

export type TakeCredits = { quoted: number; reserved: number; charged: number };

export type TakeError = {
  code: string;
  message: string;
  /** uid виноватого входа (модерация) — подсветить в InputsStrip. */
  input: Uid | null;
};

export type TakeLite = {
  uid: Uid;
  shot: Uid;
  kind: VsKind;
  status: TakeStatus;
  /** Сырой статус провайдера во время running ("processing", "in_queue"…). */
  stage: string;
  mode: TakeMode;
  charge_state: ChargeState;
  credits: TakeCredits;
  effective: EffectiveParams;
  warnings: CompilerIssue[];
  dropped: DroppedInput[];
  result: AssetJSON | null;
  error: TakeError | null;
  eta_s: number;
  elapsed_s: number;
  /** Позиция в очереди для queued (0 — следующий); null — не в очереди. */
  queue_position: number | null;
  created_at: string;
  submitted_at: string | null;
  finished_at: string | null;
};

/** GET takes/<uid>/ — «Что ушло модели». */
export type TakeJSON = TakeLite & {
  serialized_prompt: string;
  /** Тело submit без ключей, URL абсолютные. */
  request_body: Record<string, unknown>;
};

/** GET takes/active/ — открытые дубли по всем проектам. */
export type ActiveTake = TakeLite & { project_uid: Uid };

export type ShotJSON = {
  uid: Uid;
  project: Uid;
  kind: VsKind;
  origin: ShotOrigin;
  /** null — модель удалили из каталога после запуска. */
  model: { id: string; name: string } | null;
  prompt_doc: PromptDoc;
  /** Рендер документа с метками «@Image N», без обрезки. */
  prompt_text: string;
  params: ShotParams;
  inputs: ShotInputJSON[];
  forked_from: Uid | null;
  created_at: string;
  /** По возрастанию created_at. */
  takes: TakeLite[];
};

/** Страница списка: next — курсор для следующего запроса (null — дальше пусто). */
export type Paged<T> = { items: T[]; next: string | null };

/* ------------------------------------------------------------------ */
/* Цена: quote/ и shots/ (§5, §8.3)                                    */
/* ------------------------------------------------------------------ */

export type ShotInputBody = {
  asset: Uid;
  slot: InputSlot;
  /** Порядок в лотке внутри слота, с нуля. */
  position: number;
  role?: string;
  included: boolean;
};

/** Ровно одно из двух: документ редактора или текст запасной textarea. */
export type PromptPayload =
  | { prompt_doc: PromptDoc; prompt_text?: undefined }
  | { prompt_text: string; prompt_doc?: undefined };

export type QuoteBody = {
  project: Uid | null;
  kind: VsKind;
  model: string;
  inputs: ShotInputBody[];
  params: ShotParams;
} & PromptPayload;

/** quote/ принимает и готовый кадр — для «Повторить». */
export type QuoteRequest = QuoteBody | { shot: Uid };

export type PriceLineKey = "price.video" | "price.refs" | "price.image";
export type PriceLine = {
  /** i18n-ключ в ns vstudio. */
  key: PriceLineKey | (string & {});
  /** video: {s, res, ar}; refs: {n}; image: {n}. */
  params: Record<string, string | number>;
  credits: number;
};

export type BalanceJSON = {
  balance: number;
  /** Все резервы: видео чата и бота, сцены мультстудии, дубли студии. */
  reserved: number;
  available: number;
  /** Сколько останется после этого запуска (есть только в quote). */
  after?: number | null;
};

export type PromptMeterJSON = {
  chars: number;
  words: number;
  soft_words: number | null;
  hard_chars: number;
  level: MeterLevel;
};

export type QuoteJSON = {
  /** null — цену не посчитать (например, invalid_param). */
  credits: number | null;
  breakdown: PriceLine[];
  /** null для гостя. */
  balance: BalanceJSON | null;
  mode: TakeMode | null;
  effective: EffectiveParams;
  /** {asset uid: "Image 1" | "first_frame" | "last_frame"} — только то, что уйдёт модели. */
  labels: Record<Uid, string>;
  serialized_prompt: string;
  errors: CompilerIssue[];
  warnings: CompilerIssue[];
  meter: PromptMeterJSON;
  dropped: DroppedInput[];
  eta_s: number;
};

export type RunShotBody = QuoteBody & {
  quoted_credits: number;
  /** Живёт от клика до ответа: повторный клик уходит с тем же id (≤64 символа). */
  client_request_id: string;
  origin?: ShotOrigin;
  /** «Изменить» / «Другая модель»: кадр, от которого ответвились (только связь для истории). */
  forked_from?: Uid | null;
};

/** 202 (200 при повторе client_request_id). */
export type RunShotResponse = {
  project: ProjectJSON;
  shot: ShotJSON;
  take: TakeLite;
  /** Только у картинок: ассет в pending — сразу чип в лотке. */
  asset?: AssetJSON | null;
  balance: BalanceJSON | null;
};

export type RetryBody = { quoted_credits: number; client_request_id: string };
export type RetryResponse = { take: TakeLite; balance: BalanceJSON | null };

export type CondenseBody = {
  model: string;
  prompt_doc: PromptDoc;
  inputs: ShotInputBody[];
};
export type TextStats = { chars: number; words: number };
export type CondenseResponse = { prompt_doc: PromptDoc; before: TextStats; after: TextStats };

export type ProjectPatch = {
  title?: string;
  settings?: ProjectSettings;
  is_archived?: boolean;
};

export type ListProjectsQuery = {
  q?: string;
  archived?: boolean;
  /** ISO-время last_activity_at — курсор из Paged.next. */
  before?: string | null;
  limit?: number;
};
export type ListShotsQuery = { before?: Uid | null; limit?: number };
export type ListAssetsQuery = {
  kind?: AssetKind;
  source?: AssetSource | "";
  before?: string | null;
  limit?: number;
};

export type FromTakeBody = { take: Uid; at: "last_frame" };

/** POST assets/: 201 новый, 200 — тот же файл уже был (дедупликация по sha256). */
export type UploadResult = { asset: AssetJSON; duplicate: boolean };
export type UploadPhase = "upload" | "processing";

/* ------------------------------------------------------------------ */
/* Ошибки API (§8.1, §8.4)                                             */
/* ------------------------------------------------------------------ */

export type HttpErrorCode =
  | "bad_request"
  | "unauthorized"
  | "insufficient_balance"
  | "premium_locked"
  | "vstudio_disabled"
  | "project_not_found"
  | "take_not_found"
  | "asset_not_found"
  | "shot_not_found"
  | "price_changed"
  | "too_many_open"
  | "already_submitted"
  | "file_too_large"
  | "unsupported_type"
  | "bad_image"
  | "too_many_pixels"
  | "video_refs_unsupported"
  | "blocked"
  | "prompt_doc_invalid"
  | "condense_failed"
  | "throttled"
  | "provider_unavailable"
  | "service_misconfigured"
  // «Последний кадр → первый» (assets/from-take/) и общие отказы DRF.
  | "take_not_ready"
  | "frame_failed"
  | "forbidden"
  | "method_not_allowed";

/** Коды, которые придумывает сам фронт (ответа сервера нет или он без error_code). */
export type ClientErrorCode = "network" | "aborted" | "server_error" | "not_found" | "bad_response" | "unknown";

export type VsErrorCode = HttpErrorCode | ClientErrorCode | (string & {});

export type VsError = {
  /** HTTP-статус; 0 — сети нет или запрос отменён. */
  status: number;
  code: VsErrorCode;
  /** Русский текст бэкенда (error/detail); пустая строка — текста нет. */
  message: string;
  /** Всё тело ответа: доп. поля (balance_tokens, limit, credits, errors…). */
  data: Record<string, unknown>;
};

export type VsResult<T> =
  | { ok: true; status: number; data: T }
  | { ok: false; status: number; error: VsError };

/* ------------------------------------------------------------------ */
/* Стор (§9.4) — редьюсер пишет FE-1 в components/vstudio/store.ts      */
/* ------------------------------------------------------------------ */

export type TrayStatus = "uploading" | "processing" | "ready" | "failed" | "pending" | "deleted";

export type TrayItem = {
  /** Локальный id чипа: ключ React и адрес для tray/*-действий. */
  lid: string;
  /** Появляется после загрузки (или сразу — для материала из библиотеки). */
  assetUid?: Uid;
  slot: InputSlot;
  /** «Кто или что это?» — уходит в ShotInput.role. */
  role: string;
  /** false — серый чип «не учитывается и не оплачивается». */
  included: boolean;
  status: TrayStatus;
  /** 0…100 — прогресс загрузки. */
  progress: number;
  /** blob: во время загрузки, потом thumb_url. */
  preview: string | null;
  /** Запись сервера, когда она известна (размеры, flags, source). */
  asset?: AssetJSON;
  /** failed: error_code загрузки или ассета. */
  errorCode?: string;
};

export type ComposerFrames = { first_frame: TrayItem | null; last_frame: TrayItem | null };

export type ComposerState = {
  kind: VsKind;
  /** ModelJSON.id; null — модели ещё не загружены. */
  model: string | null;
  params: ShotParams;
  doc: PromptDoc;
  /** Фото-референсы (@Image N) в порядке лотка. */
  tray: TrayItem[];
  /** Слоты кадров — отдельно от референсов (§0 п. 9). */
  frames: ComposerFrames;
  /** «Изменить и перезапустить»: кадр, от которого ответвились. */
  forkedFrom: Uid | null;
};

export type QuoteState = {
  status: "idle" | "loading" | "ready" | "error";
  /** Слепок тела запроса: цена годится для запуска, только если key совпал. */
  key: string | null;
  data: QuoteJSON | null;
  error: VsError | null;
};

export type RunState = {
  status: "idle" | "sending";
  /** Создаётся на первый клик и живёт до ответа — двойной клик не платит дважды. */
  clientRequestId: string | null;
  error: VsError | null;
};

export type LibraryFilter = "all" | "uploads" | "generated" | "frames";

export type LibraryState = {
  items: AssetJSON[];
  next: string | null;
  loading: boolean;
  loaded: boolean;
  filter: LibraryFilter;
};

export type ProjectsState = {
  items: ProjectJSON[];
  next: string | null;
  loading: boolean;
  loaded: boolean;
  q: string;
};

export type FeedState = { next: string | null; loading: boolean; loaded: boolean };

export type PageStatus = "loading" | "ready" | "not_found" | "offline" | "disabled" | "error";
export type PanelName = "rail" | "settings" | "library" | "picker";

/**
 * Поле запроса в панели: rest — свёрнуто само, пока человек не работает в
 * панели; open — развёрнуто; shut — свернул сам кнопкой (подсказки и
 * брошенный файл его уже не развернут, только фокус в поле или та же кнопка).
 */
export type PromptFold = "rest" | "open" | "shut";

export type Toast = {
  id: string;
  tone: "info" | "ok" | "error";
  /** Уже переведённый текст. */
  text: string;
  /** Клик по тосту прокручивает к карточке дубля. */
  take?: Uid;
};

export type UiState = {
  page: PageStatus;
  panels: Record<PanelName, boolean>;
  paywall: PaywallContext | null;
  /** Окно «Войдите, чтобы создать видео». */
  auth: boolean;
  topup: boolean;
  toasts: Toast[];
  /** ?take=<uid> или клик по тосту: прокрутить и подсветить карточку. */
  focusTake: Uid | null;
  /** Полноэкранный редактор (⤢). */
  fullscreen: boolean;
  /** Свёрнуто ли поле запроса. Только в памяти вкладки: после перезагрузки — снова rest. */
  promptFold: PromptFold;
};

export type VsState = {
  /** null, пока не пришёл models/. */
  mode: VsMode | null;
  available: boolean;
  models: { video: ModelJSON[]; image: ModelJSON[] } | null;
  projects: ProjectsState;
  project: ProjectJSON | null;
  shots: Map<Uid, ShotJSON>;
  takes: Map<Uid, TakeLite>;
  /** uid кадров ленты по возрастанию created_at (старые сверху). */
  order: Uid[];
  feed: FeedState;
  composer: ComposerState;
  quote: QuoteState;
  run: RunState;
  library: LibraryState;
  ui: UiState;
};

export type VsAction =
  // модели и страница
  | { type: "models/loaded"; payload: ModelsResponse }
  | { type: "page/status"; status: PageStatus }
  // история проектов (левая колонка)
  | { type: "projects/loading" }
  | { type: "projects/loaded"; page: Paged<ProjectJSON>; append: boolean }
  | { type: "projects/query"; q: string }
  | { type: "projects/upsert"; project: ProjectJSON }
  | { type: "projects/remove"; uid: Uid }
  | { type: "project/set"; project: ProjectJSON | null }
  // лента
  | { type: "feed/loading" }
  /** Страница старше текущих: ставится в начало order. */
  | { type: "feed/loaded"; page: Paged<ShotJSON>; older: boolean }
  | { type: "shot/upsert"; shot: ShotJSON }
  | { type: "takes/upsert"; takes: TakeLite[] }
  | { type: "take/added"; shot: Uid; take: TakeLite }
  // композер
  | { type: "composer/kind"; kind: VsKind }
  | { type: "composer/model"; model: string }
  | { type: "composer/params"; params: Partial<ShotParams> }
  | { type: "composer/doc"; doc: PromptDoc }
  /** «Изменить» / «Другая модель»: композер заполняется кадром (новый Shot с forked_from). */
  | { type: "composer/fill"; shot: ShotJSON; model?: string }
  | { type: "composer/restore"; draft: Pick<ComposerState, "kind" | "model" | "params" | "doc"> }
  | { type: "composer/reset"; keepText?: boolean }
  // лоток и кадры
  | { type: "tray/add"; item: TrayItem; at?: number }
  | { type: "tray/update"; lid: string; patch: Partial<TrayItem> }
  | { type: "tray/remove"; lid: string }
  /** Перестановка референса: номера @Image N пересчитываются сразу. */
  | { type: "tray/move"; lid: string; to: number }
  /** «Сделать первым кадром» / «Сделать референсом». */
  | { type: "tray/slot"; lid: string; slot: InputSlot }
  /** exclude_inputs, use_frames_only, use_refs_only, «Учитывать снова». */
  | { type: "tray/include"; lids: string[]; included: boolean }
  | { type: "tray/role"; lid: string; role: string }
  // цена
  | { type: "quote/loading"; key: string }
  | { type: "quote/loaded"; key: string; quote: QuoteJSON }
  | { type: "quote/failed"; key: string; error: VsError }
  // запуск
  | { type: "run/start"; clientRequestId: string }
  | { type: "run/done"; response: RunShotResponse }
  | { type: "run/failed"; error: VsError }
  // библиотека
  | { type: "library/loading" }
  | { type: "library/loaded"; page: Paged<AssetJSON>; append: boolean }
  | { type: "library/filter"; filter: LibraryFilter }
  | { type: "library/upsert"; asset: AssetJSON }
  | { type: "library/remove"; uid: Uid }
  // интерфейс
  | { type: "ui/panel"; panel: PanelName; open?: boolean }
  | { type: "ui/paywall"; paywall: PaywallContext | null }
  | { type: "ui/auth"; open: boolean }
  | { type: "ui/topup"; open: boolean }
  | { type: "ui/toast"; toast: Toast }
  | { type: "ui/toastDismiss"; id: string }
  | { type: "ui/focusTake"; take: Uid | null }
  | { type: "ui/fullscreen"; open: boolean }
  | { type: "ui/promptFold"; fold: PromptFold };

export type VsActionType = VsAction["type"];

/* ------------------------------------------------------------------ */
/* Редактор (§9.5) — реализует FE-2                                    */
/* ------------------------------------------------------------------ */

/** Состояние чипа: ok — «@Image N», pending — создаётся, excluded — серый «—», deleted — красный. */
export type RefChipState = "ok" | "pending" | "failed" | "excluded" | "deleted" | "missing";

export type RefLabel = {
  /** Текст чипа: «@Image 1», «@Первый кадр», «@Анна», «—». Не переводится для @Image N. */
  text: string;
  /** Номер среди включённых референсов; null у кадров и выключенных. */
  n: number | null;
  /** null — материала нет в лотке (mention_not_attached). */
  slot: InputSlot | null;
  state: RefChipState;
  /** Переведённая подсказка и aria-label: «Фото 1 · героиня». */
  aria: string;
};
export type RefLabels = Record<Uid, RefLabel>;

export type PickerSection = "in_request" | "library" | "upload" | "generate";

export type PickerItem = {
  asset: Uid;
  section: "in_request" | "library";
  /** «@Image 1» у материалов запроса, пусто у библиотеки. */
  label: string;
  thumb: string | null;
  role?: string;
  status?: AssetStatus;
};

export type MentionVia = "at" | "button" | "paste";

/** Императивные ручки: кнопка «@ Материалы», вставка чипа после «Создать картинку». */
export type PromptEditorHandle = {
  focus: () => void;
  insertRef: (asset: Uid) => void;
  openPicker: () => void;
};

export type PromptEditorProps = {
  doc: PromptDoc;
  onChange: (doc: PromptDoc) => void;
  labels: RefLabels;
  pickerItems: PickerItem[];
  /** Материал из «Моих материалов»: родитель кладёт его в лоток, редактор вставляет чип. */
  onPickLibrary?: (asset: Uid) => void;
  /** Вставка или перетаскивание файлов: промис отдаёт uid загруженных — редактор ставит чипы в позицию каретки. */
  onUpload: (files: File[], via: "paste" | "drop" | "picker") => Promise<Uid[]>;
  /** «Создать картинку» из выбора материалов. */
  onGenerate: () => void;
  /** По умолчанию PROMPT_MAX_CHARS. */
  maxChars?: number;
  placeholder?: string;
  /** Ctrl/⌘+Enter. */
  onSubmit: () => void;
  fullscreen?: boolean;
  onFullscreenChange?: (open: boolean) => void;
  disabled?: boolean;
  autoFocus?: boolean;
  /** Для воронки vstudio_mention. */
  onMention?: (via: MentionVia) => void;
  handleRef?: Ref<PromptEditorHandle>;
};

/* ------------------------------------------------------------------ */
/* Воронка (§11)                                                       */
/* ------------------------------------------------------------------ */

/** meta для каждого шага vstudio_* (undefined — шаг без подробностей). */
export type VsFunnelMeta = {
  /** Шлётся, когда студией уже можно пользоваться. home — человек на первом экране, а не в проекте. */
  vstudio_view: { authed: boolean; home: boolean };
  /** Нажатие на первом экране: what — секция, id — кадр карусели или «Трендов», сценарий, модель, инструмент или проект. */
  vstudio_home_pick: {
    what: "reel" | "template" | "model" | "tool" | "continue" | "trend";
    id: string;
  };
  vstudio_upload: { ok: boolean; code?: string };
  vstudio_mention: { via: MentionVia };
  vstudio_imagegen: undefined;
  vstudio_blocked: { code: string };
  vstudio_run_click: {
    model: string;
    kind: VsKind;
    credits: number | null;
    refs: number;
    frames: number;
    words: number;
  };
  vstudio_paywall: undefined;
  vstudio_auth_prompt: undefined;
  vstudio_condense: { accepted: boolean; model?: string };
  vstudio_share: undefined;
};
export type VsFunnelStep = keyof VsFunnelMeta;

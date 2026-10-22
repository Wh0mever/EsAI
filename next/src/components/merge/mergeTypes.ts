/**
 * «Склейка видео»: формы ответов /api/merge/ (vstudio2-notes/pricing/CONTRACT_M.md §7).
 *
 * Идентификатор склейки — uid из 32 hex, идентификаторы источников — строки.
 * В запросах фрагменты — только {type, id}: всё остальное сервер собирает сам.
 */

/** upload — своё видео, загруженное в «Мои файлы» (CONTRACT_M.md §9). */
export type MergeSourceType = "vstudio" | "cartoon_scene" | "cartoon_movie" | "chat" | "upload";
/** Вкладки выбора: «Мультстудия» отдаёт мультфильмы и сцены вместе, «Мои файлы» — свои видео. */
export type MergeTab = "vstudio" | "cartoon" | "chat" | "upload";
export type MergeStatus = "draft" | "queued" | "rendering" | "ready" | "failed" | "expired";
export type MergeAspect = "16:9" | "9:16" | "1:1";
export type MergeFit = "pad" | "crop";

export interface MergeSourceCard {
  type: MergeSourceType;
  id: string;
  title: string;
  subtitle: string;
  poster: string | null;
  url: string;
  duration_s: number | null;
  width: number | null;
  height: number | null;
  created_at: string | null;
  /** Только у своих видео (upload): размер файла, есть ли звук, до какого числа хранится. */
  size_bytes?: number;
  has_audio?: boolean;
  expires_at?: string | null;
}

/** У upload в идущей и готовой склейке — слепок без size_bytes/has_audio/expires_at. */
export interface MergeItem extends Omit<MergeSourceCard, "created_at" | "url"> {
  url: string | null;
  available: boolean;
}

/** Пределы своих видео (config/ → uploads, uploads/ → limits). */
export interface MergeUploadLimits {
  max_bytes: number;
  max_mb: number;
  min_duration_s: number;
  max_duration_s: number;
  max_side: number;
  /** Кадров в секунду в среднем (Build MU, MU_FIX2); старый сервер не присылает. */
  max_fps?: number;
  max_per_project: number;
  max_files: number;
  max_total_bytes: number;
  max_total_mb: number;
  retention_days: number;
  extensions: string[];
  accept: string;
}

/** Ответ загрузки и строка «Моих файлов»: карточка источника плюс три поля. */
export interface MergeUploadCard extends MergeSourceCard {
  size_bytes: number;
  has_audio: boolean;
  expires_at: string | null;
}

export interface MergeUploadUsage {
  files: number;
  bytes: number;
  max_files: number;
  max_bytes: number;
}

export interface MergeUploadList {
  results: MergeUploadCard[];
  usage: MergeUploadUsage;
  limits: MergeUploadLimits;
}

export interface MergeLimits {
  min_fragments: number;
  max_fragments: number;
  max_total_s: number;
  retention_days: number;
}

export interface MergeBalance {
  balance: number;
  reserved: number;
  available: number;
  after: number;
}

/** mixing — сведение звука после склейки (только у склеек со звуком, Build MA). */
export type MergeStage = "queued" | "preparing" | "normalizing" | "joining" | "mixing" | "saving";

export interface MergeProgress {
  stage: MergeStage;
  done: number;
  total: number;
}

export interface MergeRenderBlock {
  error_code: "too_few_fragments" | "source_unavailable" | "too_long" | "audio_pending";
  error: string;
  index?: number;
}

export interface MergeProjectBrief {
  id: string;
  title: string;
  status: MergeStatus;
  aspect: MergeAspect;
  fit: MergeFit;
  fragments: number;
  total_duration_s: number;
  duration_s: number | null;
  poster_url: string | null;
  error: string;
  error_code: string | null;
  error_fragment: number | null;
  expires_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface MergeProject extends MergeProjectBrief {
  items: MergeItem[];
  progress: MergeProgress | null;
  result_url: string | null;
  download_url: string | null;
  credits_reserved: number;
  credits_charged: number;
  price_credits: number | null;
  can_render: boolean;
  render_block: MergeRenderBlock | null;
  finished_at: string | null;
  limits: MergeLimits;
  /** Только в ответе render/. */
  balance?: MergeBalance;
  /** Коротко о звуке (Build MA); старый сервер не присылает. */
  audio?: MergeAudioSummary;
}

export interface MergeConfig {
  price_credits: number;
  limits: MergeLimits;
  aspects: MergeAspect[];
  fits: MergeFit[];
  source_types: MergeSourceType[];
  authenticated: boolean;
  balance: MergeBalance | null;
  /** Build MU; старый сервер его не присылает — тогда пределы по умолчанию. */
  uploads?: MergeUploadLimits;
  /** Бесплатных склеек в сутки (только при цене 0); null или нет поля — предела нет. */
  free_daily_limit?: number | null;
}

export interface MergeSourcesPage {
  type: string;
  page: number;
  page_size: number;
  has_more: boolean;
  results: MergeSourceCard[];
}

export interface MergeList {
  results: MergeProjectBrief[];
  page: number;
  has_more: boolean;
  active_id: string | null;
  price_credits: number;
  limits: MergeLimits;
}

/** Тело создания, правки и запуска: все поля необязательны. */
export interface MergeEditBody {
  title?: string;
  aspect?: MergeAspect;
  fit?: MergeFit;
  items?: { type: MergeSourceType; id: string }[];
  /** Только при создании: звук своей склейки переходит в новую (копии файлов, бесплатно). */
  copy_audio_from?: string;
}

export interface MergeRenderBody extends MergeEditBody {
  /** Цена, показанная на кнопке: разошлась с серверной — 409 price_changed. */
  price?: number;
}

/* ---------- звук (CONTRACT_M.md §10, Build MA) ---------- */

/** Звук самих роликов в сведении: как есть, тише (0,3) или выключен. */
export type MergeClipSound = "keep" | "quiet" | "off";
export type MergeTrackKind = "voice" | "music";

export interface MergeTrack {
  id: string;
  kind: MergeTrackKind;
  /** upload — свой трек (только музыка). */
  source: "generated" | "upload";
  status: "pending" | "ready" | "failed";
  url: string | null;
  duration_s: number | null;
  text: string;
  prompt: string;
  title: string;
  voice_id: string;
  voice_name: string;
  /** С какого фрагмента голос (с нуля); у музыки null. */
  start_fragment: number | null;
  /** Где голос начнётся сейчас: фрагменты убрали — с последнего. */
  start_fragment_effective: number | null;
  /** Сколько секунд музыки заказано. */
  seconds: number | null;
  credits_reserved: number;
  credits_charged: number;
  error: string;
  error_code: string | null;
  /** Ключ нажатия, которым дорожку заказали (MA_FIX6); у своего трека и копий — null. */
  request_id: string | null;
  created_at: string | null;
  expires_at: string | null;
}

export interface MergeAudioLimits {
  voice_chars: number;
  prompt_min_chars: number;
  prompt_chars: number;
  music_min_s: number;
  music_max_s: number;
  upload_max_bytes: number;
  upload_max_mb: number;
  upload_max_s: number;
  extensions: string[];
  accept: string;
  music_volume_max: number;
  voice_volume_max: number;
  clip_sounds: MergeClipSound[];
  clip_volumes: Record<MergeClipSound, number>;
  retention_days: number;
}

export interface MergeAudioPrices {
  voice_per_1k: number;
  voice_min: number;
  music_per_min: number;
}

export interface MergeAudioState {
  project_id: string;
  status: MergeStatus;
  editable: boolean;
  edit_block: { error_code: string; error: string } | null;
  /** Ключ ElevenLabs задан: без него — только свой трек. */
  configured: boolean;
  clip_sound: MergeClipSound;
  music_volume: number;
  voice_volume: number;
  tracks: MergeTrack[];
  fragments: number;
  total_duration_s: number;
  prices: MergeAudioPrices;
  music_quote: { seconds: number; credits: number } | null;
  limits: MergeAudioLimits;
  /** Ответы POST: дорожка этого запроса и баланс. */
  track?: MergeTrack;
  balance?: MergeBalance;
}

/** ProjectJSON.audio: есть ли готовый голос и музыка, делается ли что-то. */
export interface MergeAudioSummary {
  clip_sound: MergeClipSound;
  music_volume: number;
  voice_volume: number;
  voice: boolean;
  music: boolean;
  pending: boolean;
}

/** PATCH audio/: любое из полей; отказ одного — отказ всей правки. */
export interface MergeAudioSettings {
  clip_sound?: MergeClipSound;
  music_volume?: number;
  voice_volume?: number;
  voice_start_fragment?: number;
}

export interface MergeVoiceBody {
  text: string;
  voice_id: string;
  start_fragment: number;
  /** Цена на кнопке: разошлась с серверной — 409 audio_price_changed. */
  price?: number;
  /** Один на нажатие: повтор того же запроса не спишет второй раз. */
  request_id?: string;
}

export interface MergeMusicBody {
  prompt: string;
  price?: number;
  request_id?: string;
}

/** Голос ElevenLabs из общего списка мультстудии (/api/cartoon/audio/voices/). */
export interface MergeVoice {
  id: string;
  name: string;
  gender: string;
  age: string;
  accent: string;
  description: string;
  use_case: string;
  preview: string;
}

/**
 * «Склейка видео»: формы ответов /api/merge/ (vstudio2-notes/pricing/CONTRACT_M.md §7).
 *
 * Идентификатор склейки — uid из 32 hex, идентификаторы источников — строки.
 * В запросах фрагменты — только {type, id}: всё остальное сервер собирает сам.
 */

export type MergeSourceType = "vstudio" | "cartoon_scene" | "cartoon_movie" | "chat";
/** Вкладки выбора: «Мультстудия» отдаёт мультфильмы и сцены вместе. */
export type MergeTab = "vstudio" | "cartoon" | "chat";
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
}

export interface MergeItem extends Omit<MergeSourceCard, "created_at" | "url"> {
  url: string | null;
  available: boolean;
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

export type MergeStage = "queued" | "preparing" | "normalizing" | "joining" | "saving";

export interface MergeProgress {
  stage: MergeStage;
  done: number;
  total: number;
}

export interface MergeRenderBlock {
  error_code: "too_few_fragments" | "source_unavailable" | "too_long";
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
}

export interface MergeConfig {
  price_credits: number;
  limits: MergeLimits;
  aspects: MergeAspect[];
  fits: MergeFit[];
  source_types: MergeSourceType[];
  authenticated: boolean;
  balance: MergeBalance | null;
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
}

export interface MergeRenderBody extends MergeEditBody {
  /** Цена, показанная на кнопке: разошлась с серверной — 409 price_changed. */
  price?: number;
}

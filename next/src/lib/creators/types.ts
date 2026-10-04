/**
 * EsAI Creators: типы ответов /api/creators/ (публичная страница и кабинет).
 *
 * Имена полей — ровно как их отдаёт сервер (core/creators/serializers.py,
 * views.py). Деньги приходят строками и строками остаются: в браузере их
 * только показывают (format.ts), считать нельзя.
 */

export type CrMode = "off" | "staff" | "on";
export type CrLang = "ru" | "en" | "kg";
/** "8460.00" (два знака) или "12.345678" (шесть — сумма комиссии). */
export type Usdt = string;
/** "15.00" */
export type Pct = string;
export type Iso = string;

/** Отказ API: решения в интерфейсе принимаются по code, а не по тексту. */
export type CrError = {
  status: number;
  code: string;
  message: string;
  fields?: Record<string, string>;
  /** Тело ответа целиком: доп. поля отказа (available, taken_by). */
  data: Record<string, unknown>;
};
export type CrResult<T> = { ok: true; status: number; data: T } | { ok: false; status: number; error: CrError };
export type Paged<T> = { count: number; results: T[] };

export type LevelRow = {
  key: string;
  title: string;
  percent: Pct;
  sort: number;
  min_publications: number;
  min_registrations: number;
  min_paying: number;
};
export type LevelBrief = { key: string; title: string; percent: Pct };

export type ApplicationStatus = "new" | "approved" | "rejected" | "blocked";
export type CreatorStatus = "active" | "blocked";
export type Program = {
  mode: CrMode;
  min_payout_usdt: Usdt;
  hold_days: number;
  network: "TRC20";
  levels: LevelRow[];
  me: {
    is_authenticated: boolean;
    is_creator: boolean;
    creator_status: CreatorStatus | null;
    application_status: ApplicationStatus | null;
  };
};
export type Invite = { invited_by: string | null; code: string | null; bound_at: Iso | null };

export type Application = {
  id: number;
  status: ApplicationStatus;
  created_at: Iso;
  decided_at: Iso | null;
  reject_reason: string;
  name: string;
  telegram: string;
  country: string;
  instagram_url: string;
  tiktok_url: string;
  youtube_url: string;
  other_links: string[];
  followers: number;
  occupation: string;
  motivation: string;
  samples: string[];
};
export type ApplicationBody = Omit<Application, "id" | "status" | "created_at" | "decided_at" | "reject_reason"> & {
  lang: CrLang;
};

export type Part = { have: number; need: number; done: boolean };
export type Progress = {
  next_level: LevelBrief | null;
  publications: Part;
  registrations: Part;
  paying: Part;
  conditions_met: boolean;
  awaiting_confirmation?: boolean;
};
export type Counters = {
  clicks: number;
  registrations: number;
  paying: number;
  orders: number;
  sales_usdt: Usdt;
  publications_approved: number;
};
export type MoneyJson = {
  earned: Usdt;
  pending: Usdt;
  held: Usdt;
  available: Usdt;
  in_withdrawal: Usdt;
  paid: Usdt;
  debt: Usdt;
};
export type WithdrawalStatus = "review" | "approved" | "paid" | "rejected";
export type Withdrawal = {
  id: number;
  created_at: Iso;
  amount_usdt: Usdt;
  address: string;
  network: string;
  status: WithdrawalStatus;
  txid: string;
  reject_reason: string;
  approved_at: Iso | null;
  paid_at: Iso | null;
};
export type Me = {
  creator: { id: number; status: CreatorStatus; display_name: string; joined_at: Iso; lang: CrLang };
  level: LevelBrief;
  code: string | null;
  link: string | null;
  telegram_link: string | null;
  counters: Counters;
  money: MoneyJson & { min_payout: Usdt; can_withdraw: boolean; payouts_enabled: boolean };
  progress: Progress;
  credits: { granted: number; remaining: number };
  payout_address: string;
  payout_address_changed_at: Iso | null;
  open_withdrawal: Withdrawal | null;
};

export type CodeCheck = { code: string; available: boolean; reason?: "code_format" | "code_reserved" | "code_taken" };
export type CodeCreated = { code: string; link: string; telegram_link: string | null };
export type Network = "instagram" | "tiktok" | "youtube" | "telegram" | "facebook" | "x" | "vk" | "other";
export type PublicationStatus = "review" | "approved" | "rejected";
export type Publication = {
  id: number;
  network: Network;
  url: string;
  description: string;
  status: PublicationStatus;
  created_at: Iso;
  decided_at: Iso | null;
  reject_reason: string;
};
export type CreditGrant = {
  id: number;
  date: Iso;
  amount: number;
  category: string;
  category_label: string;
  note: string;
  kind?: "grant";
  remaining_after?: number;
};
export type CreditSpend = {
  id: number;
  date: Iso;
  /** Отрицательное число. */
  amount: number;
  kind: "spend";
  reason: string;
  reason_label: string;
  remaining_after: number;
};
export type Credits = {
  granted: number;
  remaining: number;
  spent: number;
  count: number;
  results: (CreditGrant | CreditSpend)[];
};
export type CommissionStatus = "accrued" | "held" | "reversed" | "void";
export type Commission = {
  id: number;
  date: Iso;
  buyer: string;
  provider: string;
  base_usdt: Usdt;
  percent: Pct;
  /** Шесть знаков, как прислал сервер. */
  amount_usdt: Usdt;
  status: CommissionStatus;
  reason: "" | "review" | "refund" | "cancelled";
  available_at: Iso | null;
};
export type ReferralSource = "link" | "promo" | "bot" | "admin";
export type Referral = {
  id: number;
  /** Маска: ни id, ни почты реферала кабинет не получает. */
  user: string;
  bound_at: Iso;
  source: ReferralSource;
  is_paying: boolean;
  orders: number;
  sales_usdt: Usdt;
  commission_usdt: Usdt;
};

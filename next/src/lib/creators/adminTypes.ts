/**
 * EsAI Creators: типы ответов раздела «Creators» панели (/api/manage/creators/…).
 * Имена полей — как в core/adminapi/creators.py и core/creators/serializers.py.
 */
import type {
  Application,
  CommissionStatus,
  Counters,
  CreatorStatus,
  CrLang,
  CrMode,
  Iso,
  LevelRow,
  MoneyJson,
  Pct,
  Progress,
  Publication,
  ReferralSource,
  Usdt,
  WithdrawalStatus,
} from "./types";

export type AdminApplication = Application & {
  lang: CrLang;
  ip: string | null;
  user_id: number;
  email: string | null;
  decided_by_id: number | null;
  decided_by_email: string | null;
};
export type AdminCreatorRow = {
  id: number;
  user_id: number;
  email: string;
  username: string;
  display_name: string;
  telegram: string;
  level: { key: string; title: string };
  percent: Pct;
  status: CreatorStatus;
  code: string | null;
  clicks: number;
  registrations: number;
  paying: number;
  sales_usdt: Usdt;
  earned_usdt: Usdt;
  credits_granted: number;
  conditions_met: boolean;
  joined_at: Iso;
};
export type AdminPublication = Publication & {
  creator_id: number;
  creator_name: string;
  decided_by_email: string | null;
};
export type AdminReferral = {
  id: number;
  user_id: number;
  email: string | null;
  user_label: string;
  creator_id: number;
  creator_name: string;
  source: ReferralSource;
  code_used: string;
  bound_at: Iso;
  bound_by_email: string | null;
  ended_at: Iso | null;
  end_reason: string;
  suspect: boolean;
  flags: { reasons?: string[]; cleared_by?: number };
  is_paying: boolean;
  orders: number;
  sales_usdt: Usdt;
  commission_usdt: Usdt;
  referred_by_id: number | null;
};
export type AdminCommission = {
  id: number;
  created_at: Iso;
  creator_id: number;
  creator_name: string;
  buyer_pk: number;
  buyer_email: string | null;
  payment_id: number;
  order_id: string;
  part: string;
  provider: string;
  paid_amount: string;
  paid_currency: string;
  rate_to_usd: string;
  rate_source: string;
  /** Шесть знаков. */
  base_usd: Usdt;
  level_key: string;
  percent: Pct;
  /** Шесть знаков. */
  amount_usdt: Usdt;
  status: CommissionStatus;
  reason: string;
  available_at: Iso | null;
  reversed_at: Iso | null;
};
export type AdminWithdrawal = {
  id: number;
  creator_id: number;
  creator_name: string;
  creator_status: CreatorStatus;
  email: string | null;
  amount_usdt: Usdt;
  address: string;
  network: string;
  status: WithdrawalStatus;
  txid: string;
  created_at: Iso;
  approved_at: Iso | null;
  approved_by_email: string | null;
  paid_at: Iso | null;
  paid_by_email: string | null;
  rejected_at: Iso | null;
  reject_reason: string;
  address_changed_at: Iso | null;
  balance: MoneyJson;
  /** false — после заявки пришёл возврат: платить по ней уже нечем. */
  covered: boolean;
};
export type AdminCreditRow = {
  id: number;
  date: Iso;
  amount: number;
  category?: string;
  category_label?: string;
  note?: string;
  balance_after?: number;
  by_id?: number | null;
  by_email?: string | null;
  kind?: "grant" | "spend";
  reason?: string;
  reason_label?: string;
  remaining_after?: number;
  creator_id?: number | null;
  creator_name?: string | null;
};
export type AdminLevel = LevelRow & { creators: number };
export type AdminLogRow = {
  id: number;
  created_at: Iso;
  actor_id: number;
  actor_email: string | null;
  action: string;
  target_type: string;
  target_id: string;
  creator_id: number | null;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  reason: string;
  ip: string | null;
};
export type AdminSettings = { mode: CrMode; payouts_enabled: boolean; hold_days: number };
export type AdminCreatorProfile = {
  creator: AdminCreatorRow & {
    lang: CrLang;
    blocked_at: Iso | null;
    blocked_reason: string;
    payout_address: string;
    payout_address_changed_at: Iso | null;
  };
  application: AdminApplication | null;
  codes: { code: string; is_primary: boolean; is_active: boolean; created_at: Iso }[];
  counters: Counters & { suspect_referrals: number };
  money: MoneyJson;
  progress: Progress;
  publications: AdminPublication[];
  referrals: AdminReferral[];
  credits: { granted: number; remaining: number; spent: number; wallet_balance: number; history: AdminCreditRow[] };
  withdrawals: AdminWithdrawal[];
  risk: { suspect_referrals: number; held_commissions: number; reversed_commissions: number; debt: Usdt };
  log: AdminLogRow[];
};

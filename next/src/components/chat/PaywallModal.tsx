"use client";

import { useTranslation } from "react-i18next";
import { Modal } from "@/components/dialog/Dialog";
import { FiLock, FiZap, FiClock } from "react-icons/fi";

/**
 * The chat backend rejects a request with one of these `error_code`s
 * (in the JSON body and/or the SSE error frame). PaywallModal turns each into a
 * branded up-sell dialog. `null` keeps the modal closed.
 */
export type PaywallReason =
  | "premium_locked"
  | "insufficient_balance"
  | "insufficient_tokens"
  | "daily_limit_reached";

export type PaywallContext = {
  /** error_code that triggered the modal */
  reason: PaywallReason;
  /** cheapest package price in KGS (от бэка: min_package_kgs), default 190 */
  minPackageKgs?: number;
  /** current balance (insufficient_balance) */
  balanceTokens?: number;
  /** estimated tokens required for the request (insufficient_balance) */
  requiredEstimate?: number;
  /** daily request limit (daily_limit_reached) */
  limit?: number;
};

type Props = {
  context: PaywallContext | null;
  onClose: () => void;
  /** opens the top-up flow (TopUpModal). When omitted we route to /pricing. */
  onTopUp?: () => void;
};

const fmt = (n: number) => n.toLocaleString("ru-RU");

/**
 * PaywallModal — single reusable up-sell modal (бренд: чёрный + золото) shown
 * when the chat endpoint refuses a request. The copy and icon adapt to the
 * `error_code` while the CTA always leads to the existing top-up flow.
 */
export default function PaywallModal({ context, onClose, onTopUp }: Props) {
  const { t } = useTranslation("common");

  const open = context != null;
  const reason = context?.reason;
  const minKgs = context?.minPackageKgs ?? 190;

  // Per-reason title / description / icon.
  let title = t("paywall.title_generic", { defaultValue: "Пополните баланс" });
  let icon = <FiZap />;
  let desc = "";

  if (reason === "premium_locked") {
    icon = <FiLock />;
    title = t("paywall.premium_title", {
      defaultValue: "Премиум-модель доступна на платном тарифе",
    });
    desc = t("paywall.premium_desc", {
      defaultValue:
        "Пополните баланс на {{kgs}} сомов, чтобы открыть все премиум-нейросети планеты.",
      kgs: fmt(minKgs),
    });
  } else if (reason === "insufficient_balance") {
    icon = <FiZap />;
    title = t("paywall.insufficient_title", { defaultValue: "Недостаточно кредитов" });
    const haveLine =
      typeof context?.balanceTokens === "number"
        ? t("paywall.insufficient_have", {
            defaultValue: "На балансе {{have}} кредитов.",
            have: fmt(context!.balanceTokens!),
          }) + " "
        : "";
    const needLine =
      typeof context?.requiredEstimate === "number"
        ? t("paywall.insufficient_need", {
            defaultValue: "Для запроса нужно около {{need}}.",
            need: fmt(context!.requiredEstimate!),
          }) + " "
        : "";
    desc =
      haveLine +
      needLine +
      t("paywall.insufficient_cta_desc", {
        defaultValue: "Пополните баланс, чтобы продолжить.",
      });
  } else if (reason === "insufficient_tokens") {
    icon = <FiZap />;
    title = t("paywall.insufficient_title", { defaultValue: "Недостаточно кредитов" });
    desc = t("paywall.zero_desc", {
      defaultValue: "На вашем балансе закончились кредиты. Пополните баланс, чтобы продолжить.",
    });
  } else if (reason === "daily_limit_reached") {
    icon = <FiClock />;
    title = t("paywall.daily_title", { defaultValue: "Достигнут дневной лимит запросов" });
    const limitLine =
      typeof context?.limit === "number"
        ? t("paywall.daily_count", {
            defaultValue: "Сегодня вы использовали все {{limit}} бесплатных запросов.",
            limit: fmt(context!.limit!),
          }) + " "
        : "";
    desc =
      limitLine +
      t("paywall.daily_desc", {
        defaultValue:
          "Перейдите на платный пакет, чтобы снять дневной лимит и получать больше запросов.",
      });
  }

  const handleTopUp = () => {
    onClose();
    if (onTopUp) onTopUp();
    else if (typeof window !== "undefined") window.location.href = "/pricing";
  };

  return (
    <Modal title={title} open={open} onClose={onClose} size="sm">
      <div className="p-2 text-center">
        <div className="mx-auto w-14 h-14 rounded-full bg-accent-soft text-accent grid place-items-center text-2xl mb-4">
          {icon}
        </div>
        <p className="text-sm text-muted leading-relaxed">{desc}</p>

        <div className="mt-5 flex gap-2">
          <button
            type="button"
            onClick={onClose}
            className="flex-1 rounded-xl border border-border py-2.5 text-sm hover:bg-surface-2 transition-colors cursor-pointer"
          >
            {t("common.cancel", { defaultValue: "Отмена" })}
          </button>
          <button
            type="button"
            onClick={handleTopUp}
            className="flex-1 inline-flex items-center justify-center gap-2 rounded-xl bg-accent text-on-accent font-semibold py-2.5 text-sm hover:bg-accent-strong transition-colors cursor-pointer"
          >
            <FiZap />
            {reason === "daily_limit_reached"
              ? t("paywall.cta_upgrade", { defaultValue: "Перейти на платный пакет" })
              : t("balance.topup", { defaultValue: "Пополнить" })}
          </button>
        </div>
      </div>
    </Modal>
  );
}

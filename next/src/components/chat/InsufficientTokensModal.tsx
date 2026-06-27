"use client";

import { useTranslation } from "react-i18next";
import { Modal } from "@/components/dialog/Dialog";
import { FiZap } from "react-icons/fi";

type Props = {
  open: boolean;
  onClose: () => void;
  onTopUp: () => void;
};

/** Shown when the chat endpoint returns 402 insufficient_tokens. */
export default function InsufficientTokensModal({ open, onClose, onTopUp }: Props) {
  const { t } = useTranslation("common");
  return (
    <Modal title={t("topup.insufficient_title", { defaultValue: "Недостаточно токенов" })} open={open} onClose={onClose} size="sm">
      <div className="p-2 text-center">
        <div className="mx-auto w-12 h-12 rounded-full bg-accent-soft text-accent grid place-items-center text-2xl mb-3">
          <FiZap />
        </div>
        <p className="text-sm text-muted">
          {t("topup.insufficient_desc", {
            defaultValue: "На вашем балансе закончились токены. Пополните баланс, чтобы продолжить.",
          })}
        </p>
        <div className="mt-4 flex gap-2">
          <button
            type="button"
            onClick={onClose}
            className="flex-1 rounded-xl border border-border py-2.5 text-sm hover:bg-surface-2 cursor-pointer"
          >
            {t("common.cancel", { defaultValue: "Отмена" })}
          </button>
          <button
            type="button"
            onClick={() => {
              onClose();
              onTopUp();
            }}
            className="flex-1 rounded-xl bg-accent text-on-accent font-semibold py-2.5 text-sm hover:bg-accent-strong cursor-pointer"
          >
            {t("balance.topup", { defaultValue: "Пополнить" })}
          </button>
        </div>
      </div>
    </Modal>
  );
}

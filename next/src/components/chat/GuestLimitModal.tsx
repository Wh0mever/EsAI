"use client";

import { useTranslation } from "react-i18next";
import { Modal } from "@/components/dialog/Dialog";
import { FiLock } from "react-icons/fi";
import SocialAuthButtons from "@/components/auth/SocialAuthButtons";

type Props = {
  open: boolean;
  onClose: () => void;
};

/**
 * GuestLimitModal — shown when the chat backend returns HTTP 401
 * { error: "guest_limit_reached" }. Invites the guest to sign in with
 * Google or Telegram to continue (reuses SocialAuthButtons).
 */
export default function GuestLimitModal({ open, onClose }: Props) {
  const { t } = useTranslation("common");
  return (
    <Modal
      title={t("guest.limit_title", { defaultValue: "Бесплатный лимит исчерпан" })}
      open={open}
      onClose={onClose}
      size="sm"
    >
      <div className="p-2 text-center">
        <div className="mx-auto w-12 h-12 rounded-full bg-accent-soft text-accent grid place-items-center text-2xl mb-3">
          <FiLock />
        </div>
        <p className="text-sm text-muted mb-5">
          {t("guest.limit_desc", {
            defaultValue:
              "Вы использовали бесплатный лимит. Войдите через Google или Telegram, чтобы продолжить.",
          })}
        </p>

        <SocialAuthButtons />
      </div>
    </Modal>
  );
}

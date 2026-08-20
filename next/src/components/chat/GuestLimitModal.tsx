"use client";

import { useTranslation } from "react-i18next";
import Link from "next/link";
import { Modal } from "@/components/dialog/Dialog";
import { FiLock } from "react-icons/fi";
import SocialAuthButtons from "@/components/auth/SocialAuthButtons";
import { useBonusSettings } from "@/hooks/useBonusSettings";

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
  const bonus = useBonusSettings();
  return (
    <Modal
      title={t("guest.limit_title", { defaultValue: "Продолжим? 🎁" })}
      open={open}
      onClose={onClose}
      size="sm"
    >
      <div className="p-2 text-center">
        <div className="mx-auto w-12 h-12 rounded-full bg-accent-soft text-accent grid place-items-center text-2xl mb-3">
          <FiLock />
        </div>
        <p className="text-sm text-muted mb-5">
          {bonus.loaded
            ? t("guest.limit_desc", {
                count: bonus.welcome_bonus,
                defaultValue:
                  "Получите {{count}} кредитов в подарок за регистрацию. Без карты, без подписок.",
              })
            : t("guest.limit_desc_plain", {
                defaultValue:
                  "Получите бонусные кредиты в подарок за регистрацию. Без карты, без подписок.",
              })}
        </p>

        <SocialAuthButtons />

        <Link
          href="/auth/signin?next=/"
          className="mt-4 inline-block text-sm text-accent-strong hover:text-accent transition-colors"
        >
          {t("guest.more_login_options", { defaultValue: "Все способы входа (Email)" })}
        </Link>
      </div>
    </Modal>
  );
}

"use client";

import { useTranslation } from "react-i18next";
import { FaGoogle } from "react-icons/fa";
import TelegramLoginButton from "./TelegramLoginButton";

/**
 * SocialAuthButtons — per spec 2.4 only Google + Telegram are offered
 * (Facebook/Instagram removed). Google is a simple link to the backend OAuth
 * entrypoint; Telegram renders the official Login Widget.
 */
export default function SocialAuthButtons() {
  const { t } = useTranslation("common");

  return (
    <div className="w-full flex flex-col items-center gap-3">
      <a
        href="/api/users/accounts/google/login/?process=login"
        aria-label={t("auth.google", { defaultValue: "Войти через Google" })}
        className="w-full max-w-xs inline-flex items-center justify-center gap-2 rounded-full border border-neutral-300 bg-white text-neutral-900 px-4 py-2.5 text-sm font-medium transition hover:-translate-y-0.5 hover:border-neutral-900 hover:bg-neutral-50"
      >
        <FaGoogle className="text-lg" />
        <span>{t("auth.google", { defaultValue: "Войти через Google" })}</span>
      </a>

      <TelegramLoginButton />
    </div>
  );
}

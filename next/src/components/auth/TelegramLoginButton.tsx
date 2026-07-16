"use client";

import { useTranslation } from "react-i18next";
import { FaTelegramPlane } from "react-icons/fa";

type Props = { className?: string };

const TG_LOGIN_URL = "/api/users/accounts/telegram/login/?process=login";

/**
 * TelegramLoginButton — вход через Telegram по ШТАТНОМУ потоку allauth:
 * ссылка на `/api/users/accounts/telegram/login/?process=login` → allauth
 * редиректит на oauth.telegram.org → callback получает tgAuthResult+state и
 * проверяет подпись. Точно как Google-кнопка.
 *
 * Раньше тут рисовался классический Telegram-виджет с `data-auth-url`, который
 * шлёт GET-параметры (id/hash/auth_date) — несовместимо с allauth-callback
 * (тот ждёт tgAuthResult POST + state), из-за чего был social_login_failed.
 */
export default function TelegramLoginButton({ className }: Props) {
  const { t } = useTranslation("common");
  return (
    <a
      href={TG_LOGIN_URL}
      aria-label={t("auth.telegram", { defaultValue: "Войти через Telegram" })}
      className={
        className ??
        "w-full max-w-xs inline-flex items-center justify-center gap-2 rounded-full bg-[#229ED9] text-white px-4 py-2.5 text-sm font-medium transition hover:-translate-y-0.5 hover:bg-[#1d8dc2]"
      }
    >
      <FaTelegramPlane className="text-lg" />
      <span>{t("auth.telegram", { defaultValue: "Войти через Telegram" })}</span>
    </a>
  );
}

"use client";

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { FaFacebookF, FaGoogle, FaInstagram } from "react-icons/fa";

type SocialProvider = {
  id: "google" | "facebook" | "instagram";
  href?: string;
  label: string;
  icon: ReactNode;
  enabled: boolean;
};

export default function SocialAuthButtons() {
  const { t } = useTranslation("common");

  const providers: SocialProvider[] = [
    {
      id: "google",
      href: "/api/users/accounts/google/login/?process=login",
      label: "Google",
      icon: <FaGoogle className="text-lg" />,
      enabled: true,
    },
    {
      id: "facebook",
      href: "/api/users/accounts/facebook/login/?process=login",
      label: "Facebook",
      icon: <FaFacebookF className="text-lg" />,
      enabled: true,
    },
    {
      id: "instagram",
      href: "/api/users/accounts/instagram/login/?process=login",
      label: "Instagram",
      icon: <FaInstagram className="text-lg" />,
      enabled: true,
    },
  ];

  return (
    <div className="w-full flex items-center justify-center gap-3">
      {providers.map((provider) =>
        provider.enabled && provider.href ? (
          <a
            key={provider.id}
            href={provider.href}
            aria-label={provider.label}
            title={provider.label}
            className="flex h-12 w-12 items-center justify-center rounded-full border border-neutral-300 bg-white text-neutral-900 transition hover:-translate-y-0.5 hover:border-neutral-900 hover:bg-neutral-50"
          >
            {provider.icon}
          </a>
        ) : (
          <button
            key={provider.id}
            type="button"
            aria-label={`${provider.label} unavailable`}
            title={`${provider.label}: ${t("auth.social_soon", { defaultValue: "Скоро" })}`}
            disabled
            className="flex h-12 w-12 cursor-not-allowed items-center justify-center rounded-full border border-dashed border-neutral-300 bg-neutral-100 text-neutral-400"
          >
            {provider.icon}
          </button>
        )
      )}
    </div>
  );
}

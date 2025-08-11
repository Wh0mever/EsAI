"use client";

import Link from "next/link";
import { useTranslation } from "react-i18next";
import Cookies from "js-cookie";
import { useEffect, useState } from "react";

export default function AuthButtons() {
  const { t } = useTranslation("home");
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  useEffect(() => {
    const token = Cookies.get("access");
    setIsAuthenticated(!!token);
  }, []);

  if (isAuthenticated) {
    return (
      <div className="flex items-center gap-2">
        <Link
          href="/dashboard"
          className="bg-indigo-500 px-4 py-2 rounded-3xl hover:bg-indigo-600 text-nowrap duration-300"
        >
          {t("nav.dashboard")}
        </Link>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 bg-neutral-900 rounded-4xl px-3 py-2">
      <Link
        href="/auth/signin"
        className="border border-neutral-700 px-4 py-2 rounded-3xl hover:bg-indigo-600 text-nowrap duration-300"
      >
        {t("nav.signin")}
      </Link>

      <div className="text-neutral-500 px-1 hidden lg:block">|</div>

      <Link
        href="/auth/signup"
        className="hidden lg:inline-flex bg-indigo-500 px-4 py-2 rounded-3xl hover:bg-indigo-600 text-nowrap duration-300"
      >
        {t("nav.signup")}
      </Link>
    </div>
  );
}

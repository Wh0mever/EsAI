"use client";

import Link from "next/link";
import { useTranslation } from "react-i18next";
import Cookies from "js-cookie";
import { useEffect, useState } from "react";
import { FiUserPlus, FiLogIn, FiGrid } from "react-icons/fi";

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
        {/* Desktop версия — текст */}
        <Link
          href="/dashboard/text-chat"
          className="hidden lg:inline-flex bg-indigo-500 px-4 py-2 rounded-3xl hover:bg-indigo-600 text-nowrap duration-300"
        >
          {t("nav.dashboard")}
        </Link>

        {/* Мобильная/планшетная версия — иконка */}
        <Link
          href="/dashboard/text-chat"
          className="lg:hidden bg-indigo-500 p-3 rounded-3xl hover:bg-indigo-600 duration-300"
        >
          <FiGrid className="text-xl" />
        </Link>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 bg-neutral-900 rounded-4xl px-3 py-2">
      {/* Signin */}
      <Link
        href="/auth/signin"
        className="hidden lg:inline-flex border border-neutral-700 px-4 py-2 rounded-3xl hover:bg-indigo-600 text-nowrap duration-300"
      >
        {t("nav.signin")}
      </Link>
      <Link
        href="/auth/signin"
        className="lg:hidden border border-neutral-700 p-3 rounded-3xl hover:bg-indigo-600 duration-300"
      >
        <FiLogIn className="text-xl" />
      </Link>

      <div className="text-neutral-500 px-1 hidden lg:block">|</div>

      {/* Signup */}
      <Link
        href="/auth/signup"
        className="hidden lg:inline-flex bg-indigo-500 px-4 py-2 rounded-3xl hover:bg-indigo-600 text-nowrap duration-300"
      >
        {t("nav.signup")}
      </Link>
      <Link
        href="/auth/signup"
        className="lg:hidden bg-indigo-500 p-3 rounded-3xl hover:bg-indigo-600 duration-300"
      >
        <FiUserPlus className="text-xl" />
      </Link>
    </div>
  );
}

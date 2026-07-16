"use client";

import Link from "next/link";
import Cookies from "js-cookie";
import clsx from "clsx";
import { memo } from "react";
import { useTranslation } from "react-i18next";
import { DropDownHovered } from "@/components/ui/dropDown/DropDownHovered";
import { Button } from "@/components/ui/buttons/Buttons";
import { usePathname } from "next/navigation";
import { setLanguagePreference } from "@/lib/locale";

type Variant = "desktop" | "mobile";
type Props = { variant?: Variant; className?: string; onNavigate?: () => void };

type Lang = { code: "ru" | "en" | "kg"; icon: string; label: string };

const LANGUAGES: Lang[] = [
  { code: "ru", icon: "/images/local/ru.webp", label: "Русский" },
  { code: "en", icon: "/images/local/en.webp", label: "English" },
  { code: "kg", icon: "/images/local/kg.webp", label: "Кыргызча" },
];

const CATEGORIES_ROUTES = ["/about", "/contact-us", "/faq", "/terms-conditions"];

function useLocale() {
  const { i18n } = useTranslation();
  // Derive from the live i18n language so the UI updates instantly on switch.
  const current = i18n.language || Cookies.get("NEXT_LOCALE") || "kg";
  const change = (lang: string) => {
    if (typeof window !== "undefined") {
      setLanguagePreference(lang as "ru" | "en" | "kg");
    } else {
      Cookies.set("NEXT_LOCALE", lang);
      Cookies.set("NEXT_LOCALE_MANUAL", "1");
    }
  };
  return { currentLang: current, changeLanguage: change };
}

const LanguageMenu = memo(function LanguageMenu({
  currentLang,
  changeLanguage,
}: {
  currentLang: string;
  changeLanguage: (code: string) => void;
}) {
  return (
    <ul className="flex flex-col py-2 text-sm">
      {LANGUAGES.map(({ code, icon, label }) => (
        <li key={code} className="border-b border-neutral-700 last:border-b-0">
          <Button
            onClick={() => changeLanguage(code)}
            className={clsx(
              "py-4 px-8 w-full text-left flex items-center gap-2 transition-all duration-300 hover:bg-neutral-800",
              currentLang === code && "bg-neutral-700"
            )}
          >
            <img src={icon} alt={label} className="min-w-4 h-4 w-6 object-cover rounded-[2px]" />
            <span>{label}</span>
          </Button>
        </li>
      ))}
    </ul>
  );
});

/* ---------- Active helpers ---------- */
function useActive() {
  const pathname = usePathname() || "/";
  const isActive = (href: string, exact = false) =>
    exact ? pathname === href : pathname === href || pathname.startsWith(href + "/");
  const anyActive = (routes: string[]) => routes.some(r => isActive(r, false));
  return { pathname, isActive, anyActive };
}

/* ---------- Mobile ---------- */
// Только навигация: валюта убрана (одна валюта — сом), язык вынесен в шапку
// (LangSwitch), чтобы не нагружать меню (запрос клиента).
function MobileNav({ className, onNavigate }: any) {
  const { isActive, anyActive } = useActive();
  const { t } = useTranslation('home');

  const linkCls = (href: string, exact = false) =>
    clsx(
      "block rounded-xl px-4 py-3 hover:bg-neutral-800 transition-colors",
      isActive(href, exact) ? "bg-neutral-700 text-white" : "text-neutral-200"
    );

  return (
    <nav className={clsx("text-white", className)}>
      <ul className="flex flex-col gap-2">
        <li>
          <Link href="/" onClick={onNavigate} className={linkCls("/", true)} aria-current={isActive("/", true) ? "page" : undefined}>
            {t("nav.home")}
          </Link>
        </li>
        <li>
          <Link href="/pricing" onClick={onNavigate} className={linkCls("/pricing")} aria-current={isActive("/pricing") ? "page" : undefined}>
            {t("nav.pricing")}
          </Link>
        </li>
        <li>
          <Link href="/blog" onClick={onNavigate} className={linkCls("/blog")} aria-current={isActive("/blog") ? "page" : undefined}>
            {t("nav.blog")}
          </Link>
        </li>

        <li className="mt-2">
          <div
            className={clsx(
              "px-4 pb-1 text-xs uppercase tracking-wide",
              anyActive(CATEGORIES_ROUTES) ? "text-rose-400" : "text-neutral-400"
            )}
          >
            {t("nav.categories")}
          </div>
          <div className="flex flex-col">
            <Link href="/about" onClick={onNavigate} className={linkCls("/about")} aria-current={isActive("/about") ? "page" : undefined}>
              {t("nav.about")}
            </Link>
            <Link href="/referral" onClick={onNavigate} className={linkCls("/referral")} aria-current={isActive("/referral") ? "page" : undefined}>
              {t("nav.referral")}
            </Link>
            <Link href="/contact-us" onClick={onNavigate} className={linkCls("/contact-us")} aria-current={isActive("/contact-us") ? "page" : undefined}>
              {t("nav.contact")}
            </Link>
            <Link href="/faq" onClick={onNavigate} className={linkCls("/faq")} aria-current={isActive("/faq") ? "page" : undefined}>
              {t("nav.help")}
            </Link>
            <Link
              href="/terms-conditions"
              onClick={onNavigate}
              className={linkCls("/terms-conditions")}
              aria-current={isActive("/terms-conditions") ? "page" : undefined}
            >
              {t("nav.terms")}
            </Link>
          </div>
        </li>
      </ul>
    </nav>
  );
}

/* ---------- Desktop ---------- */
// Валюта убрана; компактный переключатель языка (флаг) оставлен.
function PCNav({ className, onNavigate, t, changeLanguage, currentLang }: any) {
  const { isActive, anyActive } = useActive();

  const linkCls = (href: string, exact = false) =>
    clsx(
      "py-3 relative",
      isActive(href, exact) ? "text-white" : "text-neutral-300",
      "hover:text-white"
    );

  const linkInner = (active: boolean) =>
    clsx(
      "inline-block",
      active && "after:content-[''] after:block after:h-[2px] after:bg-rose-500 after:rounded-full after:mt-1"
    );

  return (
    <nav className={clsx("bg-neutral-900 px-6 rounded-4xl flex items-center shadow-md", className)}>
      <ul className="flex items-center gap-10 text-md">
        <li className={linkCls("/", true)}>
          <Link href="/" onClick={onNavigate} className={linkInner(isActive("/", true))} aria-current={isActive("/", true) ? "page" : undefined}>
            {t("nav.home")}
          </Link>
        </li>
        <li className={linkCls("/pricing")}>
          <Link href="/pricing" onClick={onNavigate} className={linkInner(isActive("/pricing"))} aria-current={isActive("/pricing") ? "page" : undefined}>
            {t("nav.pricing")}
          </Link>
        </li>
        <li className={linkCls("/blog")}>
          <Link href="/blog" onClick={onNavigate} className={linkInner(isActive("/blog"))} aria-current={isActive("/blog") ? "page" : undefined}>
            {t("nav.blog")}
          </Link>
        </li>

        <li
          className={clsx(
            "py-3",
            anyActive(CATEGORIES_ROUTES) ? "text-white" : "text-neutral-300",
            "hover:text-white"
          )}
        >
          <DropDownHovered
            handleText={
              <span
                className={linkInner(anyActive(CATEGORIES_ROUTES))}
                aria-current={anyActive(CATEGORIES_ROUTES) ? "page" : undefined}
              >
                {t("nav.categories")}
              </span>
            }
          >
            <ul className="flex flex-col text-sm py-2">
              <li className="border-b border-neutral-700">
                <Link
                  href="/about"
                  onClick={onNavigate}
                  className={clsx(
                    "py-4 px-8 hover:bg-neutral-800 transition-all duration-300 flex w-full",
                    isActive("/about") && "bg-neutral-800"
                  )}
                  aria-current={isActive("/about") ? "page" : undefined}
                >
                  {t("nav.about")}
                </Link>
              </li>
              <li className="border-b border-neutral-700">
                <Link
                  href="/referral"
                  onClick={onNavigate}
                  className={clsx(
                    "py-4 px-8 hover:bg-neutral-800 transition-all duration-300 flex w-full",
                    isActive("/referral") && "bg-neutral-800"
                  )}
                  aria-current={isActive("/referral") ? "page" : undefined}
                >
                  {t("nav.referral")}
                </Link>
              </li>
              <li className="border-b border-neutral-700">
                <Link
                  href="/contact-us"
                  onClick={onNavigate}
                  className={clsx(
                    "py-4 px-8 hover:bg-neutral-800 transition-all duration-300 flex w-full",
                    isActive("/contact-us") && "bg-neutral-800"
                  )}
                  aria-current={isActive("/contact-us") ? "page" : undefined}
                >
                  {t("nav.contact")}
                </Link>
              </li>
              <li className="border-b border-neutral-700">
                <Link
                  href="/faq"
                  onClick={onNavigate}
                  className={clsx(
                    "py-4 px-8 hover:bg-neutral-800 transition-all duration-300 flex w-full",
                    isActive("/faq") && "bg-neutral-800"
                  )}
                  aria-current={isActive("/faq") ? "page" : undefined}
                >
                  {t("nav.help")}
                </Link>
              </li>
              <li>
                <Link
                  href="/terms-conditions"
                  onClick={onNavigate}
                  className={clsx(
                    "py-4 px-8 hover:bg-neutral-800 transition-all duration-300 flex w-full",
                    isActive("/terms-conditions") && "bg-neutral-800"
                  )}
                  aria-current={isActive("/terms-conditions") ? "page" : undefined}
                >
                  {t("nav.terms")}
                </Link>
              </li>
            </ul>
          </DropDownHovered>
        </li>

        <li className="py-3">
          <DropDownHovered
            handleText={
              <span className="flex items-center gap-1">
                <img src={`/images/local/${currentLang}.webp`} alt="" />
              </span>
            }
          >
            <LanguageMenu currentLang={currentLang} changeLanguage={changeLanguage} />
          </DropDownHovered>
        </li>
      </ul>
    </nav>
  );
}

export default function Nav({ variant = "desktop", className, onNavigate }: Props) {
  const { t } = useTranslation("home");
  const { currentLang, changeLanguage } = useLocale();

  if (variant === "mobile") {
    return <MobileNav className={className} onNavigate={onNavigate} />;
  }

  return (
    <PCNav
      className={className}
      onNavigate={onNavigate}
      t={t}
      changeLanguage={changeLanguage}
      currentLang={currentLang}
    />
  );
}

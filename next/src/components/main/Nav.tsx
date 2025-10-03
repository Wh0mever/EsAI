"use client";

import Link from "next/link";
import Cookies from "js-cookie";
import clsx from "clsx";
import { useEffect, useMemo, useState, memo } from "react";
import { useTranslation } from "react-i18next";
import { DropDownHovered } from "@/components/ui/dropDown/DropDownHovered";
import { Button } from "@/components/ui/buttons/Buttons";
import { useRouter, usePathname } from "next/navigation";

type Variant = "desktop" | "mobile";
type Props = { variant?: Variant; className?: string; onNavigate?: () => void };

type Lang = { code: "ru" | "en" | "kg"; icon: string; label: string };
type Currency = { code: "USD" | "RUB" | "KGS"; symbol: string; label: string };

const LANGUAGES: Lang[] = [
  { code: "ru", icon: "/images/local/ru.webp", label: "Русский" },
  { code: "en", icon: "/images/local/en.webp", label: "English" },
  { code: "kg", icon: "/images/local/kg.webp", label: "Кыргызча" },
];

const CURRENCIES: Currency[] = [
  { code: "USD", symbol: "$", label: "$ USD" },
  { code: "RUB", symbol: "₽", label: "₽ RUB" },
  { code: "KGS", symbol: "с̲", label: "с̲ KGS" },
];

const CATEGORIES_ROUTES = ["/about", "/contact-us", "/faq", "/terms-conditions"];

const CURRENCY_KEY = "APP_CURRENCY";
const CURRENCY_CHANGED_EVENT = "app:currency-changed";
import { getInitialCurrency, persistCurrency } from "@/lib/currency";
import { redirectToLanguageDomain } from "@/lib/locale";

function useLocale() {
  const current = Cookies.get("NEXT_LOCALE") || "ru";
  const change = (lang: string) => {
    if (typeof window !== "undefined") {
      redirectToLanguageDomain(lang as "ru" | "en" | "kg");
    } else {
      Cookies.set("NEXT_LOCALE", lang);
      Cookies.set("NEXT_LOCALE_MANUAL", "1");
    }
  };
  return { currentLang: current, changeLanguage: change };
}

function useCurrency() {
  const router = useRouter();
  const [currency, setCurrency] = useState<Currency["code"]>(() => (typeof window !== 'undefined' ? getInitialCurrency() : "USD"));

  useEffect(() => {
    if (typeof window === "undefined") return;
    const init = getInitialCurrency();
    setCurrency(init);
    // Ensure persistence on first run
    if (!window.localStorage.getItem(CURRENCY_KEY)) window.localStorage.setItem(CURRENCY_KEY, init);
  }, []);

  const changeCurrency = (code: Currency["code"]) => {
    setCurrency(code);
    if (typeof window !== "undefined") {
      persistCurrency(code, true);
      window.dispatchEvent(new CustomEvent(CURRENCY_CHANGED_EVENT, { detail: { code } }));
    }
    window.location.reload();
  };

  const display = useMemo(() => {
    const found = CURRENCIES.find(c => c.code === currency) || CURRENCIES[2];
    return `${found.symbol} ${found.code}`;
  }, [currency]);

  return { currency, changeCurrency, currencyDisplay: display };
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

const CurrencyMenu = memo(function CurrencyMenu({
  current,
  onChange,
}: {
  current: Currency["code"];
  onChange: (c: Currency["code"]) => void;
}) {
  return (
    <ul className="flex flex-col py-2 text-sm">
      {CURRENCIES.map(({ code, label }) => (
        <li key={code} className="border-b border-neutral-700 last:border-b-0">
          <Button
            onClick={() => onChange(code)}
            className={clsx(
              "py-4 px-8 w-full text-left transition-all duration-300 hover:bg-neutral-800",
              current === code && "bg-neutral-700"
            )}
          >
            {label}
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
function MobileNav({
  className,
  onNavigate,
  changeLanguage,
  currentLang,
  currency,
  changeCurrency,
}: any) {
  const { isActive, anyActive } = useActive();
  const { t } = useTranslation('home');

  const linkCls = (href: string, exact = false) =>
    clsx(
      "block rounded-xl px-4 py-3 hover:bg-neutral-800 transition-colors",
      isActive(href, exact) ? "bg-neutral-700 text-white" : "text-neutral-200"
    );

  const btnCls = (active: boolean) =>
    clsx("text-left block px-4 py-3 hover:bg-neutral-800 rounded-xl", active && "bg-neutral-700");

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

        <li className="mt-2">
          <div className="px-4 pb-1 text-xs uppercase tracking-wide text-neutral-400">{t("nav.currency")}</div>
          <div className="flex flex-col">
            {CURRENCIES.map(({ code, label }) => (
              <button key={code} onClick={() => changeCurrency(code)} className={btnCls(currency === code)}>
                {label}
              </button>
            ))}
          </div>
        </li>

        <li className="mt-2">
          <div className="px-4 pb-1 text-xs uppercase tracking-wide text-neutral-400">{t('nav.language')}</div>
          <div className="flex flex-col">
            {LANGUAGES.map(({ code, label, icon }) => (
              <button
                key={code}
                onClick={() => changeLanguage(code)}
                className={clsx(
                  "flex items-center gap-2 text-left px-4 py-3 hover:bg-neutral-800 rounded-xl",
                  currentLang === code && "bg-neutral-700"
                )}
              >
                <img src={icon} alt={label} className="h-4 w-6 object-cover rounded-[2px]" />
                <span>{label}</span>
              </button>
            ))}
          </div>
        </li>
      </ul>
    </nav>
  );
}

/* ---------- Desktop ---------- */
function PCNav({
  className,
  onNavigate,
  t,
  changeLanguage,
  currentLang,
  currencyDisplay,
  currency,
  changeCurrency,
}: any) {
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

        <li className="py-3 uppercase font-bold">
          <DropDownHovered handleText={<span className="flex items-center gap-1">{currencyDisplay}</span>}>
            <CurrencyMenu current={currency} onChange={changeCurrency} />
          </DropDownHovered>
        </li>
      </ul>
    </nav>
  );
}

export default function Nav({ variant = "desktop", className, onNavigate }: Props) {
  const { t } = useTranslation("home");
  const { currentLang, changeLanguage } = useLocale();
  const { currency, changeCurrency, currencyDisplay } = useCurrency();

  if (variant === "mobile") {
    return (
      <MobileNav
        className={className}
        onNavigate={onNavigate}
        t={t}
        changeLanguage={changeLanguage}
        currentLang={currentLang}
        currency={currency}
        changeCurrency={changeCurrency}
      />
    );
  }

  return (
    <PCNav
      className={className}
      onNavigate={onNavigate}
      t={t}
      changeLanguage={changeLanguage}
      currentLang={currentLang}
      currencyDisplay={currencyDisplay}
      currency={currency}
      changeCurrency={changeCurrency}
    />
  );
}

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
// Состав меню — lib/nav/menu.ts (общий с подвалом и оболочками студий).
// Шапка по решению клиента 16.11.2026: Главная · Студии ▾ · Инструменты ▾ ·
// Тарифы · Блог · Креаторы · язык. «О нас», «Контакты», «Помощь», «Условия»
// ушли из шапки компьютера в подвал; в мобильном меню они остаются.
import { STUDIOS, TOOLS, MAIN_TAIL, COMPANY, LEGAL, pathOf, type MenuItem } from "@/lib/nav/menu";
import { CREATIVE_PATH } from "@/lib/nav/paths";

// /creative есть и в «Студиях», и в «Инструментах» (категории). Подсвечиваем
// только «Студии», иначе на странице Creative Studio горели оба пункта.
const TOOLS_ACTIVE = TOOLS.filter((i) => pathOf(i.href) !== CREATIVE_PATH);

type Variant = "desktop" | "mobile";
type Props = { variant?: Variant; className?: string; onNavigate?: () => void };

type Lang = { code: "ru" | "en" | "kg"; icon: string; label: string };

const LANGUAGES: Lang[] = [
  { code: "ru", icon: "/images/local/ru.webp", label: "Русский" },
  { code: "en", icon: "/images/local/en.webp", label: "English" },
  { code: "kg", icon: "/images/local/kg.webp", label: "Кыргызча" },
];

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
            aria-current={currentLang === code ? "true" : undefined}
            className={clsx(
              "py-4 px-8 w-full text-left flex items-center gap-2 transition-all duration-300 hover:bg-surface-2",
              currentLang === code && "bg-surface-3"
            )}
          >
            <img src={icon} alt="" className="min-w-4 h-4 w-6 object-cover rounded-[2px]" />
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
  const isActive = (href: string, exact = false) => {
    const h = pathOf(href);
    return exact ? pathname === h : pathname === h || pathname.startsWith(h + "/");
  };
  const anyActive = (items: MenuItem[]) => items.some((i) => isActive(i.href));
  return { pathname, isActive, anyActive };
}

function useLabel() {
  const { t } = useTranslation("home");
  return (i: MenuItem) => t(i.label, { ns: i.ns || "home", defaultValue: i.fallback });
}

/* ---------- Mobile ---------- */
// Только навигация: язык вынесен в шапку (LangSwitch). Группы с подзаголовками,
// чтобы длинный список читался.
function MobileNav({ className, onNavigate }: { className?: string; onNavigate?: () => void }) {
  const { isActive } = useActive();
  const { t } = useTranslation("home");
  const label = useLabel();

  const linkCls = (href: string, exact = false) =>
    clsx(
      "block rounded-xl px-4 py-3 hover:bg-surface-2 transition-colors",
      isActive(href, exact) ? "bg-surface-3 text-foreground" : "text-muted"
    );

  const item = (i: MenuItem, exact = false) => (
    <li key={i.href + i.label}>
      <Link
        href={i.href}
        prefetch={i.prefetch}
        onClick={onNavigate}
        className={linkCls(i.href, exact)}
        aria-current={isActive(i.href, exact) ? "page" : undefined}
      >
        {label(i)}
      </Link>
    </li>
  );

  const group = (title: string, items: MenuItem[]) => (
    <li className="mt-2">
      <div className="px-4 pb-1 text-xs uppercase tracking-wide text-muted">{title}</div>
      <ul className="flex flex-col">{items.map((i) => item(i))}</ul>
    </li>
  );

  return (
    <nav className={clsx("text-foreground", className)}>
      <ul className="flex flex-col gap-1">
        {item({ href: "/", label: "nav.home", fallback: "Главная" }, true)}
        {group(t("nav.studios", { defaultValue: "Студии" }), STUDIOS)}
        {group(t("nav.tools", { defaultValue: "Инструменты" }), TOOLS)}
        <li className="mt-2">
          <ul className="flex flex-col">{MAIN_TAIL.map((i) => item(i))}</ul>
        </li>
        {group(t("nav.more", { defaultValue: "Ещё" }), [...COMPANY, LEGAL[0]])}
      </ul>
    </nav>
  );
}

/* ---------- Desktop ---------- */
type PCProps = {
  className?: string;
  onNavigate?: () => void;
  t: (k: string, o?: Record<string, unknown>) => string;
  changeLanguage: (code: string) => void;
  currentLang: string;
};

function PCNav({ className, onNavigate, t, changeLanguage, currentLang }: PCProps) {
  const { isActive, anyActive } = useActive();
  const label = useLabel();

  const linkCls = (active: boolean) =>
    clsx("py-3 relative", active ? "text-foreground" : "text-muted", "hover:text-foreground");

  const linkInner = (active: boolean) =>
    clsx(
      "inline-block",
      active && "after:content-[''] after:block after:h-[2px] after:bg-[#F5C518] after:rounded-full after:mt-1"
    );

  // Имя переключателя языка для экранного диктора — на самом языке, без перевода.
  const LANG_NAME: Record<string, string> = { ru: "Русский", en: "English", kg: "Кыргызча" };

  const dropdown = (title: string, items: MenuItem[], activeBy: MenuItem[] = items) => {
    const active = anyActive(activeBy);
    return (
      <li className={linkCls(active)}>
        <DropDownHovered
          handleText={
            <span className={linkInner(active)} aria-current={active ? "page" : undefined}>
              {title}
            </span>
          }
        >
          <ul className="flex flex-col text-sm py-2 min-w-56">
            {items.map((i, n) => (
              <li key={i.href + i.label} className={clsx(n < items.length - 1 && "border-b border-neutral-700")}>
                <Link
                  href={i.href}
                  prefetch={i.prefetch}
                  onClick={onNavigate}
                  className="py-3.5 px-8 hover:bg-surface-2 transition-all duration-300 flex w-full"
                >
                  {label(i)}
                </Link>
              </li>
            ))}
          </ul>
        </DropDownHovered>
      </li>
    );
  };

  const plain = (i: MenuItem, exact = false) => {
    const active = isActive(i.href, exact);
    return (
      <li key={i.href + i.label} className={linkCls(active)}>
        <Link href={i.href} prefetch={i.prefetch} onClick={onNavigate} className={linkInner(active)} aria-current={active ? "page" : undefined}>
          {label(i)}
        </Link>
      </li>
    );
  };

  return (
    <nav className={clsx("bg-surface px-3 xl:px-6 rounded-4xl flex items-center shadow-md", className)}>
      {/* Ниже xl ряд плотнее: у вошедшего по-кыргызски шапка тесная на 1024 px.
          nowrap — чтобы пункт не ломался на две строки. */}
      <ul className="flex items-center gap-2 min-[1100px]:gap-3 xl:gap-5 2xl:gap-8 text-sm xl:text-base whitespace-nowrap">
        {plain({ href: "/", label: "nav.home", fallback: "Главная" }, true)}
        {dropdown(t("nav.studios", { defaultValue: "Студии" }), STUDIOS)}
        {dropdown(t("nav.tools", { defaultValue: "Инструменты" }), TOOLS, TOOLS_ACTIVE)}
        {MAIN_TAIL.map((i) => plain(i))}

        <li className="py-3">
          <DropDownHovered
            handleText={
              <span className="flex items-center gap-1">
                <img src={`/images/local/${currentLang}.webp`} alt={LANG_NAME[currentLang] ?? currentLang} />
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

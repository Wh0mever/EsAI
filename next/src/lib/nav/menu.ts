// Состав меню сайта — одно место для шапки (компьютер и телефон), подвала
// и переключателя разделов в оболочках студий. Раньше пункты были вписаны в
// Nav.tsx и Footer.tsx по отдельности и расходились.
//
// Подписи — ключи пространства `home` (locales/*/home.json, раздел nav).
// Флаги вшиваются при сборке (Dockerfile ARG + compose build args):
//   NEXT_PUBLIC_VSTUDIO_NAV  — Видеостудия открыта всем;
//   NEXT_PUBLIC_CREATIVE_NAV — Creative Studio открыта всем;
//   NEXT_PUBLIC_CREATORS_NAV — программа Creators открыта всем.
import { CREATORS_NAV } from "@/lib/creators/format";
import { CHAT_PATH, CREATIVE_PATH } from "./paths";

export const VSTUDIO_NAV = process.env.NEXT_PUBLIC_VSTUDIO_NAV === "1";
export const CREATIVE_NAV = process.env.NEXT_PUBLIC_CREATIVE_NAV === "1";

export type MenuItem = {
  href: string;
  /** ключ в пространстве home */
  label: string;
  /** запасная подпись, если перевод ещё не загрузился */
  fallback: string;
  /** пространство имён, если не home */
  ns?: string;
  prefetch?: boolean;
};

/** Категории Creative Studio: адрес-фильтр `/creative?cat=<id>`. */
export const CREATIVE_CATEGORIES = [
  { id: "video", label: "nav.cat_video", fallback: "Видео и движение" },
  { id: "image", label: "nav.cat_image", fallback: "Изображения" },
  { id: "characters", label: "nav.cat_characters", fallback: "AI-персонажи" },
  { id: "ads", label: "nav.cat_ads", fallback: "Реклама и маркетинг" },
] as const;

export type CreativeCategory = (typeof CREATIVE_CATEGORIES)[number]["id"];

const on = <T,>(flag: boolean, items: T[]): T[] => (flag ? items : []);

export const STUDIOS: MenuItem[] = [
  { href: "/studio", label: "nav.cartoon", fallback: "Мультстудия" },
  ...on(VSTUDIO_NAV, [{ href: "/video-studio", label: "nav.vstudio", fallback: "Видеостудия" }]),
  ...on(CREATIVE_NAV, [{ href: CREATIVE_PATH, label: "nav.creative", fallback: "Creative Studio" }]),
  { href: "/merge", label: "nav.merge_full", fallback: "Склейка видео", prefetch: false },
];

export const TOOLS: MenuItem[] = [
  { href: CHAT_PATH, label: "nav.chat", fallback: "Чаты ИИ" },
  ...on(
    CREATIVE_NAV,
    CREATIVE_CATEGORIES.map((c) => ({ href: `${CREATIVE_PATH}?cat=${c.id}`, label: c.label, fallback: c.fallback })),
  ),
  ...on(CREATIVE_NAV, [{ href: CREATIVE_PATH, label: "nav.all_tools", fallback: "Все 15 инструментов" }]),
  { href: "/models", label: "nav.models", fallback: "Модели" },
  { href: "/academy", label: "nav.academy", fallback: "EsAI Академия" },
];

/** Пункты верхнего ряда после «Студии» и «Инструменты». */
export const MAIN_TAIL: MenuItem[] = [
  { href: "/pricing", label: "nav.tariffs", fallback: "Тарифы" },
  { href: "/blog", label: "nav.blog", fallback: "Блог" },
  ...on(CREATORS_NAV, [{ href: "/creators", label: "nav.creators", fallback: "Креаторы" }]),
];

/** Ушло из шапки компьютера (решение клиента 16.11): подвал и мобильное меню. */
export const COMPANY: MenuItem[] = [
  { href: "/about", label: "nav.about", fallback: "О нас" },
  { href: "/referral", label: "nav.referral", fallback: "Реферальная программа" },
  { href: "/contact-us", label: "nav.contact", fallback: "Контакты" },
  { href: "/faq", label: "nav.help", fallback: "Помощь" },
];

export const LEGAL: MenuItem[] = [
  { href: "/terms-conditions", label: "nav.terms", fallback: "Условия и положения" },
  { href: "/privacy", label: "nav.privacy", fallback: "Политика конфиденциальности" },
  { href: "/public-offer", label: "nav.offer", fallback: "Оферта" },
];

/** Путь без строки запроса — для подсветки активного пункта. */
export const pathOf = (href: string) => href.split("?")[0];

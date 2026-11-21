"use client";

import clsx from "clsx";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import { FaFilm, FaImage, FaUser, FaBullhorn, FaTableCellsLarge } from "react-icons/fa6";
import { CREATIVE_TOOLS, isCategory } from "@/lib/creative/tools";
import { CREATIVE_CATEGORIES, type CreativeCategory } from "@/lib/nav/menu";
import ToolCard from "./ToolCard";
import CreativeExamples from "./CreativeExamples";

const CAT_ICON: Record<CreativeCategory, typeof FaFilm> = {
  video: FaFilm,
  image: FaImage,
  characters: FaUser,
  ads: FaBullhorn,
};

// Страница Creative Studio по макету 2: плашка, заголовок, подзаголовок,
// пять кнопок фильтра, сетка 15 карточек. Без приветственного экрана.
// Фильтр живёт в адресе (?cat=video) — ссылки из меню «Инструменты» ведут
// сразу на нужную категорию, а «назад» в браузере возвращает прежний фильтр.
export default function CreativeCatalog() {
  const { t } = useTranslation("creative");
  const tHome = useTranslation("home").t;
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const raw = params.get("cat");
  const cat: CreativeCategory | null = isCategory(raw) ? raw : null;

  const tools = CREATIVE_TOOLS.filter((x) => !cat || x.cat === cat).sort((a, b) => a.n - b.n);

  const pick = (next: CreativeCategory | null) => {
    const sp = new URLSearchParams(params.toString());
    if (next) sp.set("cat", next);
    else sp.delete("cat");
    const qs = sp.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  };

  const pill = (active: boolean) =>
    clsx(
      "inline-flex shrink-0 items-center gap-2.5 rounded-xl border px-4 py-2.5 text-sm font-medium transition-colors sm:px-5 sm:py-3",
      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F5C518] focus-visible:ring-offset-2 focus-visible:ring-offset-background",
      active
        ? "border-[#F5C518] bg-[#F5C518] text-black"
        : "border-border bg-surface text-foreground hover:border-[#F5C518]/60"
    );

  return (
    <main className="pb-16">
      {/* Первый экран — всегда тёмный: текст лежит на картинке. Картинка — временная
          (обложка Creative Studio с главной); версию без надписей клиент ещё пришлёт. */}
      <section className="relative overflow-hidden bg-neutral-950 text-white">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/images/creative/hero-1280.webp"
          srcSet="/images/creative/hero-640.webp 640w, /images/creative/hero-1280.webp 1280w"
          sizes="(min-width: 768px) 60vw, 100vw"
          alt=""
          fetchPriority="high"
          className="absolute inset-y-0 right-0 h-full w-full object-cover object-[70%_30%] opacity-70 md:w-[62%] md:opacity-100"
        />
        <div className="absolute inset-0 bg-gradient-to-r from-neutral-950 via-neutral-950/85 to-neutral-950/10 md:via-neutral-950/70" />
        <div className="absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-background to-transparent" />
        <div className="relative mx-auto max-w-7xl px-4 pb-10 pt-28 sm:px-6 sm:pt-32 lg:px-8 lg:pb-14">
          <span className="inline-block rounded-full bg-[#F5C518] px-4 py-1.5 text-sm font-semibold text-black">
            {t("page.badge", { defaultValue: "Creative Studio" })}
          </span>
          <h1 className="mt-4 text-3xl font-extrabold leading-tight sm:text-4xl lg:text-5xl">
            {t("page.title_a", { defaultValue: "15 творческих" })}{" "}
            <span className="text-[#F5C518]">{t("page.title_b", { defaultValue: "инструментов" })}</span>
          </h1>
          <p className="mt-3 max-w-xl text-base text-white/80 sm:text-lg">
            {t("page.subtitle", { defaultValue: "Профессиональные AI-инструменты для видео, изображений и рекламы." })}
          </p>
        </div>
      </section>

      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        {/* На телефоне — горизонтальная прокрутка, на компьютере — в ряд. */}
        <div
          role="group"
          aria-label={t("page.filters_label", { defaultValue: "Категории инструментов" })}
          className="-mx-4 flex gap-2.5 overflow-x-auto px-4 py-4 [scrollbar-width:none] sm:mx-0 sm:flex-wrap sm:px-0 sm:gap-3"
        >
          <button type="button" className={pill(!cat)} aria-pressed={!cat} onClick={() => pick(null)}>
            <FaTableCellsLarge aria-hidden="true" />
            {t("page.filter_all", { defaultValue: "Все инструменты" })}
          </button>
          {CREATIVE_CATEGORIES.map((c) => {
            const Icon = CAT_ICON[c.id];
            return (
              <button key={c.id} type="button" className={pill(cat === c.id)} aria-pressed={cat === c.id} onClick={() => pick(c.id)}>
                <Icon aria-hidden="true" />
                {tHome(c.label, { defaultValue: c.fallback })}
              </button>
            );
          })}
        </div>

        {tools.length ? (
          <ul className="grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-3 xl:grid-cols-5">
            {tools.map((tool, i) => (
              <li key={tool.id}>
                <ToolCard tool={tool} priority={i < 5} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="py-16 text-center text-muted">{t("page.empty", { defaultValue: "В этой категории пока нет инструментов." })}</p>
        )}

        <CreativeExamples />
      </div>
    </main>
  );
}

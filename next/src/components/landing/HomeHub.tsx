"use client";

import Link from "next/link";
import clsx from "clsx";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  FaArrowRight,
  FaPlay,
  FaCheck,
  FaClapperboard,
  FaVideo,
  FaWandMagicSparkles,
  FaComments,
  FaLayerGroup,
  FaBolt,
  FaChevronRight,
  FaCubes,
  FaGraduationCap,
  FaTags,
  FaUserGroup,
  FaNewspaper,
  FaStar,
} from "react-icons/fa6";
import { ensureAccess, fetchData } from "@/tools/fetchData";
import { CHAT_PATH, CREATIVE_PATH } from "@/lib/nav/paths";
import { CREATIVE_NAV, VSTUDIO_NAV } from "@/lib/nav/menu";
import { CREATORS_NAV } from "@/lib/creators/format";
import { HAS_EXAMPLES } from "@/lib/creative/examples";

// Новая главная — центральная страница платформы (решение клиента 16.11.2026):
// открывается у всех (гость, вошедший, установленное приложение), никого не
// перенаправляет в чат, даёт переходы во все разделы. Вошедший видит баланс.
//
// Пока живёт на /home-preview (этап A4). Замена «/» — этап A6, только по слову
// Шохруха.
//
// Картинки — от клиента (без надписей, текст накладываем кодом, чтобы работали
// три языка). Для «Чатов ИИ» и «Склейки видео» обложек ещё нет — заглушки.

type Me = { token_balance?: number | string; is_unlimited?: boolean } | null;

function useMe() {
  const [authed, setAuthed] = useState(false);
  const [me, setMe] = useState<Me>(null);
  useEffect(() => {
    let alive = true;
    // Тот же путь, что у шапки (AuthButtons) и боковой панели чата: проверка
    // входа и профиль. Сессию не трогаем — только читаем.
    ensureAccess().then((ok) => {
      if (!alive) return;
      setAuthed(ok);
      if (!ok) return;
      fetchData<{ user?: Me }>("users/profile/", "get", null, true)
        .then((r) => alive && setMe(r?.data?.user || null))
        .catch(() => {});
    });
    return () => {
      alive = false;
    };
  }, []);
  return { authed, me };
}

const GOLD = "#F5C518";

type Dir = {
  key: string;
  href: string;
  title: string;
  titleRu: string;
  desc: string;
  descRu: string;
  Icon: typeof FaVideo;
  img?: { src: string; srcSet: string; pos: string };
  soon?: boolean;
  prefetch?: boolean;
};

export default function HomeHub() {
  const { t } = useTranslation("creative");
  const tHome = useTranslation("home").t;
  const { authed, me } = useMe();

  const examplesHref = HAS_EXAMPLES ? `${CREATIVE_PATH}#examples` : CREATIVE_PATH;
  const balance = me ? (me.is_unlimited ? "∞" : Number(me.token_balance ?? 0).toLocaleString("ru-RU")) : null;

  const dirs: Dir[] = [
    {
      key: "cartoon", href: "/studio", title: "hub.dir_cartoon", titleRu: "Мультстудия",
      desc: "hub.dir_cartoon_desc", descRu: "Создавай мультфильмы с помощью ИИ", Icon: FaClapperboard,
      img: { src: "/images/home/dir-cartoon-960.webp", srcSet: "/images/home/dir-cartoon-480.webp 480w, /images/home/dir-cartoon-960.webp 960w", pos: "38% 30%" },
    },
    ...(VSTUDIO_NAV
      ? [{
          key: "video", href: "/video-studio", title: "hub.dir_video", titleRu: "Видеостудия",
          desc: "hub.dir_video_desc", descRu: "Генерация AI-видео из текста, фото и идей", Icon: FaVideo,
          img: { src: "/images/home/dir-video-960.webp", srcSet: "/images/home/dir-video-480.webp 480w, /images/home/dir-video-960.webp 960w", pos: "72% 25%" },
        } as Dir]
      : []),
    {
      key: "creative", href: CREATIVE_PATH, title: "hub.dir_creative", titleRu: "Creative Studio",
      desc: "hub.dir_creative_desc", descRu: "15 творческих инструментов", Icon: FaWandMagicSparkles,
      img: { src: "/images/home/dir-creative-960.webp", srcSet: "/images/home/dir-creative-480.webp 480w, /images/home/dir-creative-960.webp 960w", pos: "58% 25%" },
      soon: !CREATIVE_NAV,
    },
    {
      key: "chat", href: CHAT_PATH, title: "hub.dir_chat", titleRu: "Чаты ИИ",
      desc: "hub.dir_chat_desc", descRu: "ChatGPT, Claude, Gemini и другие", Icon: FaComments,
    },
    {
      key: "merge", href: "/merge", title: "hub.dir_merge", titleRu: "Склейка видео",
      desc: "hub.dir_merge_desc", descRu: "Собери ролик из готовых клипов", Icon: FaLayerGroup, prefetch: false,
    },
  ];

  const others = [
    { href: "/models", label: tHome("nav.models", { defaultValue: "Модели" }), Icon: FaCubes },
    { href: "/academy", label: tHome("nav.academy", { defaultValue: "EsAI Академия" }), Icon: FaGraduationCap },
    { href: "/pricing", label: tHome("nav.tariffs", { defaultValue: "Тарифы" }), Icon: FaTags },
    { href: "/referral", label: tHome("nav.referral", { defaultValue: "Реферальная программа" }), Icon: FaUserGroup },
    ...(CREATORS_NAV ? [{ href: "/creators", label: tHome("nav.creators", { defaultValue: "Креаторы" }), Icon: FaStar }] : []),
    { href: "/blog", label: tHome("nav.blog", { defaultValue: "Блог" }), Icon: FaNewspaper },
  ];

  const btn = "inline-flex items-center justify-center gap-2.5 rounded-full px-6 py-3.5 text-[15px] font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-neutral-950";

  return (
    <main className="pb-16">
      {/* ---------- Первый экран (всегда тёмный: текст на картинке) ---------- */}
      <section className="relative overflow-hidden bg-neutral-950 text-white">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/images/home/hero-cat-1536.webp"
          srcSet="/images/home/hero-cat-768.webp 768w, /images/home/hero-cat-1536.webp 1536w"
          sizes="(min-width: 768px) 100vw, 100vw"
          alt=""
          fetchPriority="high"
          className="absolute inset-x-0 top-0 h-[440px] w-full object-cover object-[78%_20%] md:inset-0 md:h-full md:object-[70%_30%]"
        />
        {/* Телефон: картинка сверху, текст снизу на тёмном. Компьютер: текст слева. */}
        <div className="absolute inset-x-0 top-0 h-[440px] bg-gradient-to-b from-transparent from-40% to-neutral-950 md:inset-0 md:h-full md:bg-gradient-to-r md:from-neutral-950/90 md:from-0% md:via-neutral-950/45 md:to-transparent" />
        <div className="absolute inset-x-0 bottom-0 h-20 bg-gradient-to-t from-background to-transparent" />

        <div className="relative mx-auto flex max-w-7xl flex-col justify-end px-4 pb-12 pt-[330px] sm:px-6 md:min-h-[600px] md:justify-center md:pb-20 md:pt-32 lg:px-8 xl:min-h-[680px]">
          <div className="max-w-xl">
            <h1 className="text-[34px] font-extrabold leading-[1.08] tracking-tight sm:text-5xl xl:text-6xl">
              {t("hub.title_a", { defaultValue: "Всё для творчества" })}
              <br />
              {t("hub.title_b", { defaultValue: "и работы" })}{" "}
              <span style={{ color: GOLD }}>{t("hub.title_c", { defaultValue: "с ИИ" })}</span>
            </h1>
            <p className="mt-4 max-w-md text-base text-white/85 sm:text-lg">
              {t("hub.subtitle", { defaultValue: "Видео, мультфильмы, изображения и умные AI-инструменты в одном месте." })}
            </p>

            {authed ? (
              <div className="mt-7 flex flex-wrap items-center gap-3">
                <Link
                  href="/pricing"
                  className="inline-flex items-center gap-3 rounded-full border border-white/20 bg-black/40 py-2 pl-5 pr-2 backdrop-blur hover:border-white/40"
                >
                  <span className="text-sm text-white/70">{t("hub.balance", { defaultValue: "Ваш баланс" })}</span>
                  <span className="text-lg font-bold tabular-nums" style={{ color: GOLD }}>
                    {balance ?? "…"} <span className="text-sm font-semibold">{t("hub.credits", { defaultValue: "кр" })}</span>
                  </span>
                  <span className="rounded-full px-3 py-1.5 text-sm font-semibold text-black" style={{ background: GOLD }}>
                    {t("hub.topup", { defaultValue: "Пополнить" })}
                  </span>
                </Link>
                <Link href={CHAT_PATH} className={clsx(btn, "border border-white/60 text-white hover:bg-white/10 focus-visible:ring-white")}>
                  <FaComments aria-hidden="true" />
                  {t("hub.open_chat", { defaultValue: "Открыть чат" })}
                </Link>
              </div>
            ) : (
              <div className="mt-7 flex flex-wrap items-center gap-3">
                <Link href="/auth/signin" className={clsx(btn, "text-black hover:brightness-95 focus-visible:ring-[#F5C518]")} style={{ background: GOLD }}>
                  {t("hub.start", { defaultValue: "Начать бесплатно" })}
                  <FaArrowRight aria-hidden="true" />
                </Link>
                <Link href={examplesHref} className={clsx(btn, "border border-white/60 text-white hover:bg-white/10 focus-visible:ring-white")}>
                  <FaPlay aria-hidden="true" className="size-3" />
                  {t("hub.examples", { defaultValue: "Посмотреть примеры" })}
                </Link>
              </div>
            )}

            <ul className="mt-7 flex flex-wrap gap-x-6 gap-y-2.5 text-sm text-white/90">
              {[
                ["hub.check_balance", "Единый баланс"],
                ["hub.check_models", "Несколько AI-моделей"],
                ["hub.check_vpn", "Без VPN"],
              ].map(([k, d]) => (
                <li key={k} className="flex items-center gap-2">
                  <span className="grid size-5 place-items-center rounded-full text-black" style={{ background: GOLD }}>
                    <FaCheck aria-hidden="true" className="size-2.5" />
                  </span>
                  {t(k, { defaultValue: d })}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        {/* ---------- Основные направления ---------- */}
        <section className="pt-6 md:pt-10">
          <h2 className="text-2xl font-extrabold sm:text-3xl">{t("hub.directions", { defaultValue: "Основные направления" })}</h2>
          <ul className="mt-5 grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-3 lg:grid-cols-5">
            {dirs.map((d, i) => (
              <li key={d.key} className={clsx(i === dirs.length - 1 && dirs.length % 2 === 1 && "col-span-2 md:col-span-1")}>
                <DirCard d={d} t={t} wide={i === dirs.length - 1 && dirs.length % 2 === 1} />
              </li>
            ))}
          </ul>
        </section>

        {/* ---------- Другие инструменты ---------- */}
        <section className="pt-10">
          <h2 className="text-lg font-bold sm:text-xl">{t("hub.other_tools", { defaultValue: "Другие инструменты" })}</h2>
          <ul className="mt-4 flex flex-wrap gap-2.5">
            {others.map((o) => (
              <li key={o.href}>
                <Link
                  href={o.href}
                  className="inline-flex items-center gap-2 rounded-xl border border-border bg-surface px-4 py-2.5 text-sm text-foreground transition-colors hover:border-[#F5C518]/60"
                >
                  <o.Icon aria-hidden="true" className="text-[#F5C518]" />
                  {o.label}
                </Link>
              </li>
            ))}
          </ul>
        </section>

        {/* ---------- «Попробуй EsAI уже сегодня» — только гостям ---------- */}
        {!authed && (
          <section className="pt-12">
            <div className="relative overflow-hidden rounded-3xl border border-[#F5C518]/40 bg-neutral-950 px-6 py-8 text-white sm:px-10 sm:py-10">
              {/* Золотые волны — кодом: картинка клиента была с русским текстом внутри. */}
              <div
                aria-hidden="true"
                className="pointer-events-none absolute inset-0"
                style={{
                  background:
                    "radial-gradient(60% 120% at 85% 120%, rgba(245,197,24,0.45) 0%, rgba(245,197,24,0) 60%), radial-gradient(40% 80% at 100% 0%, rgba(245,197,24,0.25) 0%, rgba(245,197,24,0) 70%)",
                }}
              />
              <svg aria-hidden="true" viewBox="0 0 800 200" preserveAspectRatio="none" className="pointer-events-none absolute inset-x-0 bottom-0 h-24 w-full opacity-70">
                <path d="M0 160 C 200 120, 380 200, 560 130 S 760 60, 800 80" fill="none" stroke={GOLD} strokeWidth="2" />
                <path d="M0 180 C 220 150, 420 210, 600 150 S 770 100, 800 110" fill="none" stroke={GOLD} strokeOpacity="0.5" strokeWidth="1.5" />
              </svg>
              <div className="relative flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
                <div className="flex items-start gap-4">
                  <FaBolt aria-hidden="true" className="mt-1 size-9 shrink-0" style={{ color: GOLD }} />
                  <div>
                    <p className="text-2xl font-extrabold sm:text-3xl">{t("hub.cta_title", { defaultValue: "Попробуй EsAI уже сегодня" })}</p>
                    <p className="mt-1.5 text-white/80">{t("hub.cta_text", { defaultValue: "Создавай, экспериментируй и воплощай идеи с ИИ" })}</p>
                  </div>
                </div>
                <Link href="/auth/signin" className={clsx(btn, "shrink-0 text-black hover:brightness-95 focus-visible:ring-[#F5C518]")} style={{ background: GOLD }}>
                  {t("hub.cta_button", { defaultValue: "Создать аккаунт" })}
                  <FaArrowRight aria-hidden="true" />
                </Link>
              </div>
            </div>
          </section>
        )}
      </div>
    </main>
  );
}

// wide — последняя карточка при нечётном числе: на телефоне на всю ширину,
// поэтому низкая (2:1), иначе она одна занимала бы полэкрана.
function DirCard({ d, t, wide = false }: { d: Dir; t: (k: string, o?: Record<string, unknown>) => string; wide?: boolean }) {
  return (
    <Link
      href={d.href}
      prefetch={d.prefetch}
      className={clsx(
        "group relative flex flex-col overflow-hidden rounded-2xl border border-white/10 bg-neutral-950 text-white",
        wide ? "aspect-[2/1] md:aspect-[4/5]" : "aspect-[4/5]",
        "transition duration-300 hover:-translate-y-0.5 hover:border-[#F5C518]/60 hover:shadow-[0_8px_30px_-12px_rgba(245,197,24,0.45)]",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#F5C518] focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      )}
    >
      {d.img ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={d.img.src}
          srcSet={d.img.srcSet}
          sizes="(min-width: 1024px) 20vw, (min-width: 768px) 33vw, 50vw"
          alt=""
          loading="lazy"
          decoding="async"
          className="absolute inset-0 size-full object-cover transition-transform duration-500 group-hover:scale-[1.04]"
          style={{ objectPosition: d.img.pos }}
        />
      ) : (
        // Обложки нет — заглушка в общем стиле (клиент пришлёт картинку).
        <span
          aria-hidden="true"
          className="absolute inset-0 grid place-items-center"
          style={{ background: "radial-gradient(110% 80% at 50% 10%, #3a2a05 0%, #0b0b0d 70%)" }}
        >
          <d.Icon className="mb-16 size-14 text-[#F5C518]/40 transition-transform duration-500 group-hover:scale-110" />
        </span>
      )}

      {d.soon && (
        <span className="absolute right-3 top-3 rounded-full bg-black/60 px-2.5 py-1 text-[11px] font-medium text-white/85 backdrop-blur">
          {t("page.soon", { defaultValue: "Скоро" })}
        </span>
      )}

      <span className="relative mt-auto flex items-end gap-2 bg-gradient-to-t from-black via-black/85 to-transparent px-3.5 pb-3.5 pt-12">
        <span className="min-w-0 flex-1">
          <d.Icon aria-hidden="true" className="mb-2 size-5" style={{ color: GOLD }} />
          <span className="block text-base font-bold leading-tight sm:text-lg">{t(d.title, { defaultValue: d.titleRu })}</span>
          <span className="mt-1 line-clamp-2 block text-xs leading-snug text-white/75 sm:text-[13px]">{t(d.desc, { defaultValue: d.descRu })}</span>
        </span>
        <span aria-hidden="true" className="grid size-7 shrink-0 place-items-center rounded-full text-black transition-transform duration-300 group-hover:translate-x-0.5" style={{ background: GOLD }}>
          <FaChevronRight className="size-3" />
        </span>
      </span>
    </Link>
  );
}

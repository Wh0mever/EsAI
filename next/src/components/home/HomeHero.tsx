"use client";

import Link from "next/link";
import { useTranslation } from "react-i18next";
import { FiArrowRight } from "react-icons/fi";
import { vendorColor } from "@/lib/vendorColors";

/**
 * HomeHero — блок 1 из 8 в новой структуре главной страницы (первый экран).
 * Текст ДОСЛОВНО из ТЗ клиента: заголовок, подзаголовок, кнопка «Начать
 * бесплатно». В EsAI нет отдельной формы регистрации — аккаунт создаётся
 * автоматически при первом входе через email-OTP или соц-кнопки на
 * /auth/signin (next/src/app/auth/signup/page.tsx лишь редиректит туда же;
 * next/src/components/chat/ChatWorkspace.tsx использует тот же href для
 * гостевой ссылки «Войти»). Тот же href уже используется в
 * home/HomeFinalCTA.tsx — конечный экран с тем же CTA.
 *
 * Статичен (кроме i18n), поэтому не тянет данные с бэка — но помечён
 * "use client", потому что useTranslation требует клиентского рендера
 * (см. Footer.tsx / home/WhyEsAI.tsx — тот же паттерн в этом кодбейзе).
 *
 * Ряд вендорских «wordmark-чипов» под подзаголовком — НЕ логотипы-картинки
 * (запрещено политикой без явного разрешения скачивать сторонние ассеты),
 * а текстовые чипы, окрашенные в брендовый цвет вендора (текст + мягкий
 * тон фона/рамки того же цвета). Цвета берутся из общего
 * next/src/lib/vendorColors.ts — единого источника палитры вендоров в этом
 * проекте (используется здесь, в PopularModels.tsx и в
 * pricing/CreditsExplainer.tsx). Veo (Google) и Sora (OpenAI) — суб-продукты,
 * поэтому переиспользуют цвет материнского вендора. FLUX (Black Forest Labs)
 * и Kling (Kuaishou) — отдельные ключи в том же модуле.
 *
 * Визуальный язык — как в остальных home/* блоках и pricing/CreditsExplainer.tsx:
 * rounded-2xl/full, border-border, bg-surface-2, text-muted, bg-accent/text-on-accent.
 *
 * HomeHero рендерится ВНУТРИ ChatWorkspace (через heroSlot, см.
 * app/(home)/page.tsx и ChatWorkspace.tsx) — сразу под шапкой чата, которая
 * уже сама учитывает safe-area-inset-top (статус-бар iOS PWA), поэтому здесь
 * доп. safe-area отступ не нужен (не первая секция экрана).
 */

type VendorChip = {
  key: string;
  labelKey: string;
  labelDefault: string;
  color: string;
};

const VENDOR_CHIPS: VendorChip[] = [
  { key: "chatgpt", labelKey: "home.hero.chips.chatgpt", labelDefault: "ChatGPT", color: vendorColor("openai") },
  { key: "claude", labelKey: "home.hero.chips.claude", labelDefault: "Claude", color: vendorColor("anthropic") },
  { key: "gemini", labelKey: "home.hero.chips.gemini", labelDefault: "Gemini", color: vendorColor("google") },
  { key: "grok", labelKey: "home.hero.chips.grok", labelDefault: "Grok", color: vendorColor("x-ai") },
  { key: "deepseek", labelKey: "home.hero.chips.deepseek", labelDefault: "DeepSeek", color: vendorColor("deepseek") },
  { key: "veo", labelKey: "home.hero.chips.veo", labelDefault: "Veo", color: vendorColor("google") },
  { key: "sora", labelKey: "home.hero.chips.sora", labelDefault: "Sora", color: vendorColor("openai") },
  { key: "flux", labelKey: "home.hero.chips.flux", labelDefault: "FLUX", color: vendorColor("flux") },
  { key: "kling", labelKey: "home.hero.chips.kling", labelDefault: "Kling", color: vendorColor("kling") },
];

export default function HomeHero() {
  const { t } = useTranslation("common");

  return (
    <section
      aria-label={t("home.hero.title", { defaultValue: "Все лучшие нейросети мира в одном месте" })}
      className="relative w-full overflow-hidden bg-background"
    >
      {/* Декоративное свечение брендовым акцентом — без новых цветовых токенов (тот же приём, что в home/HomeFinalCTA.tsx). Absolute-позиционировано, на высоту блока не влияет, но уменьшено для менее «раздутого» визуального веса первого экрана. */}
      <div aria-hidden className="pointer-events-none absolute inset-x-0 -top-40 flex justify-center">
        <div className="h-56 w-[34rem] rounded-full bg-accent/20 blur-3xl" />
      </div>

      <div className="relative mx-auto flex max-w-4xl flex-col items-center gap-3 px-4 pt-6 pb-6 text-center sm:gap-4 sm:px-6 sm:pt-8 sm:pb-8 lg:pt-10 lg:pb-10">
        <h1 className="max-w-3xl text-2xl font-bold leading-[1.15] tracking-tight text-foreground sm:text-3xl lg:text-4xl">
          {t("home.hero.title", { defaultValue: "Все лучшие нейросети мира в одном месте" })}
          <br />
          <span className="text-accent">
            {t("home.hero.tagline", { defaultValue: "Без лишних трат и подписок." })}
          </span>
        </h1>

        <p className="max-w-2xl text-xs leading-snug text-muted sm:text-sm lg:text-base">
          {t("home.hero.subtitle", {
            defaultValue:
              "Используйте ChatGPT, Claude, Gemini, Grok, DeepSeek, Veo, Sora, FLUX, Kling и десятки других моделей в одном аккаунте.",
          })}
        </p>

        <Link
          href="/auth/signin"
          className="mt-1 inline-flex items-center gap-2 rounded-full bg-accent px-6 py-2.5 text-base font-semibold text-on-accent transition-colors hover:bg-accent-strong sm:text-lg"
        >
          {t("home.hero.cta", { defaultValue: "Начать бесплатно" })}
          <FiArrowRight aria-hidden />
        </Link>

        {/* Вендорские wordmark-чипы — текст, без сторонних логотипов-картинок. */}
        <ul className="mt-1 flex flex-wrap items-center justify-center gap-1.5">
          {VENDOR_CHIPS.map((chip) => (
            <li
              key={chip.key}
              className="rounded-full border px-2.5 py-1 text-xs font-semibold"
              style={{
                color: chip.color,
                borderColor: `${chip.color}33`,
                background: `${chip.color}14`,
              }}
            >
              {t(chip.labelKey, { defaultValue: chip.labelDefault })}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

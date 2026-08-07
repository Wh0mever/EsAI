'use client';
import TextSlider from "@/components/ui/sliders/TextSlider";
import { useTranslation } from "react-i18next";
import EsaiLogo from "@/components/brand/EsaiLogo";

export default function AuthLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const { t } = useTranslation('common');

  return (
    <main className="min-h-[100dvh] flex bg-background text-foreground">
      {/* Левая брендовая панель (десктоп) */}
      <div
        // Панель всегда тёмная (#0b0b0b) независимо от темы, поэтому текст внутри
        // принудительно светлый: токены (text-foreground/muted) в светлой теме
        // давали бы тёмный текст на тёмном фоне.
        // data-theme="dark" помечает её как «тёмный остров»: в светлой теме это
        // возвращает акцентному тексту внутри яркое золото (см. --accent-text
        // в globals.css), иначе он потемнел бы и пропал на чёрном фоне.
        data-theme="dark"
        className="relative hidden lg:flex flex-col justify-between w-[46%] xl:w-[42%] p-12 overflow-hidden text-white"
        style={{
          background:
            "radial-gradient(120% 90% at 0% 0%, rgba(245,197,24,0.14), transparent 55%), radial-gradient(100% 80% at 100% 100%, rgba(245,197,24,0.08), transparent 60%), #0b0b0b",
        }}
      >
        <EsaiLogo tone="ondark" className="h-9 w-auto" />

        <div className="space-y-6 max-w-md">
          <h2 className="text-4xl xl:text-5xl font-extrabold leading-[1.1]">
            {t("auth.hero_title", { defaultValue: "EsAI — Все нейросети в одном месте." })}
          </h2>
          <p className="text-base text-white/65">
            {t("auth.hero_subtitle", { defaultValue: "Без лишних трат и подписок." })}
          </p>
          <div className="text-accent font-medium">
            <TextSlider
              slides={[t('auth.welcome'), t('auth.gpt'), t('auth.you_can')]}
              delay={3000}
            />
          </div>
        </div>

        <p className="text-sm text-white/45">© EsAI — esai.kg</p>
      </div>

      {/* Область формы. Вертикальные отступы учитывают вырезы iOS (safe-area) в
          PWA, чтобы форма/лого не липли к системной строке и home-индикатору. */}
      <div className="flex-1 flex items-center justify-center px-5 sm:px-8 pt-[max(1.25rem,env(safe-area-inset-top,0px))] pb-[max(1.25rem,env(safe-area-inset-bottom,0px))] overflow-auto">
        <div className="w-full max-w-md">{children}</div>
      </div>
    </main>
  );
}

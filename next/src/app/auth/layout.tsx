'use client';
import TextSlider from "@/components/ui/sliders/TextSlider";
import { useTranslation } from "react-i18next";

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
        className="relative hidden lg:flex flex-col justify-between w-[46%] xl:w-[42%] p-12 overflow-hidden"
        style={{
          background:
            "radial-gradient(120% 90% at 0% 0%, rgba(245,197,24,0.14), transparent 55%), radial-gradient(100% 80% at 100% 100%, rgba(245,197,24,0.08), transparent 60%), #0b0b0b",
        }}
      >
        <img src="/esai-logo.svg" alt="EsAI" className="h-9 w-auto" />

        <div className="space-y-6 max-w-md">
          <h2 className="text-4xl xl:text-5xl font-extrabold leading-[1.1]">
            Все AI в одном месте
          </h2>
          <p className="text-base text-muted">
            ChatGPT, DeepSeek, Claude, Gemini, Grok, Mistral, Perplexity — один чат,
            оплата в сомах.
          </p>
          <div className="text-accent font-medium">
            <TextSlider
              slides={[t('auth.welcome'), t('auth.gpt'), t('auth.you_can')]}
              delay={3000}
            />
          </div>
        </div>

        <p className="text-sm text-muted-2">© EsAI — esai.kg</p>
      </div>

      {/* Область формы */}
      <div className="flex-1 flex items-center justify-center p-5 sm:p-8 overflow-auto">
        <div className="w-full max-w-md">{children}</div>
      </div>
    </main>
  );
}

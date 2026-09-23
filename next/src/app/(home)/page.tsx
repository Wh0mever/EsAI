import "@/assets/style.scss";
import type { Metadata } from "next";
import ChatWorkspace from "@/components/chat/ChatWorkspace";
import HomeHero from "@/components/home/HomeHero";
import WhyEsAI from "@/components/home/WhyEsAI";
import PopularModels from "@/components/home/PopularModels";
import ChatGPTComparison from "@/components/home/ChatGPTComparison";
import HomePricingPreview from "@/components/home/HomePricingPreview";
import HomeCreditsExplainer from "@/components/home/HomeCreditsExplainer";
import HomeFAQ from "@/components/home/HomeFAQ";
import HomeFinalCTA from "@/components/home/HomeFinalCTA";
import Footer from "@/components/main/Footer";

// Root page = the working chat, with HomeHero pitching the product right
// under the chat's own top bar (no separate landing route). Client wanted
// BOTH: the chat header (menu/logo/balance) as the literal first thing on
// screen, AND Hero prominent near the top — reconciled by having
// ChatWorkspace render HomeHero itself via heroSlot (right after its
// header, above the start screen) instead of HomeHero sitting above
// ChatWorkspace as a separate sibling. The chat's own start screen no
// longer repeats the slogan (removed from StartScreen.tsx — it would
// duplicate HomeHero right above it).
// WhyEsAI is ALSO relocated up into the start screen (via
// belowComposerSlot, rendered between the composer and the /studio banner)
// — client explicitly asked for "Почему EsAI" right after the chat, before
// the cartoons banner.
// Scrolling down past the chat reveals the marketing landing (Popular
// models → Comparison → Pricing preview → Credits explainer → FAQ → Final
// CTA), then the footer.
//
// Раньше эти секции жили в принудительных data-theme="dark" обёртках, из-за
// чего светлая тема была нерабочей: <html data-theme="light">, а почти вся
// страница всё равно оставалась тёмной. Обёртки убраны — все блоки следуют
// выбранной пользователем теме (см. lib/theme.ts, переключатель в
// ChatSidebar). Секции используют только токены (bg-surface/-2, text-muted,
// border-border, accent), поэтому корректно читаются в обеих темах.
//
// SEO-статья убрана с главной: клиент попросил, чтобы статьи были ТОЛЬКО в
// блоге (/blog).
// Canonical главной живёт здесь, а не в корневом layout — иначе его
// наследовали все страницы без собственного canonical.
export const metadata: Metadata = {
  alternates: { canonical: "/" },
};

export default function Home() {
  return (
    <ChatWorkspace
      heroSlot={<HomeHero />}
      belowComposerSlot={<WhyEsAI />}
      // Витрина под чатом живёт в слоте, а не рядом с ним: как только
      // пользователь отправил первое сообщение, чат разворачивается на весь
      // экран, и все эти блоки скрываются. Иначе страница продолжала
      // прокручиваться вниз к «Популярным моделям» и футеру прямо во время
      // диалога (просьба клиента: «после первого промта — только чат»).
      belowChatSlot={
        <>
          <PopularModels />
          <ChatGPTComparison />
          <HomePricingPreview />
          <HomeCreditsExplainer />
          <HomeFAQ />
          <HomeFinalCTA />
          <Footer />
        </>
      }
    />
  );
}

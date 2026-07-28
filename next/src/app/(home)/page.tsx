import "@/assets/style.scss";
import ChatWorkspace from "@/components/chat/ChatWorkspace";
import HomeHero from "@/components/home/HomeHero";
import WhyEsAI from "@/components/home/WhyEsAI";
import PopularModels from "@/components/home/PopularModels";
import ChatGPTComparison from "@/components/home/ChatGPTComparison";
import HomePricingPreview from "@/components/home/HomePricingPreview";
import HomeCreditsExplainer from "@/components/home/HomeCreditsExplainer";
import HomeFAQ from "@/components/home/HomeFAQ";
import HomeFinalCTA from "@/components/home/HomeFinalCTA";
import HomeArticleSection from "@/components/home/HomeArticleSection";
import Footer from "@/components/main/Footer";
import { getHomeArticle, articleTitle, articleBody } from "@/lib/content";

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
// the cartoons banner, instead of further down the page. It's therefore
// removed from its old spot in the marketing block below.
// Scrolling down past the chat reveals the remaining 6-section marketing
// landing (Popular models → Comparison → Pricing preview → Credits
// explainer → FAQ → Final CTA), then the flagship SEO article + footer
// (ai-flip.ru-style), with the same reveal/progress/outline animations.
//
// data-theme="dark" is forced on HomeHero and WhyEsAI (wrapped where each
// is passed into its slot below) and on the marketing/article/footer
// subtree because those sections are visually designed only for the dark
// palette (decorative glows, vendor-chip colors over a dark surface) — the
// page's actual theme can be "light" via THEME_BOOTSTRAP (lib/theme.ts)
// reacting to system/localStorage preference. ChatWorkspace itself is NOT
// wrapped: it manages its own theme-independent dark styling.
export default async function Home() {
  const article = await getHomeArticle();
  return (
    <>
      <ChatWorkspace
        heroSlot={
          <div data-theme="dark" className="bg-background text-foreground">
            <HomeHero />
          </div>
        }
        belowComposerSlot={
          <div data-theme="dark" className="bg-background text-foreground">
            <WhyEsAI />
          </div>
        }
      />
      <div data-theme="dark" className="bg-background text-foreground">
        <PopularModels />
        <ChatGPTComparison />
        <HomePricingPreview />
        <HomeCreditsExplainer />
        <HomeFAQ />
        <HomeFinalCTA />
        {article && (
          <HomeArticleSection
            title={articleTitle(article)}
            body={articleBody(article)}
            slug={article.slug}
          />
        )}
        <Footer />
      </div>
    </>
  );
}

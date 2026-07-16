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

// Root page = working chat (no landing). The chat works anonymously; the
// start screen with slogan/composer shows until the first message.
// ChatWorkspace fills the first 100dvh screen (no body scroll-lock), so
// scrolling down past it reveals the 8-section marketing landing (Hero →
// Why EsAI → Popular models → Comparison → Pricing preview → Credits
// explainer → FAQ → Final CTA), then the flagship SEO article + footer
// (ai-flip.ru-style), with the same reveal/progress/outline animations.
export default async function Home() {
  const article = await getHomeArticle();
  return (
    <>
      <ChatWorkspace />
      {/*
        Everything below the chat is forced to the DARK palette. The chat
        hardcodes a dark body (assets/style.scss: body{background:#000;color:#fff}),
        so in a user's LIGHT theme var(--background) would turn white while the
        inherited text stays white — invisible. data-theme="dark" re-establishes
        the dark tokens for this whole subtree (marketing sections + article +
        footer) regardless of the global theme preference.
      */}
      <div data-theme="dark" className="bg-background text-foreground">
        <HomeHero />
        <WhyEsAI />
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

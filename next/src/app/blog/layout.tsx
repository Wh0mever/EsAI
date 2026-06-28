import type { Metadata } from "next";
import { SITE_NAME, SITE_URL } from "@/lib/seo/site";

export const metadata: Metadata = {
  title: `Блог — ${SITE_NAME}`,
  description:
    "Статьи о нейросетях, ИИ-инструментах и о том, как использовать EsAI: ChatGPT, Claude, Gemini, DeepSeek и другие модели на русском и кыргызском.",
  alternates: { canonical: `${SITE_URL}/blog` },
};

// The blog uses the brand SeoShell (its own header/footer), so the layout is a
// thin pass-through that only contributes default metadata.
export default function BlogLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

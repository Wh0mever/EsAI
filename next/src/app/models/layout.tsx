import type { Metadata } from "next";
import Header from "@/components/main/Header";
import Footer from "@/components/main/Footer";
import { SITE_NAME, SITE_URL, OG_IMAGE } from "@/lib/seo/site";
import { breadcrumbJsonLd } from "@/lib/seo/jsonLd";

// Каталог AI-моделей (Этап 4, п.15 ТЗ) — отдельная публичная SEO-страница,
// закрывающая ссылку "Смотреть все модели" с главной (home/PopularModels.tsx).
// Список моделей на самой странице тянется динамически из ai/models/ (см.
// page.tsx), поэтому здесь достаточно статичного metadata — как в
// pricing/layout.tsx и faq/layout.tsx (dynamicParams тут не нужен, у /models
// нет сегментов).
export const metadata: Metadata = {
  title: `Каталог AI-моделей — все нейросети EsAI в одном месте`,
  description:
    "Все нейросети EsAI в одном каталоге: ChatGPT, Claude, Gemini, DeepSeek, Grok, Perplexity и другие модели для текста, кода, изображений и видео. Сравните возможности, стоимость в кредитах и выберите подходящую.",
  alternates: { canonical: `${SITE_URL}/models` },
  openGraph: {
    title: "Каталог AI-моделей EsAI",
    description:
      "Сравните все доступные нейросети EsAI — текст, код, изображения, видео — и выберите подходящую для своей задачи.",
    url: `${SITE_URL}/models`,
    siteName: SITE_NAME,
    type: "website",
    // Next.js не домерживает openGraph/twitter по полям — если сегмент задаёт
    // свой openGraph, он ЦЕЛИКОМ заменяет родительский (из root layout.tsx),
    // включая images. Поэтому og:image/twitter:image нужно повторить явно —
    // тем же сайт-wide баннером (OG_IMAGE), что и на главной. Страница-каталог
    // не привязана к одной модели, поэтому статичный баннер уместнее, чем
    // паттерн генерации per-slug превью (см. model/[slug]/opengraph-image.tsx).
    images: [{ url: OG_IMAGE }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Каталог AI-моделей EsAI",
    description:
      "Сравните все доступные нейросети EsAI — текст, код, изображения, видео — и выберите подходящую для своей задачи.",
    images: [OG_IMAGE],
  },
};

export default function ModelsLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const breadcrumb = breadcrumbJsonLd([
    { name: "Главная", url: "/" },
    { name: "Каталог AI-моделей", url: "/models" },
  ]);

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumb) }}
      />
      <Header />
      {children}
      <Footer />
    </>
  );
}

import type { Metadata } from "next";
import Header from "@/components/main/Header";
import Footer from "@/components/main/Footer";
import { OG_IMAGE, OG_IMAGE_ALT, OG_IMAGE_META, SITE_NAME, SITE_URL } from "@/lib/seo/site";
import { CREATIVE_NAV } from "@/lib/nav/menu";

// Creative Studio. Пока раздел не открыт всем (флаг NEXT_PUBLIC_CREATIVE_NAV),
// страница закрыта от поиска и не входит в карту сайта (план, этап A3). С флагом
// "1" — индексируется и попадает в sitemap.ts вместе со страницами инструментов.
export const metadata: Metadata = {
	title: `Creative Studio — 15 AI-инструментов для видео, изображений и рекламы | ${SITE_NAME}`,
	description:
		"Перенос движения, замена объектов, изменение стиля видео, портреты, AI-персонажи и рекламные визуалы — 15 творческих инструментов EsAI в одном месте.",
	alternates: { canonical: "/creative" },
	robots: { index: CREATIVE_NAV, follow: true },
	openGraph: {
		images: [OG_IMAGE_META],
		title: "Creative Studio — 15 AI-инструментов | EsAI",
		description: "Видео, изображения, AI-персонажи и реклама — 15 творческих инструментов EsAI.",
		url: `${SITE_URL}/creative`,
		siteName: SITE_NAME,
		type: "website",
	},
	twitter: {
		card: "summary_large_image",
		title: "Creative Studio — 15 AI-инструментов | EsAI",
		description: "Видео, изображения, AI-персонажи и реклама — 15 творческих инструментов EsAI.",
		images: [{ url: OG_IMAGE, alt: OG_IMAGE_ALT }],
	},
};

export default function CreativeLayout({ children }: Readonly<{ children: React.ReactNode }>) {
	return (
		<div className="min-h-[100dvh] bg-background text-foreground">
			<Header />
			{children}
			<Footer />
		</div>
	);
}

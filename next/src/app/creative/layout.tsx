import type { Metadata } from "next";
import Header from "@/components/main/Header";
import Footer from "@/components/main/Footer";
import { SITE_NAME } from "@/lib/seo/site";

// Creative Studio. Пока раздел не открыт всем, страница закрыта от поиска и
// не входит в карту сайта (план, этап A3). Открыть — убрать robots и добавить
// /creative в sitemap.ts.
export const metadata: Metadata = {
	title: `Creative Studio — 15 AI-инструментов для видео, изображений и рекламы | ${SITE_NAME}`,
	description:
		"Перенос движения, замена объектов, изменение стиля видео, портреты, AI-персонажи и рекламные визуалы — 15 творческих инструментов EsAI в одном месте.",
	alternates: { canonical: "/creative" },
	robots: { index: false, follow: true },
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

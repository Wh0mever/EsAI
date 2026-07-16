import type { Metadata } from "next";
import Header from "@/components/main/Header";
import Footer from "@/components/main/Footer";
import { SITE_NAME, SITE_URL } from "@/lib/seo/site";

export const metadata: Metadata = {
	title: "Создание мультфильмов — студия EsAI: сценарий, персонажи, видео",
	description:
		"Придумайте историю, нарисуйте героев и оживите их в видео — прямо в EsAI, без навыков. Пошаговая студия: ИИ пишет сценарий, рисует персонажей и создаёт видео.",
	alternates: { canonical: `${SITE_URL}/studio` },
	openGraph: {
		title: "Создание мультфильмов — студия EsAI",
		description:
			"От идеи до готового мультфильма: ИИ напишет сценарий, нарисует героев и оживит их в видео. Без навыков.",
		url: `${SITE_URL}/studio`,
		siteName: SITE_NAME,
		type: "website",
	},
};

export default function StudioLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	return (
		<>
			<Header />
			{children}
			<Footer />
		</>
	);
}

import type { Metadata } from "next";
import Header from "@/components/main/Header";
import Footer from "@/components/main/Footer";
import { SITE_NAME, SITE_URL } from "@/lib/seo/site";

export const metadata: Metadata = {
	title: `О нас — ${SITE_NAME}`,
	description:
		"EsAI — агрегатор флагманских нейросетей в одном месте: ChatGPT, DeepSeek, Claude, Gemini, Grok и Perplexity. Без лишних трат и подписок, оплата в сомах.",
	alternates: { canonical: `${SITE_URL}/about` },
};

export default function RootLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	return (
		// Страница следует выбранной пользователем теме: цвета внутри — на токенах.
		<div className="min-h-[100dvh] bg-background text-foreground">
			<Header />
			{children}
			<Footer />
		</div>
	);
}

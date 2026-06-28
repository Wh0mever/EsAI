import type { Metadata } from "next";
import Header from "@/components/main/Header";
import Footer from "@/components/main/Footer";
import { SITE_NAME, SITE_URL } from "@/lib/seo/site";

export const metadata: Metadata = {
	title: `О нас — ${SITE_NAME}`,
	description:
		"EsAI — агрегатор флагманских нейросетей в одном месте: ChatGPT, DeepSeek, Claude, Gemini, Grok, Mistral и Perplexity. Без лишних трат и подписок, оплата в сомах.",
	alternates: { canonical: `${SITE_URL}/about` },
};

export default function RootLayout({
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

import type { Metadata } from "next";
import Header from "@/components/main/Header";
import Footer from "@/components/main/Footer";
import { SITE_NAME, SITE_URL } from "@/lib/seo/site";
import { tokenPackagesJsonLd } from "@/lib/seo/jsonLd";

export const metadata: Metadata = {
	title: `Тарифы EsAI — пакеты кредитов, оплата в сомах без подписок`,
	description:
		"Пакеты кредитов EsAI: Старт — 190 сом, Про — 490 сом, Премиум — 990 сом, Максимум — 1990 сом. Доступ ко всем нейросетям (ChatGPT, Claude, Gemini, DeepSeek, Grok, Perplexity). Оплата в кыргызских сомах, без подписок.",
	alternates: { canonical: `${SITE_URL}/pricing` },
	openGraph: {
		title: "Тарифы EsAI — оплата в сомах, без подписок",
		description:
			"Пакеты кредитов EsAI: Старт 190, Про 490, Премиум 990, Максимум 1990 сом. Все нейросети в одном месте.",
		url: `${SITE_URL}/pricing`,
		siteName: SITE_NAME,
		type: "website",
	},
};

export default function RootLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	return (
		<>
			{/* Product/AggregateOffer для rich-результата по ценам в выдаче. */}
			<script
				type="application/ld+json"
				dangerouslySetInnerHTML={{ __html: JSON.stringify(tokenPackagesJsonLd()) }}
			/>
			<Header />
			{children}
			<Footer />
		</>
	);
}

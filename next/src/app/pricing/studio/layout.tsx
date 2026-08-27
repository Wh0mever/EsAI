import type { Metadata } from "next";
import Header from "@/components/main/Header";
import Footer from "@/components/main/Footer";
import { SITE_NAME, SITE_URL } from "@/lib/seo/site";

export const metadata: Metadata = {
	title: "Тарифы Cartoon Studio — сколько стоит собрать мультфильм в EsAI",
	description:
		"Сколько кредитов уходит на мультфильм в студии EsAI: персонаж, сцена, склейка. Разовые пакеты без подписки — 490, 990 и 1990 сом. Оплата картой в сомах и рублях.",
	alternates: { canonical: `${SITE_URL}/pricing/studio` },
	openGraph: {
		title: "Тарифы Cartoon Studio — EsAI",
		description:
			"Разовые пакеты кредитов для студии мультфильмов EsAI. Без подписки: заплатили один раз, кредиты не сгорают.",
		url: `${SITE_URL}/pricing/studio`,
		siteName: SITE_NAME,
		type: "website",
	},
};

export default function StudioPricingLayout({
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

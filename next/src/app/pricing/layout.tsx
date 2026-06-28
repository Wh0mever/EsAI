import type { Metadata } from "next";
import Header from "@/components/main/Header";
import Footer from "@/components/main/Footer";
import { SITE_NAME, SITE_URL } from "@/lib/seo/site";

export const metadata: Metadata = {
	title: `Цены и тарифы — ${SITE_NAME}`,
	description:
		"Тарифы EsAI: доступ ко всем флагманским нейросетям в одном месте. Удобная оплата в кыргызских сомах, без лишних трат и подписок.",
	alternates: { canonical: `${SITE_URL}/pricing` },
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

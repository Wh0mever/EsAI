import type { Metadata } from "next";
import Header from "@/components/main/Header";
import Footer from "@/components/main/Footer";
import { SITE_NAME, SITE_URL } from "@/lib/seo/site";

export const metadata: Metadata = {
	title: `Часто задаваемые вопросы — ${SITE_NAME}`,
	description:
		"Ответы на частые вопросы об EsAI: какие нейросети доступны, как работает оплата в сомах, тарифы и токены, поддержка и безопасность.",
	alternates: { canonical: `${SITE_URL}/faq` },
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
